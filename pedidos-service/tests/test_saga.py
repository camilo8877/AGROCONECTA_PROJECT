from fastapi.testclient import TestClient

from app.clients.servicios import PagoRechazado, ServicioNoDisponible, SinInventario
from app.db import SessionLocal
from app.main import app
from app.models import DetallePedido, Pedido
from app.saga.orquestador import ejecutar_saga

TestClient(app).__enter__()  # crea las tablas


class CatalogoFalso:
    def __init__(self, sin_stock=False):
        self.sin_stock, self.llamadas = sin_stock, []

    def reservar(self, pedido_id, items):
        self.llamadas.append("reservar")
        if self.sin_stock:
            raise SinInventario("Sin inventario suficiente de Mora")

    def liberar(self, pedido_id):
        self.llamadas.append("liberar")

    def confirmar(self, pedido_id):
        self.llamadas.append("confirmar")


class PagosFalso:
    def __init__(self, error=None):
        self.error = error

    def cobrar(self, pedido_id, monto):
        if self.error:
            raise self.error
        return {"estado": "APROBADO", "referencia_pasarela": "SIM-1"}


def _pedido(db):
    p = Pedido(comprador_id="c1", total=7000)
    p.detalles.append(DetallePedido(producto_id="m", productor_id="p1", nombre_producto="Mora", unidad="kg",
                                    cantidad=1, precio_unitario=7000))
    db.add(p)
    db.commit()
    return p


def test_saga_exitosa():
    with SessionLocal() as db:
        cat = CatalogoFalso()
        r = ejecutar_saga(db, _pedido(db), cat, PagosFalso())
        assert r.codigo == 201 and r.pedido.estado == "PAGADO"
        assert cat.llamadas == ["reservar", "confirmar"]
        assert r.pedido.saga.paso == "COMPLETADA"


def test_pago_rechazado_compensa():
    with SessionLocal() as db:
        cat = CatalogoFalso()
        r = ejecutar_saga(db, _pedido(db), cat, PagosFalso(PagoRechazado("Fondos insuficientes")))
        assert r.codigo == 409 and r.pedido.estado == "CANCELADO"
        assert cat.llamadas == ["reservar", "liberar"]
        assert r.pedido.saga.paso == "COMPENSADA"


def test_pasarela_caida_compensa_con_503():
    with SessionLocal() as db:
        cat = CatalogoFalso()
        r = ejecutar_saga(db, _pedido(db), cat, PagosFalso(ServicioNoDisponible("Circuito abierto")))
        assert r.codigo == 503 and "liberar" in cat.llamadas


def test_sin_stock_no_cobra():
    with SessionLocal() as db:
        cat = CatalogoFalso(sin_stock=True)
        r = ejecutar_saga(db, _pedido(db), cat, PagosFalso(AssertionError("no debe cobrar")))
        assert r.codigo == 409 and cat.llamadas == ["reservar"]
