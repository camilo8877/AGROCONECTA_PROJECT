"""Lógica de negocio del catálogo.

Cache-Aside: los datos descriptivos del producto (nombre, precio, finca) se leen
primero de la caché; el inventario disponible se consulta siempre en la base de
datos para no mostrar cantidades desactualizadas.
"""
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..cache import cache
from ..models import Producto, Reserva
from ..repositories.productos import RepositorioCatalogo

log = logging.getLogger("catalogo")


def clave_producto(producto_id: str) -> str:
    return f"producto:{producto_id}"


def _a_dict(p: Producto) -> dict:
    return {
        "id": p.id,
        "nombre": p.nombre,
        "unidad": p.unidad,
        "precio": float(p.precio),
        "activo": p.activo,
        "categoria_id": p.categoria_id,
        "categoria": p.categoria.nombre if p.categoria else None,
        "finca_id": p.finca_id,
        "finca": p.finca.nombre if p.finca else None,
        "municipio": p.finca.municipio if p.finca else None,
        "productor_id": p.productor_id,
    }


def _con_inventario(datos: list[dict], repo: RepositorioCatalogo) -> list[dict]:
    inventarios = repo.inventarios([d["id"] for d in datos])
    for d in datos:
        inv = inventarios.get(d["id"])
        d["disponible"] = inv.disponible if inv else 0
    return datos


# ---------- lecturas (Cache-Aside) ----------
def obtener_producto(db: Session, producto_id: str) -> dict:
    repo = RepositorioCatalogo(db)
    clave = clave_producto(producto_id)
    datos = cache.get(clave)                      # 1. buscar en caché
    if datos is None:
        producto = repo.por_id(producto_id)       # 2. fallo de caché: ir a la BD
        if not producto:
            raise HTTPException(404, "Producto no encontrado")
        datos = _a_dict(producto)
        cache.set(clave, datos)                   # 3. guardar con TTL
    return _con_inventario([datos], repo)[0]


def listar_productos(db: Session, categoria_id=None, municipio=None, productor_id=None,
                     solo_disponibles=False) -> list[dict]:
    repo = RepositorioCatalogo(db)
    version = cache.version_listados()
    clave = f"productos:lista:v{version}:{categoria_id}:{(municipio or '').lower()}:{productor_id}"
    datos = cache.get(clave)
    if datos is None:
        datos = [_a_dict(p) for p in repo.listar(categoria_id, municipio, productor_id)]
        cache.set(clave, datos)
    datos = _con_inventario(datos, repo)
    if solo_disponibles:
        datos = [d for d in datos if d["disponible"] > 0]
    return datos


def invalidar(producto_id: str | None = None) -> None:
    if producto_id:
        cache.delete(clave_producto(producto_id))
    cache.incr("productos:version")


# ---------- escrituras ----------
def crear_producto(db: Session, datos: dict, productor_id: str) -> dict:
    repo = RepositorioCatalogo(db)
    finca = repo.finca(datos["finca_id"])
    if not finca or finca.productor_id != productor_id:
        raise HTTPException(403, "La finca no existe o no pertenece al productor")
    disponible = datos.pop("disponible_inicial", 0)
    producto = repo.crear({**datos, "productor_id": productor_id}, disponible)
    invalidar()
    log.info(f"Producto creado {producto.id} por productor {productor_id}")
    return obtener_producto(db, producto.id)


def _producto_propio(repo: RepositorioCatalogo, producto_id: str, usuario: dict) -> Producto:
    producto = repo.por_id(producto_id)
    if not producto:
        raise HTTPException(404, "Producto no encontrado")
    if usuario.get("rol") != "admin" and producto.productor_id != usuario.get("id"):
        raise HTTPException(403, "Solo el productor dueño puede modificar este producto")
    return producto


def actualizar_producto(db: Session, producto_id: str, cambios: dict, usuario: dict) -> dict:
    repo = RepositorioCatalogo(db)
    producto = _producto_propio(repo, producto_id, usuario)
    repo.actualizar(producto, {k: v for k, v in cambios.items() if v is not None})
    invalidar(producto_id)                        # invalidación de la caché
    return obtener_producto(db, producto_id)


def actualizar_inventario(db: Session, producto_id: str, disponible: int, usuario: dict) -> dict:
    repo = RepositorioCatalogo(db)
    _producto_propio(repo, producto_id, usuario)
    repo.fijar_disponible(producto_id, disponible)
    return obtener_producto(db, producto_id)


# ---------- reservas: pasos y compensaciones de la Saga ----------
def reservar(db: Session, pedido_id: str, items: list[dict]) -> dict:
    """Reserva todos los ítems o ninguno (transacción local ACID)."""
    repo = RepositorioCatalogo(db)
    if repo.reservas_de(pedido_id):               # idempotencia ante reintentos
        return {"pedido_id": pedido_id, "estado": "RESERVADO", "idempotente": True}
    try:
        for item in items:
            if not repo.descontar_si_hay(item["producto_id"], item["cantidad"]):
                db.rollback()
                producto = repo.por_id(item["producto_id"])
                nombre = producto.nombre if producto else item["producto_id"]
                raise HTTPException(409, f"Sin inventario suficiente de {nombre}")
            db.add(Reserva(pedido_id=pedido_id, producto_id=item["producto_id"], cantidad=item["cantidad"]))
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise
    log.info(f"Inventario reservado para pedido {pedido_id}")
    return {"pedido_id": pedido_id, "estado": "RESERVADO"}


def liberar(db: Session, pedido_id: str) -> dict:
    """Transacción compensatoria: devuelve al inventario lo reservado."""
    repo = RepositorioCatalogo(db)
    reservas = repo.reservas_de(pedido_id, "RESERVADA")
    for r in reservas:
        repo.devolver(r.producto_id, r.cantidad)
        r.estado = "LIBERADA"
    db.commit()
    log.info(f"Compensación: {len(reservas)} reservas liberadas del pedido {pedido_id}")
    return {"pedido_id": pedido_id, "estado": "LIBERADO", "reservas_liberadas": len(reservas)}


def confirmar(db: Session, pedido_id: str) -> dict:
    """Al aprobarse el pago, la reserva se vuelve venta definitiva."""
    repo = RepositorioCatalogo(db)
    reservas = repo.reservas_de(pedido_id, "RESERVADA")
    for r in reservas:
        repo.consumir_reservado(r.producto_id, r.cantidad)
        r.estado = "CONFIRMADA"
    db.commit()
    return {"pedido_id": pedido_id, "estado": "CONFIRMADO", "reservas_confirmadas": len(reservas)}
