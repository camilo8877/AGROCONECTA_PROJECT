"""pagos-service: cobro de pedidos protegido con Retry + Circuit Breaker."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from tenacity import RetryError, Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .comun import configurar_logs, verificar_token_interno
from .db import db_ok, get_db, init_db
from .models import Pago
from .pasarelas.base import PasarelaError
from .pasarelas.simulada import PasarelaSimulada
from .resiliencia.circuit_breaker import CircuitBreaker, CircuitoAbierto

log = configurar_logs("pagos")

pasarela = PasarelaSimulada()
breaker = CircuitBreaker(
    "pasarela-pagos",
    umbral_fallos=int(os.getenv("CB_UMBRAL_FALLOS", "3")),
    tiempo_recuperacion=float(os.getenv("CB_TIEMPO_RECUPERACION", "30")),
)
REINTENTOS = int(os.getenv("PASARELA_REINTENTOS", "3"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("pagos-service iniciado")
    yield


app = FastAPI(title="AgroConecta · pagos-service", version="1.0.0", lifespan=lifespan)
router = APIRouter(dependencies=[Depends(verificar_token_interno)])


class PagoIn(BaseModel):
    pedido_id: str
    monto: float = Field(gt=0)


class PasarelaConfig(BaseModel):
    tasa_fallo: float = Field(ge=0, le=1)


def cobrar_con_reintentos(pedido_id: str, monto: float, contador: dict):
    """Patrón Retry: reintentos con espera exponencial solo ante fallas transitorias."""
    for intento in Retrying(
        stop=stop_after_attempt(REINTENTOS),
        wait=wait_exponential(multiplier=0.2, max=1.0),
        retry=retry_if_exception_type(PasarelaError),
        reraise=True,
    ):
        with intento:
            contador["intentos"] += 1
            return pasarela.autorizar(pedido_id, monto)


@router.post("/pagos", tags=["pagos"])
def cobrar(body: PagoIn, db: Session = Depends(get_db)):
    existente = db.scalars(select(Pago).where(Pago.pedido_id == body.pedido_id, Pago.estado == "APROBADO")).first()
    if existente:  # idempotencia: nunca cobrar dos veces el mismo pedido
        return existente.a_dict()

    contador = {"intentos": 0}
    pago = Pago(pedido_id=body.pedido_id, monto=body.monto)
    try:
        resultado = breaker.llamar(cobrar_con_reintentos, body.pedido_id, body.monto, contador)
        pago.estado = "APROBADO" if resultado.aprobado else "RECHAZADO"
        pago.referencia_pasarela = resultado.referencia
        pago.motivo = resultado.motivo
    except CircuitoAbierto as e:
        pago.estado, pago.motivo = "FALLIDO", str(e)
    except (PasarelaError, RetryError) as e:
        pago.estado, pago.motivo = "FALLIDO", f"Pasarela no disponible tras {contador['intentos']} intentos: {e}"
    pago.intentos = contador["intentos"]
    db.add(pago)
    db.commit()
    log.info(f"Pago {pago.estado} pedido={body.pedido_id} intentos={pago.intentos}")

    if pago.estado == "FALLIDO":
        return JSONResponse({**pago.a_dict(), "circuito": breaker.estado_actual()["estado"]}, status_code=503)
    return pago.a_dict()


@router.get("/pagos/estado-circuito", tags=["resiliencia"])
def estado_circuito():
    return {**breaker.estado_actual(), "pasarela": pasarela.configuracion()}


@router.get("/pagos/pedido/{pedido_id}", tags=["pagos"])
def pagos_de_pedido(pedido_id: str, db: Session = Depends(get_db)):
    return [p.a_dict() for p in db.scalars(select(Pago).where(Pago.pedido_id == pedido_id).order_by(Pago.creado))]


@router.post("/admin/pasarela", tags=["demo"])
def configurar_pasarela(body: PasarelaConfig):
    """Ajusta la tasa de fallo de la pasarela simulada (demostración en vivo)."""
    pasarela.tasa_fallo = body.tasa_fallo
    logging.getLogger("pagos").info(f"Tasa de fallo de la pasarela ajustada a {body.tasa_fallo}")
    return estado_circuito()


@router.post("/admin/circuito/reiniciar", tags=["demo"])
def reiniciar_circuito():
    breaker.reiniciar()
    return estado_circuito()


app.include_router(router)


@app.get("/health", tags=["observabilidad"])
def health():
    base_datos = db_ok()
    if not base_datos:
        raise HTTPException(503, "Base de datos no disponible")
    return {"servicio": "pagos-service", "estado": "ok",
            "dependencias": {"base_datos": base_datos, "pasarela_circuito": breaker.estado_actual()["estado"]}}
