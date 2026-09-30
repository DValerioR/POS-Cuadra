"""Respaldos de la base (solo administradores). Ver services/respaldos.py."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.auth import solo_admin
from app.models import Usuario
from app.services import respaldos
from app.services.errores import ERRORES_NEGOCIO, a_http

router = APIRouter(prefix="/respaldos", tags=["respaldos"])


# GET /respaldos es la pantalla: por eso el estado es /respaldos/estado.
@router.get("/estado")
def estado(usuario: Usuario = Depends(solo_admin)):
    return respaldos.estado()


@router.post("", status_code=201)
def respaldar_ahora(usuario: Usuario = Depends(solo_admin)):
    try:
        return respaldos.hacer(automatico=False)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/archivo/{nombre}")
def descargar(nombre: str, usuario: Usuario = Depends(solo_admin)):
    try:
        ruta = respaldos.ruta_de(nombre)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    return FileResponse(ruta, media_type="application/octet-stream", filename=nombre)


class CopiaIn(BaseModel):
    ruta: str | None = None


@router.get("/destinos")
def destinos(usuario: Usuario = Depends(solo_admin)):
    """USB conectadas y carpetas de Google Drive / OneDrive detectadas en la computadora del servidor."""
    return respaldos.destinos()


@router.put("/copia")
def configurar_copia(datos: CopiaIn, usuario: Usuario = Depends(solo_admin)):
    try:
        return respaldos.configurar_copia(datos.ruta)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.post("/copia/probar")
def probar_copia(usuario: Usuario = Depends(solo_admin)):
    """Copia ahora el último respaldo a la carpeta de copia."""
    try:
        return respaldos.copiar_ultimo()
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
