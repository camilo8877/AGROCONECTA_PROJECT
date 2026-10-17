"""Clientes HTTP hacia los servicios de catálogo y pagos."""
import os

import httpx

INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")


def _url(nombre: str, defecto: str) -> str:
    """Acepta URL completa o solo el host. En Render se recibe el host público
    (RENDER_EXTERNAL_HOSTNAME), porque los servicios gratuitos no reciben tráfico privado."""
    url = (os.getenv(nombre) or defecto).strip().rstrip("/")
    if url.startswith(("http://", "https://")):
        return url
    local = url.startswith(("localhost", "127.", "0.0.0.0")) or ":" in url
    return f"{'http' if local else 'https'}://{url}"


CATALOGO_URL = _url("CATALOGO_URL", "http://localhost:8001")
PAGOS_URL = _url("PAGOS_URL", "http://localhost:8003")
TIMEOUT = httpx.Timeout(float(os.getenv("HTTP_TIMEOUT", "20")), connect=10.0)


class ServicioNoDisponible(Exception):
    pass


class SinInventario(Exception):
    pass


class PagoRechazado(Exception):
    pass


class ProductoNoEncontrado(Exception):
    pass


def _cliente(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=TIMEOUT, headers={"X-Internal-Token": INTERNAL_TOKEN})


class CatalogoCliente:
    def obtener_producto(self, producto_id: str) -> dict:
        try:
            with _cliente(CATALOGO_URL) as c:
                r = c.get(f"/productos/{producto_id}")
        except httpx.HTTPError as e:
            raise ServicioNoDisponible(f"Catálogo no disponible: {e}") from e
        if r.status_code == 404:
            raise ProductoNoEncontrado(producto_id)
        if r.status_code >= 500:
            raise ServicioNoDisponible("Catálogo no disponible")
        return r.json()

    def _post(self, ruta: str, cuerpo: dict) -> httpx.Response:
        try:
            with _cliente(CATALOGO_URL) as c:
                r = c.post(ruta, json=cuerpo)
        except httpx.HTTPError as e:
            raise ServicioNoDisponible(f"Catálogo no disponible: {e}") from e
        if r.status_code >= 500:
            raise ServicioNoDisponible("Catálogo no disponible")
        return r

    def reservar(self, pedido_id: str, items: list[dict]) -> dict:
        r = self._post("/inventario/reservar", {"pedido_id": pedido_id, "items": items})
        if r.status_code == 409:
            raise SinInventario(r.json().get("detail", "Sin inventario"))
        r.raise_for_status()
        return r.json()

    def liberar(self, pedido_id: str) -> dict:
        r = self._post("/inventario/liberar", {"pedido_id": pedido_id})
        r.raise_for_status()
        return r.json()

    def confirmar(self, pedido_id: str) -> dict:
        r = self._post("/inventario/confirmar", {"pedido_id": pedido_id})
        r.raise_for_status()
        return r.json()


class PagosCliente:
    def cobrar(self, pedido_id: str, monto: float) -> dict:
        try:
            with _cliente(PAGOS_URL) as c:
                r = c.post("/pagos", json={"pedido_id": pedido_id, "monto": monto})
        except httpx.HTTPError as e:
            raise ServicioNoDisponible(f"Servicio de pagos no disponible: {e}") from e
        if r.status_code == 503:
            raise ServicioNoDisponible(r.json().get("motivo") or "Pasarela de pagos no disponible")
        r.raise_for_status()
        pago = r.json()
        if pago["estado"] != "APROBADO":
            raise PagoRechazado(pago.get("motivo") or "Pago rechazado")
        return pago
