"""pedidos-service: ciclo de vida del pedido y orquestación de la Saga."""
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import eventos
from .clients.servicios import CatalogoCliente, ProductoNoEncontrado, ServicioNoDisponible
from .comun import configurar_logs, usuario_desde_headers, verificar_token_interno
from .db import db_ok, get_db, init_db
from .models import DetallePedido, EstadoPedido, Pedido
from .saga.orquestador import ejecutar_saga

log = configurar_logs("pedidos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("pedidos-service iniciado")
    yield


app = FastAPI(title="AgroConecta · pedidos-service", version="1.0.0", lifespan=lifespan)
router = APIRouter(dependencies=[Depends(verificar_token_interno)])

TRANSICIONES = {
    EstadoPedido.PAGADO.value: {EstadoPedido.DESPACHADO.value},
    EstadoPedido.DESPACHADO.value: {EstadoPedido.ENTREGADO.value},
}


class ItemIn(BaseModel):
    producto_id: str
    cantidad: int = Field(gt=0, le=1000)


class PedidoIn(BaseModel):
    items: list[ItemIn] = Field(min_length=1, max_length=50)


class CambioEstado(BaseModel):
    estado: str


def _puede_ver(pedido: Pedido, usuario: dict) -> bool:
    return (usuario.get("rol") == "admin" or pedido.comprador_id == usuario.get("id")
            or usuario.get("id") in pedido.productor_ids())


@router.post("/pedidos", tags=["pedidos"])
def crear_pedido(body: PedidoIn, db: Session = Depends(get_db), usuario: dict = Depends(usuario_desde_headers)):
    if usuario.get("rol") != "comprador" or not usuario.get("id"):
        raise HTTPException(403, "Solo los compradores pueden realizar pedidos")

    # Agrupar ítems repetidos y tomar precio y nombre vigentes del catálogo
    cantidades: dict[str, int] = defaultdict(int)
    for item in body.items:
        cantidades[item.producto_id] += item.cantidad
    catalogo = CatalogoCliente()
    pedido = Pedido(comprador_id=usuario["id"])
    try:
        for producto_id, cantidad in cantidades.items():
            p = catalogo.obtener_producto(producto_id)
            if not p.get("activo", True):
                raise HTTPException(409, f"El producto {p['nombre']} no está disponible")
            pedido.detalles.append(DetallePedido(
                producto_id=producto_id, productor_id=p["productor_id"], nombre_producto=p["nombre"],
                unidad=p["unidad"], cantidad=cantidad, precio_unitario=p["precio"]))
    except ProductoNoEncontrado as e:
        raise HTTPException(404, f"Producto no encontrado: {e}") from e
    except ServicioNoDisponible as e:
        raise HTTPException(503, str(e)) from e
    pedido.total = sum(d.subtotal() for d in pedido.detalles)
    db.add(pedido)
    db.commit()
    log.info(f"Pedido creado {pedido.id} total={pedido.total}")

    resultado = ejecutar_saga(db, pedido, catalogo)
    db.refresh(resultado.pedido)
    return JSONResponse(resultado.pedido.a_dict(), status_code=resultado.codigo)


@router.get("/pedidos", tags=["pedidos"])
def listar_pedidos(db: Session = Depends(get_db), usuario: dict = Depends(usuario_desde_headers)):
    q = select(Pedido).order_by(Pedido.fecha.desc()).limit(100)
    rol, uid = usuario.get("rol"), usuario.get("id")
    if rol == "comprador":
        q = q.where(Pedido.comprador_id == uid)
    elif rol == "productor":
        q = q.where(Pedido.id.in_(select(DetallePedido.pedido_id).where(DetallePedido.productor_id == uid)))
    elif rol != "admin":
        raise HTTPException(403, "No autorizado")
    return [p.a_dict() for p in db.scalars(q)]


@router.get("/pedidos/{pedido_id}", tags=["pedidos"])
def obtener_pedido(pedido_id: str, db: Session = Depends(get_db), usuario: dict = Depends(usuario_desde_headers)):
    pedido = db.get(Pedido, pedido_id)
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    if not _puede_ver(pedido, usuario):
        raise HTTPException(403, "No autorizado")
    return pedido.a_dict()


@router.patch("/pedidos/{pedido_id}/estado", tags=["pedidos"])
def cambiar_estado(pedido_id: str, body: CambioEstado, db: Session = Depends(get_db),
                   usuario: dict = Depends(usuario_desde_headers)):
    pedido = db.get(Pedido, pedido_id)
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    if usuario.get("rol") != "admin" and usuario.get("id") not in pedido.productor_ids():
        raise HTTPException(403, "Solo el productor del pedido o el administrador pueden cambiar su estado")
    if body.estado not in TRANSICIONES.get(pedido.estado, set()):
        raise HTTPException(409, f"Transición no permitida: {pedido.estado} → {body.estado}")
    pedido.estado = body.estado
    db.commit()
    eventos.publicar(f"pedido.{body.estado.lower()}", pedido.resumen())
    return pedido.a_dict()


@router.post("/pedidos/{pedido_id}/reprocesar", tags=["pedidos"])
def reprocesar_saga(pedido_id: str, db: Session = Depends(get_db), usuario: dict = Depends(usuario_desde_headers)):
    """Reintenta una compensación o confirmación que quedó pendiente por una falla."""
    if usuario.get("rol") != "admin":
        raise HTTPException(403, "Solo el administrador")
    pedido = db.get(Pedido, pedido_id)
    if not pedido or not pedido.saga:
        raise HTTPException(404, "Pedido no encontrado")
    catalogo = CatalogoCliente()
    try:
        if pedido.saga.paso == "COMPENSACION_PENDIENTE":
            catalogo.liberar(pedido.id)
            pedido.saga.registrar("COMPENSADA", "reproceso manual")
        elif pedido.saga.paso == "CONFIRMACION_PENDIENTE":
            catalogo.confirmar(pedido.id)
            pedido.saga.registrar("COMPLETADA", "reproceso manual")
        else:
            raise HTTPException(409, f"La Saga no tiene pasos pendientes (paso actual: {pedido.saga.paso})")
    except ServicioNoDisponible as e:
        raise HTTPException(503, str(e)) from e
    db.commit()
    return pedido.a_dict()


@router.get("/reportes/ventas", tags=["reportes"])
def reporte_ventas(db: Session = Depends(get_db), usuario: dict = Depends(usuario_desde_headers)):
    if usuario.get("rol") != "admin":
        raise HTTPException(403, "Solo el administrador")
    vendidos = {EstadoPedido.PAGADO.value, EstadoPedido.DESPACHADO.value, EstadoPedido.ENTREGADO.value}
    pedidos = list(db.scalars(select(Pedido)))
    por_productor: dict[str, dict] = defaultdict(lambda: {"pedidos": set(), "unidades": 0, "ventas": 0.0})
    for p in pedidos:
        if p.estado not in vendidos:
            continue
        for d in p.detalles:
            r = por_productor[d.productor_id]
            r["pedidos"].add(p.id)
            r["unidades"] += d.cantidad
            r["ventas"] += d.subtotal()
    return {
        "total_pedidos": len(pedidos),
        "pedidos_vendidos": sum(1 for p in pedidos if p.estado in vendidos),
        "pedidos_cancelados": sum(1 for p in pedidos if p.estado == EstadoPedido.CANCELADO.value),
        "ventas_totales": sum(float(p.total) for p in pedidos if p.estado in vendidos),
        "por_productor": [{"productor_id": k, "pedidos": len(v["pedidos"]), "unidades": v["unidades"],
                           "ventas": v["ventas"]} for k, v in por_productor.items()],
    }


app.include_router(router)


@app.get("/health", tags=["observabilidad"])
def health():
    base_datos, broker = db_ok(), eventos.broker_ok()
    cuerpo = {"servicio": "pedidos-service", "estado": "ok" if base_datos and broker else "degradado",
              "dependencias": {"base_datos": base_datos, "broker_eventos": broker}}
    return JSONResponse(cuerpo, status_code=200 if base_datos else 503)
