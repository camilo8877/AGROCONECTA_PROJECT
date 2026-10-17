from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..cache import cache
from ..comun import usuario_desde_headers
from ..db import get_db
from ..repositories.productos import RepositorioCatalogo
from ..schemas import CategoriaIn, FincaIn, InventarioUpdate, ProductoIn, ProductoUpdate
from ..services import catalogo

router = APIRouter()


def _requiere_productor(usuario: dict) -> None:
    if usuario.get("rol") not in ("productor", "admin") or not usuario.get("id"):
        raise HTTPException(403, "Operación permitida solo para productores")


@router.get("/categorias", tags=["categorías"])
def listar_categorias(db: Session = Depends(get_db)):
    return [{"id": c.id, "nombre": c.nombre} for c in RepositorioCatalogo(db).categorias()]


@router.post("/categorias", status_code=201, tags=["categorías"])
def crear_categoria(body: CategoriaIn, db: Session = Depends(get_db), usuario: dict = Depends(usuario_desde_headers)):
    if usuario.get("rol") != "admin":
        raise HTTPException(403, "Solo el administrador crea categorías")
    c = RepositorioCatalogo(db).crear_categoria(body.nombre)
    return {"id": c.id, "nombre": c.nombre}


@router.get("/fincas", tags=["fincas"])
def listar_fincas(productor_id: str | None = None, db: Session = Depends(get_db)):
    return [
        {"id": f.id, "nombre": f.nombre, "municipio": f.municipio, "productor_id": f.productor_id}
        for f in RepositorioCatalogo(db).fincas(productor_id)
    ]


@router.post("/fincas", status_code=201, tags=["fincas"])
def crear_finca(body: FincaIn, db: Session = Depends(get_db), usuario: dict = Depends(usuario_desde_headers)):
    _requiere_productor(usuario)
    f = RepositorioCatalogo(db).crear_finca(body.nombre, body.municipio, usuario["id"])
    return {"id": f.id, "nombre": f.nombre, "municipio": f.municipio, "productor_id": f.productor_id}


@router.get("/productos", tags=["productos"])
def listar_productos(
    categoria_id: int | None = None,
    municipio: str | None = None,
    productor_id: str | None = None,
    solo_disponibles: bool = False,
    db: Session = Depends(get_db),
):
    return catalogo.listar_productos(db, categoria_id, municipio, productor_id, solo_disponibles)


@router.get("/productos/{producto_id}", tags=["productos"])
def obtener_producto(producto_id: str, db: Session = Depends(get_db)):
    return catalogo.obtener_producto(db, producto_id)


@router.post("/productos", status_code=201, tags=["productos"])
def crear_producto(body: ProductoIn, db: Session = Depends(get_db), usuario: dict = Depends(usuario_desde_headers)):
    _requiere_productor(usuario)
    return catalogo.crear_producto(db, body.model_dump(), usuario["id"])


@router.patch("/productos/{producto_id}", tags=["productos"])
def actualizar_producto(producto_id: str, body: ProductoUpdate, db: Session = Depends(get_db),
                        usuario: dict = Depends(usuario_desde_headers)):
    _requiere_productor(usuario)
    return catalogo.actualizar_producto(db, producto_id, body.model_dump(), usuario)


@router.patch("/productos/{producto_id}/inventario", tags=["productos"])
def actualizar_inventario(producto_id: str, body: InventarioUpdate, db: Session = Depends(get_db),
                          usuario: dict = Depends(usuario_desde_headers)):
    _requiere_productor(usuario)
    return catalogo.actualizar_inventario(db, producto_id, body.disponible, usuario)


@router.get("/cache/estadisticas", tags=["observabilidad"])
def estadisticas_cache():
    return cache.estadisticas()


@router.post("/cache/estadisticas/reiniciar", tags=["observabilidad"])
def reiniciar_estadisticas_cache():
    cache.reiniciar_estadisticas()
    return cache.estadisticas()
