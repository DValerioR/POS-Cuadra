"""Sesiones y permisos. Los endpoints piden al usuario con
`Depends(usuario_actual)` o, si la operación es solo para ciertos roles,
`Depends(requiere_rol(RolUsuario.ADMIN, ...))`. El negocio sale del usuario,
así que nadie puede leer ni tocar datos de otro negocio.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models import RolUsuario, Sesion, Usuario

COOKIE_SESION = "pos_sesion"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def crear_sesion(db: Session, usuario: Usuario) -> tuple[str, Sesion]:
    """Regresa el token (va a la cookie; no se guarda) y la sesión creada."""
    token = secrets.token_urlsafe(32)
    sesion = Sesion(
        usuario_id=usuario.id,
        token_hash=_hash(token),
        expira=datetime.now(timezone.utc) + timedelta(hours=settings.horas_sesion),
    )
    db.add(sesion)
    return token, sesion


# Declararlo así hace que /docs muestre el botón "Authorize". auto_error=False
# porque el navegador normalmente manda la cookie, no el encabezado.
_bearer = HTTPBearer(auto_error=False, description="Token que regresa POST /auth/login")


def sesion_actual(
    request: Request,
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Sesion:
    # El encabezado (scripts, /docs) tiene prioridad sobre la cookie del navegador.
    token = credenciales.credentials if credenciales else request.cookies.get(COOKIE_SESION)
    sesion = db.scalar(select(Sesion).where(Sesion.token_hash == _hash(token))) if token else None
    if sesion is None or sesion.cerrada is not None or sesion.expira <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Inicia sesión")
    return sesion


def usuario_actual(sesion: Sesion = Depends(sesion_actual), db: Session = Depends(get_db)) -> Usuario:
    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        raise HTTPException(status_code=401, detail="Inicia sesión")
    return usuario


def requiere_rol(*roles: RolUsuario):
    def dependencia(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(status_code=403, detail=f"El rol {usuario.rol.value} no puede hacer esta operación")
        return usuario

    return dependencia


solo_admin = requiere_rol(RolUsuario.ADMIN)
