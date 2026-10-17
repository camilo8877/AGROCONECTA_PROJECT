"""Utilidades transversales: logs estructurados y seguridad entre servicios."""
import json
import logging
import os
import sys

from fastapi import Header, HTTPException

INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")


class FormatoJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "nivel": record.levelname,
            "servicio": record.name,
            "mensaje": record.getMessage(),
        }
        if record.exc_info:
            datos["error"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False)


def configurar_logs(nombre: str) -> logging.Logger:
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(FormatoJSON())
    logger = logging.getLogger(nombre)
    logger.handlers = [manejador]
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    logger.propagate = False
    return logger


def verificar_token_interno(x_internal_token: str | None = Header(default=None)) -> None:
    """Solo el API Gateway y los servicios internos conocen INTERNAL_TOKEN."""
    if INTERNAL_TOKEN and x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Token interno inválido")


def usuario_desde_headers(
    x_user_id: str | None = Header(default=None),
    x_user_rol: str | None = Header(default=None),
) -> dict:
    """El gateway valida el JWT y propaga la identidad en cabeceras."""
    return {"id": x_user_id, "rol": x_user_rol}
