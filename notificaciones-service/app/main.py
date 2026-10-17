"""notificaciones-service: suscriptor de eventos de pedidos (patrón Publisher/Subscriber).

Escucha los canales pedido.* en Redis y genera una notificación para el comprador
y para cada productor involucrado. Las notificaciones se guardan en memoria
(prototipo); en producción se enviarían por correo, SMS o WhatsApp.
"""
import json
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import redis
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from .comun import configurar_logs, verificar_token_interno

log = configurar_logs("notificaciones")
REDIS_URL = os.getenv("REDIS_URL")
notificaciones: deque = deque(maxlen=500)
estado = {"conectado": False, "eventos_recibidos": 0, "ultimo_evento": None}

MENSAJES = {
    "pedido.pagado": ("Tu pedido #{id} fue pagado por ${total}. El productor ya fue notificado.",
                      "Tienes un nuevo pedido #{id} pagado. Prepáralo para despacho."),
    "pedido.cancelado": ("Tu pedido #{id} fue cancelado. Motivo: {motivo}", None),
    "pedido.despachado": ("Tu pedido #{id} va en camino.", None),
    "pedido.entregado": ("Tu pedido #{id} fue entregado. ¡Califica a tu productor!",
                         "El pedido #{id} fue entregado al comprador."),
}


def procesar_evento(evento: dict) -> list[dict]:
    tipo = evento.get("tipo", "")
    plantilla_comprador, plantilla_productor = MENSAJES.get(tipo, (None, None))
    total = f"{float(evento.get('total', 0)):,.0f}".replace(",", ".")  # formato colombiano: $12.000
    datos = {"id": evento.get("pedido_id", "")[:8], "total": total,
             "motivo": evento.get("motivo", "no especificado")}
    nuevas = []
    if plantilla_comprador and evento.get("comprador_id"):
        nuevas.append(_notificacion(evento, evento["comprador_id"], "comprador", plantilla_comprador.format(**datos)))
    if plantilla_productor:
        for productor_id in evento.get("productor_ids", []):
            nuevas.append(_notificacion(evento, productor_id, "productor", plantilla_productor.format(**datos)))
    for n in nuevas:
        notificaciones.appendleft(n)
        log.info(f"Notificación a {n['rol']} {n['usuario_id'][:8]}: {n['mensaje']}")
    estado["eventos_recibidos"] += 1
    estado["ultimo_evento"] = tipo
    return nuevas


def _notificacion(evento: dict, usuario_id: str, rol: str, mensaje: str) -> dict:
    return {"usuario_id": usuario_id, "rol": rol, "tipo": evento.get("tipo"), "pedido_id": evento.get("pedido_id"),
            "mensaje": mensaje, "fecha": datetime.now(UTC).isoformat()}


def escuchar() -> None:
    """Hilo suscriptor con reconexión automática y espera creciente."""
    espera = 1
    while True:
        try:
            cliente = redis.from_url(REDIS_URL, decode_responses=True, health_check_interval=30)
            pubsub = cliente.pubsub(ignore_subscribe_messages=True)
            pubsub.psubscribe("pedido.*")
            estado["conectado"] = True
            espera = 1
            log.info("Suscrito a los eventos pedido.*")
            for mensaje in pubsub.listen():
                if mensaje.get("type") == "pmessage":
                    try:
                        procesar_evento(json.loads(mensaje["data"]))
                    except Exception as e:
                        log.error(f"Evento inválido: {e}")
        except Exception as e:
            estado["conectado"] = False
            log.warning(f"Conexión con el broker perdida ({e}); reintento en {espera}s")
            time.sleep(espera)
            espera = min(espera * 2, 30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if REDIS_URL:
        threading.Thread(target=escuchar, daemon=True, name="suscriptor").start()
    else:
        log.warning("REDIS_URL no definido: el suscriptor no se inicia")
    yield


app = FastAPI(title="AgroConecta · notificaciones-service", version="1.0.0", lifespan=lifespan)


@app.get("/notificaciones", tags=["notificaciones"], dependencies=[Depends(verificar_token_interno)])
def listar(usuario_id: str | None = None, limite: int = 50):
    datos = [n for n in notificaciones if not usuario_id or n["usuario_id"] == usuario_id]
    return datos[:limite]


@app.get("/health", tags=["observabilidad"])
def health():
    ok = estado["conectado"] or not REDIS_URL
    cuerpo = {"servicio": "notificaciones-service", "estado": "ok" if ok else "degradado",
              "dependencias": {"broker_eventos": estado["conectado"]},
              "eventos_recibidos": estado["eventos_recibidos"], "ultimo_evento": estado["ultimo_evento"]}
    return JSONResponse(cuerpo)  # 200 aunque esté degradado: el servicio sigue vivo y reconectando
