"""Conexión a base de datos.

Patrón Database per Service: cada servicio usa su propio esquema de PostgreSQL
(variable DB_SCHEMA) y solo accede a sus tablas. Sin DATABASE_URL se usa SQLite
local, útil para pruebas y desarrollo.
"""
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

SERVICIO = "catalogo"


def _normalizar_url(url: str) -> str:
    # Render entrega "postgres://..." o "postgresql://..."; SQLAlchemy necesita el driver.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _normalizar_url(os.getenv("DATABASE_URL", f"sqlite:///./{SERVICIO}.db"))
DB_SCHEMA = os.getenv("DB_SCHEMA", SERVICIO)
ES_POSTGRES = DATABASE_URL.startswith("postgresql")

if ES_POSTGRES:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"options": f"-csearch_path={DB_SCHEMA}"},
    )
else:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    if ES_POSTGRES:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}"'))
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_ok() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
