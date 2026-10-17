"""Enrutamiento hacia los microservicios (patrón API Gateway)."""
import logging
import os

import httpx
from fastapi import Request, Response
from fastapi.responses import JSONResponse

log = logging.getLogger("gateway")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")


def _url(nombre: str, defecto: str) -> str:
    """Acepta URL completa o solo el host. En Render se recibe el host público
    (RENDER_EXTERNAL_HOSTNAME), porque los servicios gratuitos no reciben tráfico privado."""
    url = (os.getenv(nombre) or defecto).strip().rstrip("/")
    if url.startswith(("http://", "https://")):
        return url
    local = url.startswith(("localhost", "127.", "0.0.0.0")) or ":" in url
    return f"{'http' if local else 'https'}://{url}"


SERVICIOS = {
    "catalogo": _url("CATALOGO_URL", "http://localhost:8001"),
    "pedidos": _url("PEDIDOS_URL", "http://localhost:8002"),
    "pagos": _url("PAGOS_URL", "http://localhost:8003"),
    "notificaciones": _url("NOTIFICACIONES_URL", "http://localhost:8004"),
}
# La creación de pedidos ejecuta la Saga completa (con reintentos de pago): necesita más tiempo.
TIMEOUT = httpx.Timeout(float(os.getenv("GATEWAY_TIMEOUT", "60")), connect=15.0)
_clientes = {nombre: httpx.AsyncClient(base_url=url, timeout=TIMEOUT) for nombre, url in SERVICIOS.items()}


def cabeceras_internas(usuario=None) -> dict:
    h = {"X-Internal-Token": INTERNAL_TOKEN}
    if usuario is not None:
        h["X-User-Id"] = usuario.id
        h["X-User-Rol"] = usuario.rol
    return h


async def reenviar(servicio: str, ruta: str, request: Request, cuerpo: bytes = b"", usuario=None,
             params: dict | None = None) -> Response:
    cabeceras = cabeceras_internas(usuario)
    if cuerpo:
        cabeceras["Content-Type"] = "application/json"
    try:
        r = await _clientes[servicio].request(request.method, ruta, content=cuerpo or None,
                                        params=params if params is not None else dict(request.query_params),
                                        headers=cabeceras)
    except httpx.HTTPError as e:
        log.error(f"{servicio} no disponible: {e}")
        return JSONResponse({"detail": f"El servicio de {servicio} no está disponible en este momento"},
                            status_code=503)
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))


async def consultar_salud(servicio: str) -> dict:
    try:
        r = await _clientes[servicio].get("/health", timeout=10)
        datos = r.json()
        datos["http"] = r.status_code
        return datos
    except Exception as e:
        return {"servicio": f"{servicio}-service", "estado": "caido", "error": str(e)[:120]}
