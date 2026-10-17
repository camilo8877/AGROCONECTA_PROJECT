"""Patrón Adapter: la lógica de cobro depende de esta interfaz, no de un proveedor concreto.
Para usar un proveedor real basta con crear otro adaptador (p. ej. PasarelaWompi)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class PasarelaError(Exception):
    """Falla técnica de la pasarela (timeout, 5xx). Es transitoria: se reintenta."""


@dataclass
class ResultadoPasarela:
    aprobado: bool
    referencia: str
    motivo: str | None = None


class PasarelaPagos(ABC):
    @abstractmethod
    def autorizar(self, pedido_id: str, monto: float) -> ResultadoPasarela: ...
