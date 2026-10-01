"""Versión del sistema y actualizaciones automáticas (ver services/actualizaciones.py)."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import solo_admin
from app.models import Usuario
from app.services import actualizaciones

router = APIRouter(prefix="/sistema", tags=["sistema"])


@router.get("/version")
def version():
    """La versión que está corriendo. Las pantallas abiertas la revisan: si
    cambió, el sistema se actualizó y hay que recargar."""
    return {"version": actualizaciones.VERSION}


@router.get("/actualizaciones")
def ver_actualizaciones(usuario: Usuario = Depends(solo_admin)):
    return actualizaciones.estado()


@router.post("/actualizaciones/instalar-ahora")
def instalar_ahora(usuario: Usuario = Depends(solo_admin)):
    try:
        return actualizaciones.instalar_ahora()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
