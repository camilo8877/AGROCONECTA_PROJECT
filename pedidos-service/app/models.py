import enum
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _ahora() -> datetime:
    return datetime.now(UTC)


class EstadoPedido(enum.StrEnum):
    PENDIENTE = "PENDIENTE"
    RESERVADO = "RESERVADO"
    PAGADO = "PAGADO"
    DESPACHADO = "DESPACHADO"
    ENTREGADO = "ENTREGADO"
    CANCELADO = "CANCELADO"


class Pedido(Base):
    __tablename__ = "pedidos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    comprador_id: Mapped[str] = mapped_column(String(36), index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
    estado: Mapped[str] = mapped_column(String(12), default=EstadoPedido.PENDIENTE.value)
    total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    motivo_cancelacion: Mapped[str | None] = mapped_column(String(300), nullable=True)

    detalles: Mapped[list["DetallePedido"]] = relationship(back_populates="pedido", lazy="selectin",
                                                           cascade="all, delete-orphan")
    saga: Mapped["SagaPedido"] = relationship(back_populates="pedido", uselist=False, lazy="selectin")

    def productor_ids(self) -> list[str]:
        return sorted({d.productor_id for d in self.detalles})

    def resumen(self, **extra) -> dict:
        return {"pedido_id": self.id, "comprador_id": self.comprador_id, "productor_ids": self.productor_ids(),
                "total": float(self.total), "estado": self.estado, **extra}

    def a_dict(self) -> dict:
        return {
            "id": self.id,
            "comprador_id": self.comprador_id,
            "fecha": self.fecha.isoformat() if self.fecha else None,
            "estado": self.estado,
            "total": float(self.total),
            "motivo_cancelacion": self.motivo_cancelacion,
            "items": [d.a_dict() for d in self.detalles],
            "saga": self.saga.a_dict() if self.saga else None,
        }


class DetallePedido(Base):
    __tablename__ = "detalles_pedido"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pedido_id: Mapped[str] = mapped_column(ForeignKey("pedidos.id"), index=True)
    # Referencias por identificador a datos de otro servicio (sin llave foránea): Database per Service
    producto_id: Mapped[str] = mapped_column(String(36))
    productor_id: Mapped[str] = mapped_column(String(36), index=True)
    nombre_producto: Mapped[str] = mapped_column(String(120))
    unidad: Mapped[str] = mapped_column(String(20))
    cantidad: Mapped[int] = mapped_column(Integer)
    precio_unitario: Mapped[float] = mapped_column(Numeric(12, 2))

    pedido: Mapped[Pedido] = relationship(back_populates="detalles")

    def subtotal(self) -> float:
        return float(self.precio_unitario) * self.cantidad

    def a_dict(self) -> dict:
        return {"producto_id": self.producto_id, "productor_id": self.productor_id, "nombre": self.nombre_producto,
                "unidad": self.unidad, "cantidad": self.cantidad, "precio_unitario": float(self.precio_unitario),
                "subtotal": self.subtotal()}


class SagaPedido(Base):
    """Estado persistente de la Saga: permite saber en qué paso quedó y compensar."""
    __tablename__ = "saga_pedido"
    pedido_id: Mapped[str] = mapped_column(ForeignKey("pedidos.id"), primary_key=True)
    paso: Mapped[str] = mapped_column(String(30), default="INICIADA")
    historial: Mapped[str] = mapped_column(Text, default="[]")
    actualizado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, onupdate=_ahora)

    pedido: Mapped[Pedido] = relationship(back_populates="saga")

    def registrar(self, paso: str, detalle: str = "") -> None:
        historial = json.loads(self.historial or "[]")
        historial.append({"paso": paso, "detalle": detalle, "fecha": _ahora().isoformat()})
        self.historial = json.dumps(historial, ensure_ascii=False)
        self.paso = paso

    def a_dict(self) -> dict:
        return {"paso": self.paso, "historial": json.loads(self.historial or "[]")}
