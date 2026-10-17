import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _ahora() -> datetime:
    return datetime.now(UTC)


class Categoria(Base):
    __tablename__ = "categorias"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True)


class Finca(Base):
    __tablename__ = "fincas"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    nombre: Mapped[str] = mapped_column(String(120))
    municipio: Mapped[str] = mapped_column(String(80), index=True)
    productor_id: Mapped[str] = mapped_column(String(36), index=True)


class Producto(Base):
    __tablename__ = "productos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    nombre: Mapped[str] = mapped_column(String(120))
    unidad: Mapped[str] = mapped_column(String(20))
    precio: Mapped[float] = mapped_column(Numeric(12, 2))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"))
    finca_id: Mapped[str] = mapped_column(ForeignKey("fincas.id"))
    productor_id: Mapped[str] = mapped_column(String(36), index=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)

    categoria: Mapped[Categoria] = relationship(lazy="joined")
    finca: Mapped[Finca] = relationship(lazy="joined")
    inventario: Mapped["Inventario"] = relationship(back_populates="producto", uselist=False, lazy="joined")


class Inventario(Base):
    __tablename__ = "inventario"
    producto_id: Mapped[str] = mapped_column(ForeignKey("productos.id"), primary_key=True)
    disponible: Mapped[int] = mapped_column(Integer, default=0)
    reservado: Mapped[int] = mapped_column(Integer, default=0)

    producto: Mapped[Producto] = relationship(back_populates="inventario")


class Reserva(Base):
    """Registro de cada reserva hecha por la Saga; permite compensarla (liberar)."""
    __tablename__ = "reservas"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    pedido_id: Mapped[str] = mapped_column(String(36), index=True)
    producto_id: Mapped[str] = mapped_column(ForeignKey("productos.id"))
    cantidad: Mapped[int] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(12), default="RESERVADA")  # RESERVADA | LIBERADA | CONFIRMADA
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
