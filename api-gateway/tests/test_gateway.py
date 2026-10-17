from fastapi.testclient import TestClient

from app.main import app


def test_login_y_roles():
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"email": "comprador@agroconecta.co", "clave": "mala"}).status_code == 401
        tok = c.post("/api/auth/login", json={"email": "comprador@agroconecta.co", "clave": "Comprador123*"}).json()
        h = {"Authorization": f"Bearer {tok['access_token']}"}
        assert c.get("/api/auth/yo", headers=h).json()["rol"] == "comprador"
        assert c.post("/api/productos", json={}, headers=h).status_code == 403  # comprador no publica
        assert c.post("/api/pedidos", json={}).status_code == 401  # sin token


def test_productor_nuevo_requiere_validacion():
    with TestClient(app) as c:
        r = c.post("/api/auth/registro", json={"nombre": "Nuevo", "email": "nuevo@finca.co", "clave": "Clave1234",
                                               "rol": "productor"}).json()
        h = {"Authorization": f"Bearer {r['access_token']}"}
        assert r["usuario"]["verificado"] is False
        assert c.post("/api/productos", json={}, headers=h).status_code == 403


def test_servicio_caido_responde_503_controlado():
    with TestClient(app) as c:
        r = c.get("/api/productos")  # no hay catálogo levantado en la prueba
        assert r.status_code == 503 and "no está disponible" in r.json()["detail"]
