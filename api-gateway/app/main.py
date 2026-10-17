"""api-gateway: punto de entrada único de AgroConecta (patrón API Gateway).

Responsabilidades transversales: autenticación JWT, autorización por rol,
limitación de peticiones, CORS, enrutamiento y verificación de salud.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from .auth import hash_clave
from .comun import configurar_logs
from .db import SessionLocal, db_ok, init_db
from .models import Usuario
from .rate_limit import LimitadorPeticiones
from .routes import router

log = configurar_logs("gateway")

# Cuentas de demostración (sus id coinciden con los datos iniciales del catálogo)
USUARIOS_DEMO = [
    ("00000000-0000-0000-0000-000000000000", "Administrador AgroConecta", "admin@agroconecta.co", "Admin123*",
     "admin", None, None),
    ("11111111-1111-1111-1111-111111111111", "Finca La Esperanza", "productor@agroconecta.co", "Productor123*",
     "productor", "Asociación de Productores de Marinilla", None),
    ("22222222-2222-2222-2222-222222222222", "Restaurante El Fogón", "comprador@agroconecta.co", "Comprador123*",
     "comprador", "El Fogón Paisa S.A.S.", "restaurante"),
]


def crear_usuarios_demo() -> None:
    with SessionLocal() as db:
        for uid, nombre, email, clave, rol, razon, tipo in USUARIOS_DEMO:
            if not db.scalars(select(Usuario).where(Usuario.email == email)).first():
                db.add(Usuario(id=uid, nombre=nombre, email=email, hash_clave=hash_clave(clave), rol=rol,
                               razon_social=razon, tipo_comercio=tipo, verificado=True))
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if os.getenv("CREAR_USUARIOS_DEMO", "true").lower() == "true":
        crear_usuarios_demo()
    log.info("api-gateway iniciado")
    yield


app = FastAPI(
    title="AgroConecta · API Gateway",
    version="1.0.0",
    description="Marketplace de productores agrícolas a comercios. Arquitectura de microservicios en Render.",
    lifespan=lifespan,
)
origenes = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(LimitadorPeticiones)
app.add_middleware(CORSMiddleware, allow_origins=origenes, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/docs")


@app.get("/health", tags=["observabilidad"])
def health():
    base_datos = db_ok()
    return JSONResponse({"servicio": "api-gateway", "estado": "ok" if base_datos else "degradado",
                         "dependencias": {"base_datos": base_datos}}, status_code=200 if base_datos else 503)
