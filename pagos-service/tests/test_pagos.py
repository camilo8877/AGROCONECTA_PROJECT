import time

import pytest
from fastapi.testclient import TestClient

from app.main import app, breaker, pasarela
from app.resiliencia.circuit_breaker import CircuitBreaker, CircuitoAbierto


def falla():
    raise RuntimeError("caída")


def test_circuito_se_abre_y_se_recupera():
    cb = CircuitBreaker("prueba", umbral_fallos=3, tiempo_recuperacion=0.2)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.llamar(falla)
    assert cb.estado == "ABIERTO"
    with pytest.raises(CircuitoAbierto):  # falla rápida, sin invocar la función
        cb.llamar(lambda: "ok")
    time.sleep(0.25)
    assert cb.llamar(lambda: "ok") == "ok"  # SEMIABIERTO -> CERRADO
    assert cb.estado == "CERRADO"


def test_semiabierto_vuelve_a_abrir():
    cb = CircuitBreaker("prueba", umbral_fallos=1, tiempo_recuperacion=0.1)
    with pytest.raises(RuntimeError):
        cb.llamar(falla)
    time.sleep(0.15)
    with pytest.raises(RuntimeError):
        cb.llamar(falla)
    assert cb.estado == "ABIERTO"


@pytest.fixture()
def cliente():
    pasarela.latencia_ms = 0
    pasarela.tasa_fallo = 0
    breaker.reiniciar()
    with TestClient(app) as c:
        yield c


def test_pago_aprobado_e_idempotente(cliente):
    r1 = cliente.post("/pagos", json={"pedido_id": "p1", "monto": 10000}).json()
    r2 = cliente.post("/pagos", json={"pedido_id": "p1", "monto": 10000}).json()
    assert r1["estado"] == "APROBADO" and r1["id"] == r2["id"]


def test_rechazo_de_negocio_no_abre_el_circuito(cliente):
    r = cliente.post("/pagos", json={"pedido_id": "p2", "monto": 99_000_000})
    assert r.status_code == 200 and r.json()["estado"] == "RECHAZADO"
    assert breaker.estado == "CERRADO"


def test_fallas_tecnicas_abren_el_circuito(cliente):
    pasarela.tasa_fallo = 1
    for i in range(3):
        r = cliente.post("/pagos", json={"pedido_id": f"f{i}", "monto": 1000})
        assert r.status_code == 503
        assert r.json()["intentos"] == 3  # Retry antes de contar el fallo
    r = cliente.post("/pagos", json={"pedido_id": "f4", "monto": 1000})
    assert r.status_code == 503 and r.json()["intentos"] == 0  # circuito abierto: ni se intenta
    assert cliente.get("/pagos/estado-circuito").json()["estado"] == "ABIERTO"
