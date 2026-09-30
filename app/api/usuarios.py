from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Usuario
from app.services import usuarios
from app.services.errores import ERRORES_NEGOCIO, a_http

# La pantalla es /usuarios; el API va en /cuentas para no chocar con ella.
router = APIRouter(prefix="/cuentas", tags=["usuarios"])


class UsuarioNuevoIn(BaseModel):
    nombre_usuario: str = Field(max_length=40)
    nombre_completo: str = Field(max_length=80)
    rol: str
    password: str = Field(max_length=200)


class UsuarioCambioIn(BaseModel):
    nombre_completo: str | None = Field(default=None, max_length=80)
    rol: str | None = None
    activo: bool | None = None


class PasswordIn(BaseModel):
    password: str = Field(max_length=200)


class MiPasswordIn(BaseModel):
    actual: str = Field(max_length=200)
    nueva: str = Field(max_length=200)


def _hacer(db: Session, admin: Usuario, accion) -> list[dict]:
    """Corre la acción, hace commit y regresa la lista actualizada."""
    try:
        accion()
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return usuarios.listar(db, admin)


@router.get("")
def listar(admin: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    return usuarios.listar(db, admin)


@router.post("", status_code=201)
def crear(datos: UsuarioNuevoIn, admin: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    return _hacer(db, admin, lambda: usuarios.crear(
        db, admin, datos.nombre_usuario, datos.nombre_completo, datos.rol, datos.password))


@router.put("/yo/password", status_code=204)
def cambiar_mi_password(datos: MiPasswordIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Cualquier usuario cambia su propia contraseña (pide la actual)."""
    try:
        usuarios.cambiar_mi_password(db, usuario, datos.actual, datos.nueva)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()


@router.put("/{usuario_id}")
def actualizar(usuario_id: int, datos: UsuarioCambioIn, admin: Usuario = Depends(solo_admin),
               db: Session = Depends(get_db)):
    return _hacer(db, admin, lambda: usuarios.actualizar(
        db, admin, usuario_id, datos.nombre_completo, datos.rol, datos.activo))


@router.put("/{usuario_id}/password")
def restablecer_password(usuario_id: int, datos: PasswordIn, admin: Usuario = Depends(solo_admin),
                         db: Session = Depends(get_db)):
    """El administrador le pone una contraseña nueva; se cierran sus sesiones."""
    return _hacer(db, admin, lambda: usuarios.restablecer_password(db, admin, usuario_id, datos.password))
