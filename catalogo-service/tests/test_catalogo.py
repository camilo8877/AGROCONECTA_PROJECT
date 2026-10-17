from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.services import catalogo

PRODUCTOR = {"X-User-Id": "11111111-1111-1111-1111-111111111111", "X-User-Rol": "productor"}


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def _producto(cliente, nombre):
    return next(p for p in cliente.get("/productos").json() if p["nombre"].startswith(nombre))


def test_catalogo_con_datos_iniciales(cliente):
    productos = cliente.get("/productos").json()
    assert len(productos) >= 8
    assert all("disponible" in p for p in productos)


def test_cache_aside_acierta_y_se_invalida(cliente):
    p = _producto(cliente, "Aguacate")
    cliente.post("/cache/estadisticas/reiniciar")
    for _ in range(10):
        cliente.get(f"/productos/{p['id']}")
    stats = cliente.get("/cache/estadisticas").json()
    assert stats["aciertos"] >= 9
    r = cliente.patch(f"/productos/{p['id']}", json={"precio": 9900}, headers=PRODUCTOR)
    assert r.status_code == 200
    assert cliente.get(f"/productos/{p['id']}").json()["precio"] == 9900  # la caché se invalidó


def test_solo_el_dueno_modifica(cliente):
    p = _producto(cliente, "Fresa")
    otro = {"X-User-Id": "otro", "X-User-Rol": "productor"}
    assert cliente.patch(f"/productos/{p['id']}", json={"precio": 1}, headers=otro).status_code == 403


def test_reserva_todo_o_nada_y_compensacion(cliente):
    leche, queso = _producto(cliente, "Leche"), _producto(cliente, "Queso")
    items = [{"producto_id": leche["id"], "cantidad": 1}, {"producto_id": queso["id"], "cantidad": 10_000}]
    assert cliente.post("/inventario/reservar", json={"pedido_id": "x1", "items": items}).status_code == 409
    assert _producto(cliente, "Leche")["disponible"] == leche["disponible"]  # rollback completo

    items = [{"producto_id": leche["id"], "cantidad": 5}]
    assert cliente.post("/inventario/reservar", json={"pedido_id": "x2", "items": items}).status_code == 200
    assert _producto(cliente, "Leche")["disponible"] == leche["disponible"] - 5
    cliente.post("/inventario/liberar", json={"pedido_id": "x2"})
    assert _producto(cliente, "Leche")["disponible"] == leche["disponible"]


def test_reserva_idempotente(cliente):
    papa = _producto(cliente, "Papa")
    cuerpo = {"pedido_id": "x3", "items": [{"producto_id": papa["id"], "cantidad": 2}]}
    cliente.post("/inventario/reservar", json=cuerpo)
    cliente.post("/inventario/reservar", json=cuerpo)  # reintento
    assert _producto(cliente, "Papa")["disponible"] == papa["disponible"] - 2


def test_concurrencia_sin_sobreventa(cliente):
    mora = _producto(cliente, "Mora")
    cliente.patch(f"/productos/{mora['id']}/inventario", json={"disponible": 5}, headers=PRODUCTOR)

    def intentar(i):
        with SessionLocal() as db:
            try:
                catalogo.reservar(db, f"c{i}", [{"producto_id": mora["id"], "cantidad": 1}])
                return True
            except Exception:
                return False

    with ThreadPoolExecutor(max_workers=10) as ex:
        exitos = sum(ex.map(intentar, range(20)))
    assert exitos == 5
    assert _producto(cliente, "Mora")["disponible"] == 0


def test_health(cliente):
    assert cliente.get("/health").json()["estado"] == "ok"
