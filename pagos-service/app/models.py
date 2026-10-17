import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Pago(Base):
    __tablename__ = "pagos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pedido_id: Mapped[str] = mapped_column(String(36), index=True)
    monto: Mapped[float] = mapped_column(Numeric(12, 2))
    estado: Mapped[str] = mapped_column(String(12))  # APROBADO | RECHAZADO | FALLIDO
    referencia_pasarela: Mapped[str | None] = mapped_column(String(40), nullable=True)
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    motivo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    def a_dict(self) -> dict:
        return {
            "id": self.id, "pedido_id": self.pedido_id, "monto": float(self.monto), "estado": self.estado,
            "referencia_pasarela": self.referencia_pasarela, "intentos": self.intentos,
            "motivo": self.motivo, "creado": self.creado.isoformat() if self.creado else None,
        }
