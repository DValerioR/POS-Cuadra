import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session, undefer

from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Negocio, Usuario
from app.schemas.negocio import NegocioOut, NegocioUpdate

router = APIRouter(prefix="/negocio", tags=["negocio"])

LOGO_MAXIMO = 5 * 1024 * 1024  # 5 MB: sobra para un logo o una foto


def tipo_de_imagen(datos: bytes) -> str | None:
    """Tipo de la imagen según sus primeros bytes (no se confía en el nombre
    del archivo). Solo formatos que el navegador muestra y que no llevan
    código: nada de SVG."""
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if datos.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if datos[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("", response_model=NegocioOut)
def obtener_negocio(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """El negocio del usuario que inició sesión."""
    return db.get(Negocio, usuario.negocio_id)


@router.put("", response_model=NegocioOut)
def actualizar_negocio(datos: NegocioUpdate, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Configuración del negocio. Mandar `redondeo_precio_venta: null` apaga el redondeo."""
    negocio = db.get(Negocio, usuario.negocio_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(negocio, campo, valor)
    db.commit()
    db.refresh(negocio)
    return negocio


@router.get("/logo")
def ver_logo(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """La imagen de la pantalla de inicio. La dirección cambia (?v=) con cada
    imagen nueva, así que el navegador la puede guardar mucho tiempo."""
    negocio = db.get(Negocio, usuario.negocio_id, options=[undefer(Negocio.logo_imagen)])
    if not negocio.logo_imagen:
        raise HTTPException(status_code=404, detail="El negocio no tiene imagen de inicio")
    return Response(negocio.logo_imagen, media_type=negocio.logo_tipo,
                    headers={"Cache-Control": "private, max-age=31536000"})


@router.put("/logo", response_model=NegocioOut)
async def subir_logo(request: Request, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Cambia la imagen de inicio. El cuerpo es la imagen tal cual (PNG, JPG,
    GIF o WEBP), no un formulario."""
    datos = await request.body()
    if len(datos) > LOGO_MAXIMO:
        raise HTTPException(status_code=413, detail="La imagen es muy pesada; el máximo es 5 MB")
    tipo = tipo_de_imagen(datos)
    if tipo is None:
        raise HTTPException(status_code=422, detail="El archivo no es una imagen PNG, JPG, GIF o WEBP")
    negocio = db.get(Negocio, usuario.negocio_id)
    negocio.logo_imagen = datos
    negocio.logo_tipo = tipo
    negocio.logo_url = f"/negocio/logo?v={time.time_ns()}"
    db.commit()
    db.refresh(negocio)
    return negocio


@router.delete("/logo", response_model=NegocioOut)
def quitar_logo(usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Quita la imagen de inicio; la pantalla vuelve a mostrar el nombre del negocio."""
    negocio = db.get(Negocio, usuario.negocio_id)
    negocio.logo_imagen = None
    negocio.logo_tipo = None
    negocio.logo_url = None
    db.commit()
    db.refresh(negocio)
    return negocio
