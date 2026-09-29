from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import solo_admin, usuario_actual
from app.models import RolUsuario, Usuario
from app.services import configuracion_ia
from app.services.errores import ERRORES_NEGOCIO, a_http

router = APIRouter(prefix="/ia", tags=["asistente de IA"])


class ClaveIn(BaseModel):
    clave: str


@router.get("/estado")
def estado(usuario: Usuario = Depends(usuario_actual)):
    """Si la lectura con IA está disponible. Los últimos caracteres de la
    clave solo los ve un administrador."""
    datos = configuracion_ia.estado()
    if usuario.rol != RolUsuario.ADMIN:
        datos["termina_en"] = None
    return datos


@router.put("/clave")
def guardar_clave(datos: ClaveIn, usuario: Usuario = Depends(solo_admin)):
    """Guarda la clave en el .env y la usa desde ese momento."""
    try:
        return configuracion_ia.guardar(datos.clave)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.delete("/clave")
def quitar_clave(usuario: Usuario = Depends(solo_admin)):
    return configuracion_ia.quitar()


@router.post("/probar")
def probar(usuario: Usuario = Depends(solo_admin)):
    try:
        return configuracion_ia.probar()
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
