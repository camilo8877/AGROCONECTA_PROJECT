"""Patrón Saga orquestada (Garcia-Molina y Salem, 1987; Richardson, 2018).

Pasos y compensaciones:
    1. Reservar inventario (catálogo)   <- compensación: liberar inventario
    2. Cobrar el pedido (pagos)          <- (paso pivote: si se aprueba, la Saga avanza)
    3. Confirmar la reserva (catálogo)
El estado de cada Saga queda guardado en la tabla saga_pedido.
"""
import logging

from sqlalchemy.orm import Session

from .. import eventos
from ..clients.servicios import CatalogoCliente, PagoRechazado, PagosCliente, ServicioNoDisponible, SinInventario
from ..models import EstadoPedido, Pedido, SagaPedido

log = logging.getLogger("pedidos")


class ResultadoSaga:
    def __init__(self, pedido: Pedido, codigo: int):
        self.pedido = pedido
        self.codigo = codigo  # 201 pagado · 409 rechazado/sin stock · 503 servicio no disponible


def ejecutar_saga(db: Session, pedido: Pedido, catalogo: CatalogoCliente | None = None,
                  pagos: PagosCliente | None = None) -> ResultadoSaga:
    catalogo = catalogo or CatalogoCliente()
    pagos = pagos or PagosCliente()
    saga = SagaPedido(pedido_id=pedido.id)
    saga.registrar("INICIADA")
    db.add(saga)
    db.commit()
    items = [{"producto_id": d.producto_id, "cantidad": d.cantidad} for d in pedido.detalles]

    # Paso 1: reservar inventario
    try:
        catalogo.reservar(pedido.id, items)
    except SinInventario as e:
        return _cancelar(db, pedido, saga, catalogo, str(e), 409, compensar=False)
    except ServicioNoDisponible as e:
        return _cancelar(db, pedido, saga, catalogo, str(e), 503, compensar=True)
    saga.registrar("STOCK_RESERVADO")
    pedido.estado = EstadoPedido.RESERVADO.value
    db.commit()

    # Paso 2: cobrar (Circuit Breaker y Retry viven en pagos-service)
    try:
        pago = pagos.cobrar(pedido.id, float(pedido.total))
    except PagoRechazado as e:
        return _cancelar(db, pedido, saga, catalogo, f"Pago rechazado: {e}", 409, compensar=True)
    except ServicioNoDisponible as e:
        return _cancelar(db, pedido, saga, catalogo, str(e), 503, compensar=True)
    saga.registrar("PAGADO", f"referencia {pago.get('referencia_pasarela')}")
    pedido.estado = EstadoPedido.PAGADO.value
    db.commit()

    # Paso 3: confirmar la reserva como venta
    try:
        catalogo.confirmar(pedido.id)
        saga.registrar("COMPLETADA")
    except Exception as e:  # el pago ya está hecho: se deja pendiente para reproceso
        log.error(f"No se pudo confirmar la reserva del pedido {pedido.id}: {e}")
        saga.registrar("CONFIRMACION_PENDIENTE", str(e))
    db.commit()

    eventos.publicar("pedido.pagado", pedido.resumen())
    log.info(f"Saga completada pedido={pedido.id}")
    return ResultadoSaga(pedido, 201)


def _cancelar(db: Session, pedido: Pedido, saga: SagaPedido, catalogo: CatalogoCliente, motivo: str, codigo: int,
              compensar: bool) -> ResultadoSaga:
    paso_final = "CANCELADA"
    if compensar:
        try:
            catalogo.liberar(pedido.id)            # transacción compensatoria
            paso_final = "COMPENSADA"
        except Exception as e:
            log.error(f"Compensación pendiente para el pedido {pedido.id}: {e}")
            paso_final = "COMPENSACION_PENDIENTE"
    pedido.estado = EstadoPedido.CANCELADO.value
    pedido.motivo_cancelacion = motivo[:300]
    saga.registrar(paso_final, motivo[:200])
    db.commit()
    eventos.publicar("pedido.cancelado", pedido.resumen(motivo=motivo))
    log.info(f"Saga cancelada pedido={pedido.id} motivo={motivo}")
    return ResultadoSaga(pedido, codigo)
