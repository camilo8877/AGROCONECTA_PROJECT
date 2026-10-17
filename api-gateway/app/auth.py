"""Autenticación centralizada en el API Gateway: contraseñas con bcrypt y tokens JWT."""
import logging
import os
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .db import get_db
from .models import Usuario

log = logging.getLogger("gateway")
JWT_SECRET = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    JWT_SECRET = "solo-para-desarrollo-cambiar"
    log.warning("JWT_SECRET no definido: usando clave de desarrollo")
JWT_ALGORITMO = "HS256"
JWT_MINUTOS = int(os.getenv("JWT_MINUTOS", "60"))

bearer = HTTPBearer(auto_error=False)


def hash_clave(clave: str) -> str:
    return bcrypt.hashpw(clave.encode(), bcrypt.gensalt()).decode()


def verificar_clave(clave: str, hash_guardado: str) -> bool:
    return bcrypt.checkpw(clave.encode(), hash_guardado.encode())


def crear_token(usuario: Usuario) -> str:
    ahora = datetime.now(UTC)
    datos = {"sub": usuario.id, "rol": usuario.rol, "nombre": usuario.nombre,
             "iat": ahora, "exp": ahora + timedelta(minutes=JWT_MINUTOS)}
    return jwt.encode(datos, JWT_SECRET, algorithm=JWT_ALGORITMO)


def usuario_actual(cred: HTTPAuthorizationCredentials | None = Depends(bearer),
                   db: Session = Depends(get_db)) -> Usuario:
    if not cred:
        raise HTTPException(401, "Falta el token de acceso", headers={"WWW-Authenticate": "Bearer"})
    try:
        datos = jwt.decode(cred.credentials, JWT_SECRET, algorithms=[JWT_ALGORITMO])
    except JWTError as e:
        raise HTTPException(401, "Token inválido o expirado", headers={"WWW-Authenticate": "Bearer"}) from e
    usuario = db.get(Usuario, datos.get("sub"))
    if not usuario:
        raise HTTPException(401, "Usuario no existe")
    return usuario


def requiere_rol(*roles: str):
    def dependencia(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(403, f"Requiere rol: {', '.join(roles)}")
        return usuario
    return dependencia


def productor_verificado(usuario: Usuario = Depends(requiere_rol("productor", "admin"))) -> Usuario:
    if usuario.rol == "productor" and not usuario.verificado:
        raise HTTPException(403, "Tu cuenta de productor aún no ha sido validada por el administrador")
    return usuario
