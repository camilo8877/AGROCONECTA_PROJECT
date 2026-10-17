"""Pasarela simulada para la demostración.

- tasa_fallo: probabilidad (0 a 1) de una falla técnica. Se ajusta en caliente con
  POST /admin/pasarela para provocar la apertura del circuito durante la demo.
- Montos superiores a LIMITE_MONTO se rechazan por "fondos insuficientes"
  (rechazo de negocio, no se reintenta).
"""
import os
import random
import time
import uuid

from .base import PasarelaError, PasarelaPagos, ResultadoPasarela


class PasarelaSimulada(PasarelaPagos):
    def __init__(self):
        self.tasa_fallo = float(os.getenv("PASARELA_TASA_FALLO", "0"))
        self.latencia_ms = int(os.getenv("PASARELA_LATENCIA_MS", "150"))
        self.limite_monto = float(os.getenv("PASARELA_LIMITE_MONTO", "5000000"))

    def autorizar(self, pedido_id: str, monto: float) -> ResultadoPasarela:
        time.sleep(self.latencia_ms / 1000)
        if random.random() < self.tasa_fallo:
            raise PasarelaError("La pasarela no respondió (timeout simulado)")
        referencia = f"SIM-{uuid.uuid4().hex[:10].upper()}"
        if monto > self.limite_monto:
            return ResultadoPasarela(False, referencia, "Fondos insuficientes")
        return ResultadoPasarela(True, referencia)

    def configuracion(self) -> dict:
        return {"tasa_fallo": self.tasa_fallo, "latencia_ms": self.latencia_ms, "limite_monto": self.limite_monto}
