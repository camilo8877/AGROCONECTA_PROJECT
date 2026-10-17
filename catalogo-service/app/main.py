"""catalogo-service: productos, fincas e inventario de AgroConecta."""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from . import datos_iniciales
from .cache import cache
from .comun import configurar_logs, verificar_token_interno
from .db import SessionLocal, db_ok, init_db
from .routers import inventario, productos

log = configurar_logs("catalogo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        datos_iniciales.cargar(db)
    log.info(f"catalogo-service iniciado (caché: {cache.backend})")
    yield


app = FastAPI(title="AgroConecta · catalogo-service", version="1.0.0", lifespan=lifespan)
app.include_router(productos.router, dependencies=[Depends(verificar_token_interno)])
app.include_router(inventario.router, dependencies=[Depends(verificar_token_interno)])


@app.get("/health", tags=["observabilidad"])
def health():
    """Health Endpoint Monitoring: verifica base de datos y caché."""
    base_datos, redis_ok = db_ok(), cache.ping()
    estado = "ok" if base_datos and redis_ok else "degradado"
    cuerpo = {"servicio": "catalogo-service", "estado": estado,
              "dependencias": {"base_datos": base_datos, "cache": redis_ok, "cache_backend": cache.backend}}
    return JSONResponse(cuerpo, status_code=200 if base_datos else 503)
