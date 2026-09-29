from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import COOKIE_SESION, crear_sesion, sesion_actual, usuario_actual
from app.core.config import settings
from app.core.database import get_db
from app.core.seguridad import hashear_password, verificar_password
from app.models import RolUsuario, Sesion, Usuario

router = APIRouter(prefix="/auth", tags=["auth"])

# Para que un usuario inexistente tarde lo mismo que una contraseña incorrecta
# y no se pueda averiguar qué usuarios existen midiendo el tiempo.
_HASH_FALSO = hashear_password("no-es-una-contraseña")


class LoginIn(BaseModel):
    negocio_id: int | None = None  # sin él, el negocio predeterminado de la configuración
    usuario: str
    password: str


class UsuarioOut(BaseModel):
    id: int
    negocio_id: int
    nombre_usuario: str
    nombre_completo: str
    rol: RolUsuario


class LoginOut(BaseModel):
    usuario: UsuarioOut
    # Solo para clientes que no usan cookies (scripts, /docs). El navegador usa la cookie.
    token: str
    expira: datetime


def _usuario_out(u: Usuario) -> UsuarioOut:
    return UsuarioOut(
        id=u.id, negocio_id=u.negocio_id, nombre_usuario=u.nombre_usuario,
        nombre_completo=u.nombre_completo, rol=u.rol,
    )


@router.post("/login", response_model=LoginOut)
def login(datos: LoginIn, response: Response, db: Session = Depends(get_db)):
    negocio_id = datos.negocio_id or settings.negocio_predeterminado
    usuario = db.scalar(
        select(Usuario).where(Usuario.negocio_id == negocio_id, Usuario.nombre_usuario == datos.usuario.strip())
    )
    password_ok = verificar_password(datos.password, usuario.password_hash if usuario else _HASH_FALSO)
    if usuario is None or not password_ok or not usuario.activo:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    token, sesion = crear_sesion(db, usuario)
    db.commit()
    response.set_cookie(
        COOKIE_SESION, token,
        max_age=settings.horas_sesion * 3600,
        httponly=True, samesite="strict", secure=settings.cookie_segura,
    )
    return LoginOut(usuario=_usuario_out(usuario), token=token, expira=sesion.expira)


@router.post("/logout", status_code=204)
def logout(response: Response, sesion: Sesion = Depends(sesion_actual), db: Session = Depends(get_db)):
    sesion.cerrada = datetime.now(timezone.utc)
    db.commit()
    response.delete_cookie(COOKIE_SESION)


@router.get("/yo", response_model=UsuarioOut)
def yo(usuario: Usuario = Depends(usuario_actual)):
    return _usuario_out(usuario)
