"""Rutas públicas de la API. El gateway valida identidad y rol y enruta al servicio dueño."""
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import crear_token, hash_clave, productor_verificado, requiere_rol, usuario_actual, verificar_clave
from .db import get_db
from .models import Usuario
from .proxy import SERVICIOS, consultar_salud, reenviar

router = APIRouter(prefix="/api")


# ---------------- autenticación (CU-01) ----------------
class RegistroIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    email: EmailStr
    clave: str = Field(min_length=8, max_length=72)
    rol: Literal["productor", "comprador"]
    razon_social: str | None = None
    tipo_comercio: Literal["restaurante", "tienda", "fruver", "otro"] | None = None
    nit: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    clave: str


@router.post("/auth/registro", status_code=201, tags=["autenticación"])
def registro(body: RegistroIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalars(select(Usuario).where(Usuario.email == email)).first():
        raise HTTPException(409, "Ya existe una cuenta con ese correo")
    usuario = Usuario(nombre=body.nombre, email=email, hash_clave=hash_clave(body.clave), rol=body.rol,
                      razon_social=body.razon_social, tipo_comercio=body.tipo_comercio, nit=body.nit,
                      verificado=body.rol == "comprador")  # los productores requieren validación (CU-11)
    db.add(usuario)
    db.commit()
    return {"access_token": crear_token(usuario), "token_type": "bearer", "usuario": usuario.publico()}


@router.post("/auth/login", tags=["autenticación"])
def login(body: LoginIn, db: Session = Depends(get_db)):
    usuario = db.scalars(select(Usuario).where(Usuario.email == body.email.lower())).first()
    if not usuario or not verificar_clave(body.clave, usuario.hash_clave):
        raise HTTPException(401, "Correo o contraseña incorrectos")
    return {"access_token": crear_token(usuario), "token_type": "bearer", "usuario": usuario.publico()}


@router.get("/auth/yo", tags=["autenticación"])
def yo(usuario: Usuario = Depends(usuario_actual)):
    return usuario.publico()


# ---------------- administración de productores (CU-11) ----------------
@router.get("/admin/productores", tags=["administración"])
def listar_productores(db: Session = Depends(get_db), _: Usuario = Depends(requiere_rol("admin"))):
    return [u.publico() for u in db.scalars(select(Usuario).where(Usuario.rol == "productor"))]


@router.patch("/admin/productores/{usuario_id}/validar", tags=["administración"])
def validar_productor(usuario_id: str, db: Session = Depends(get_db), _: Usuario = Depends(requiere_rol("admin"))):
    u = db.get(Usuario, usuario_id)
    if not u or u.rol != "productor":
        raise HTTPException(404, "Productor no encontrado")
    u.verificado = True
    db.commit()
    return u.publico()


# ---------------- catálogo (CU-02, CU-03, CU-04) ----------------
@router.get("/categorias", tags=["catálogo"])
async def categorias(request: Request):
    return await reenviar("catalogo", "/categorias", request)


@router.post("/categorias", tags=["catálogo"])
async def crear_categoria(request: Request, usuario: Usuario = Depends(requiere_rol("admin"))):
    return await reenviar("catalogo", "/categorias", request, await request.body(), usuario)


@router.get("/productos", tags=["catálogo"])
async def productos(request: Request):
    return await reenviar("catalogo", "/productos", request)


@router.get("/productos/{producto_id}", tags=["catálogo"])
async def producto(producto_id: str, request: Request):
    return await reenviar("catalogo", f"/productos/{producto_id}", request)


@router.post("/productos", tags=["catálogo"])
async def crear_producto(request: Request, usuario: Usuario = Depends(productor_verificado)):
    return await reenviar("catalogo", "/productos", request, await request.body(), usuario)


@router.patch("/productos/{producto_id}", tags=["catálogo"])
async def actualizar_producto(producto_id: str, request: Request, usuario: Usuario = Depends(productor_verificado)):
    return await reenviar("catalogo", f"/productos/{producto_id}", request, await request.body(), usuario)


@router.patch("/productos/{producto_id}/inventario", tags=["catálogo"])
async def actualizar_inventario(producto_id: str, request: Request,
                                usuario: Usuario = Depends(productor_verificado)):
    return await reenviar("catalogo", f"/productos/{producto_id}/inventario", request, await request.body(), usuario)


@router.get("/fincas", tags=["catálogo"])
async def mis_fincas(request: Request, usuario: Usuario = Depends(requiere_rol("productor", "admin"))):
    params = {} if usuario.rol == "admin" else {"productor_id": usuario.id}
    return await reenviar("catalogo", "/fincas", request, usuario=usuario, params=params)


@router.post("/fincas", tags=["catálogo"])
async def crear_finca(request: Request, usuario: Usuario = Depends(productor_verificado)):
    return await reenviar("catalogo", "/fincas", request, await request.body(), usuario)


# ---------------- pedidos (CU-05 a CU-09) ----------------
@router.post("/pedidos", tags=["pedidos"])
async def crear_pedido(request: Request, usuario: Usuario = Depends(requiere_rol("comprador"))):
    return await reenviar("pedidos", "/pedidos", request, await request.body(), usuario)


@router.get("/pedidos", tags=["pedidos"])
async def listar_pedidos(request: Request, usuario: Usuario = Depends(usuario_actual)):
    return await reenviar("pedidos", "/pedidos", request, usuario=usuario)


@router.get("/pedidos/{pedido_id}", tags=["pedidos"])
async def obtener_pedido(pedido_id: str, request: Request, usuario: Usuario = Depends(usuario_actual)):
    return await reenviar("pedidos", f"/pedidos/{pedido_id}", request, usuario=usuario)


@router.patch("/pedidos/{pedido_id}/estado", tags=["pedidos"])
async def cambiar_estado(pedido_id: str, request: Request,
                         usuario: Usuario = Depends(requiere_rol("productor", "admin"))):
    return await reenviar("pedidos", f"/pedidos/{pedido_id}/estado", request, await request.body(), usuario)


@router.post("/pedidos/{pedido_id}/reprocesar", tags=["pedidos"])
async def reprocesar(pedido_id: str, request: Request, usuario: Usuario = Depends(requiere_rol("admin"))):
    return await reenviar("pedidos", f"/pedidos/{pedido_id}/reprocesar", request, usuario=usuario)


@router.get("/reportes/ventas", tags=["reportes"])
async def reporte_ventas(request: Request, usuario: Usuario = Depends(requiere_rol("admin"))):
    return await reenviar("pedidos", "/reportes/ventas", request, usuario=usuario)


# ---------------- notificaciones ----------------
@router.get("/notificaciones", tags=["notificaciones"])
async def notificaciones(request: Request, usuario: Usuario = Depends(usuario_actual)):
    params = {} if usuario.rol == "admin" else {"usuario_id": usuario.id}
    return await reenviar("notificaciones", "/notificaciones", request, usuario=usuario, params=params)


# ---------------- resiliencia y observabilidad (demostración) ----------------
@router.get("/pagos/estado-circuito", tags=["resiliencia"])
async def estado_circuito(request: Request):
    return await reenviar("pagos", "/pagos/estado-circuito", request)


@router.post("/admin/pasarela", tags=["resiliencia"])
async def configurar_pasarela(request: Request, usuario: Usuario = Depends(requiere_rol("admin"))):
    return await reenviar("pagos", "/admin/pasarela", request, await request.body(), usuario)


@router.post("/admin/circuito/reiniciar", tags=["resiliencia"])
async def reiniciar_circuito(request: Request, usuario: Usuario = Depends(requiere_rol("admin"))):
    return await reenviar("pagos", "/admin/circuito/reiniciar", request, usuario=usuario)


@router.get("/cache/estadisticas", tags=["observabilidad"])
async def estadisticas_cache(request: Request):
    return await reenviar("catalogo", "/cache/estadisticas", request)


@router.post("/cache/estadisticas/reiniciar", tags=["observabilidad"])
async def reiniciar_estadisticas_cache(request: Request, usuario: Usuario = Depends(requiere_rol("admin"))):
    return await reenviar("catalogo", "/cache/estadisticas/reiniciar", request, usuario=usuario)


@router.get("/estado", tags=["observabilidad"])
async def estado_sistema():
    """Health Endpoint Monitoring agregado de todos los servicios."""
    resultados = await asyncio.gather(*(consultar_salud(n) for n in SERVICIOS))
    servicios = dict(zip(SERVICIOS, resultados, strict=False))
    todos_ok = all(s.get("estado") == "ok" for s in servicios.values())
    return {"estado": "ok" if todos_ok else "degradado", "gateway": "ok", "servicios": servicios}
