"""Respaldos de la base (solo administradores). Ver services/respaldos.py."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

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
