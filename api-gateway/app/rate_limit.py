"""Limitación de peticiones por cliente (ventana fija de 60 s) en el API Gateway."""
import os
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

LIMITE = int(os.getenv("RATE_LIMIT_POR_MINUTO", "300"))
EXENTAS = {"/health", "/docs", "/openapi.json"}


class LimitadorPeticiones(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._ventanas: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _cliente(request: Request) -> str:
        reenviado = request.headers.get("x-forwarded-for")
        if reenviado:
            return reenviado.split(",")[0].strip()
        return request.client.host if request.client else "desconocido"

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXENTAS or request.method == "OPTIONS" or LIMITE <= 0:
            return await call_next(request)
        clave = self._cliente(request)
        ventana = int(time.time() // 60)
        with self._lock:
            v, n = self._ventanas.get(clave, (ventana, 0))
            n = n + 1 if v == ventana else 1
            self._ventanas[clave] = (ventana, n)
            if len(self._ventanas) > 10000:
                self._ventanas = {k: x for k, x in self._ventanas.items() if x[0] == ventana}
        if n > LIMITE:
            return JSONResponse({"detail": "Demasiadas peticiones, intenta en un minuto"}, status_code=429,
                                headers={"Retry-After": str(60 - int(time.time()) % 60)})
        respuesta = await call_next(request)
        respuesta.headers["X-RateLimit-Limit"] = str(LIMITE)
        respuesta.headers["X-RateLimit-Remaining"] = str(max(0, LIMITE - n))
        return respuesta
