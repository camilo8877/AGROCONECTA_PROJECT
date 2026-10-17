"""Caché del catálogo (patrón Cache-Aside).

Usa Redis cuando REDIS_URL está definido y una caché en memoria en caso contrario.
Si Redis falla, la caché se comporta como un fallo de caché: el servicio sigue
respondiendo desde la base de datos (la caché nunca es un punto único de falla).
"""
import json
import logging
import os
import threading
import time

import redis

log = logging.getLogger("catalogo")
TTL_SEGUNDOS = int(os.getenv("CACHE_TTL", "300"))


class CacheCatalogo:
    def __init__(self, url: str | None):
        self._redis = redis.from_url(url, decode_responses=True, socket_timeout=2) if url else None
        self._memoria: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self.aciertos = 0
        self.fallos = 0

    @property
    def backend(self) -> str:
        return "redis" if self._redis else "memoria"

    def get(self, clave: str):
        valor = None
        try:
            if self._redis:
                valor = self._redis.get(clave)
            else:
                with self._lock:
                    item = self._memoria.get(clave)
                    if item and item[0] > time.time():
                        valor = item[1]
        except redis.RedisError as e:
            log.warning(f"Redis no disponible al leer caché: {e}")
        with self._lock:
            if valor is None:
                self.fallos += 1
            else:
                self.aciertos += 1
        return json.loads(valor) if valor is not None else None

    def set(self, clave: str, datos, ttl: int = TTL_SEGUNDOS) -> None:
        valor = json.dumps(datos, default=str)
        try:
            if self._redis:
                self._redis.set(clave, valor, ex=ttl)
            else:
                with self._lock:
                    self._memoria[clave] = (time.time() + ttl, valor)
        except redis.RedisError as e:
            log.warning(f"Redis no disponible al escribir caché: {e}")

    def delete(self, *claves: str) -> None:
        try:
            if self._redis:
                self._redis.delete(*claves)
            else:
                with self._lock:
                    for c in claves:
                        self._memoria.pop(c, None)
        except redis.RedisError as e:
            log.warning(f"Redis no disponible al invalidar caché: {e}")

    def incr(self, clave: str) -> int:
        try:
            if self._redis:
                return int(self._redis.incr(clave))
        except redis.RedisError as e:
            log.warning(f"Redis no disponible: {e}")
        with self._lock:
            actual = int(self._memoria.get(clave, (0, "0"))[1]) + 1
            self._memoria[clave] = (float("inf"), str(actual))
            return actual

    def version_listados(self) -> str:
        """Los listados se invalidan en bloque incrementando un número de versión."""
        try:
            if self._redis:
                return self._redis.get("productos:version") or "0"
        except redis.RedisError:
            return "x"
        with self._lock:
            return self._memoria.get("productos:version", (0, "0"))[1]

    def ping(self) -> bool:
        if not self._redis:
            return True
        try:
            return bool(self._redis.ping())
        except redis.RedisError:
            return False

    def estadisticas(self) -> dict:
        total = self.aciertos + self.fallos
        return {
            "backend": self.backend,
            "aciertos": self.aciertos,
            "fallos": self.fallos,
            "tasa_aciertos": round(self.aciertos / total, 3) if total else 0.0,
        }

    def reiniciar_estadisticas(self) -> None:
        with self._lock:
            self.aciertos = 0
            self.fallos = 0


cache = CacheCatalogo(os.getenv("REDIS_URL"))
