"""Endpoints internos usados por el orquestador de la Saga (servicio de pedidos)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import PedidoRef, ReservaIn
from ..services import catalogo

router = APIRouter(prefix="/inventario", tags=["inventario (Saga)"])


@router.post("/reservar")
def reservar(body: ReservaIn, db: Session = Depends(get_db)):
    return catalogo.reservar(db, body.pedido_id, [i.model_dump() for i in body.items])


@router.post("/liberar")
def liberar(body: PedidoRef, db: Session = Depends(get_db)):
    return catalogo.liberar(db, body.pedido_id)


@router.post("/confirmar")
def confirmar(body: PedidoRef, db: Session = Depends(get_db)):
    return catalogo.confirmar(db, body.pedido_id)
