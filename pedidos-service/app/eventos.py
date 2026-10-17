"""Patrón Publisher/Subscriber: el servicio de pedidos publica eventos de dominio
sin conocer a sus consumidores (hoy, el servicio de notificaciones)."""
import json
import logging
import os
from datetime import UTC, datetime

import redis

log = logging.getLogger("pedidos")
_url = os.getenv("REDIS_URL")
_redis = redis.from_url(_url, decode_responses=True, socket_timeout=2) if _url else None


def publicar(tipo: str, datos: dict) -> None:
    evento = {"tipo": tipo, "fecha": datetime.now(UTC).isoformat(), **datos}
    if not _redis:
        log.info(f"[sin broker] evento {tipo}: {evento}")
        return
    try:
        receptores = _redis.publish(tipo, json.dumps(evento, ensure_ascii=False))
        log.info(f"Evento publicado {tipo} pedido={datos.get('pedido_id')} receptores={receptores}")
    except redis.RedisError as e:
        # La publicación nunca debe tumbar la Saga: el pedido ya quedó registrado.
        log.warning(f"No se pudo publicar {tipo}: {e}")


def broker_ok() -> bool:
    if not _redis:
        return True
    try:
        return bool(_redis.ping())
    except redis.RedisError:
        return False
