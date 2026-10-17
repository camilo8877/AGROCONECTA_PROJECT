import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    nombre: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    hash_clave: Mapped[str] = mapped_column(String(100))
    rol: Mapped[str] = mapped_column(String(12))  # productor | comprador | admin
    razon_social: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tipo_comercio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verificado: Mapped[bool] = mapped_column(Boolean, default=False)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    def publico(self) -> dict:
        return {"id": self.id, "nombre": self.nombre, "email": self.email, "rol": self.rol,
                "razon_social": self.razon_social, "tipo_comercio": self.tipo_comercio, "nit": self.nit,
                "verificado": self.verificado}
