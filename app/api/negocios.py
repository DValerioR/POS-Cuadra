import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, undefer

from app.core.auth import solo_admin, usuario_actual
from app.core.config import settings
from app.core.database import get_db
from app.impresion.logo import fondo_transparente, vista_previa_png
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
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un negocio con ese nombre")
    db.refresh(negocio)
    return negocio


async def _leer_imagen(request: Request) -> tuple[bytes, str]:
    """La imagen del cuerpo (PNG, JPG, GIF o WEBP, no un formulario). Si viene
    sobre fondo blanco se guarda con ese fondo transparente."""
    datos = await request.body()
    if len(datos) > LOGO_MAXIMO:
        raise HTTPException(status_code=413, detail="La imagen es muy pesada; el máximo es 5 MB")
    tipo = tipo_de_imagen(datos)
    if tipo is None:
        raise HTTPException(status_code=422, detail="El archivo no es una imagen PNG, JPG, GIF o WEBP")
    sin_fondo = fondo_transparente(datos)
    return sin_fondo if sin_fondo else (datos, tipo)


def _guardar(db: Session, negocio: Negocio) -> Negocio:
    db.commit()
    db.refresh(negocio)
    return negocio


def _imagen(datos: bytes | None, tipo: str | None, falta: str, cache: str = "private, max-age=31536000") -> Response:
    if not datos:
        raise HTTPException(status_code=404, detail=falta)
    return Response(datos, media_type=tipo, headers={"Cache-Control": cache})


# --- Imagen de inicio (el centro de la pantalla de Inicio) --------------------

@router.get("/logo")
def ver_logo(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """La imagen de la pantalla de inicio. La dirección cambia (?v=) con cada
    imagen nueva, así que el navegador la puede guardar mucho tiempo."""
    negocio = db.get(Negocio, usuario.negocio_id, options=[undefer(Negocio.logo_imagen)])
    return _imagen(negocio.logo_imagen, negocio.logo_tipo, "El negocio no tiene imagen de inicio")


@router.put("/logo", response_model=NegocioOut)
async def subir_logo(request: Request, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Cambia la imagen de inicio (no toca el logo de la farmacia)."""
    datos, tipo = await _leer_imagen(request)
    negocio = db.get(Negocio, usuario.negocio_id)
    negocio.logo_imagen, negocio.logo_tipo = datos, tipo
    negocio.logo_url = f"/negocio/logo?v={time.time_ns()}"
    return _guardar(db, negocio)


@router.delete("/logo", response_model=NegocioOut)
def quitar_logo(usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Quita la imagen de inicio; la pantalla vuelve a mostrar el nombre del negocio."""
    negocio = db.get(Negocio, usuario.negocio_id)
    negocio.logo_imagen = negocio.logo_tipo = negocio.logo_url = None
    return _guardar(db, negocio)


# --- Logo de la farmacia (barra, inicio de sesión, tableta y ticket) -----------

@router.get("/marca")
def ver_marca(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    negocio = db.get(Negocio, usuario.negocio_id, options=[undefer(Negocio.marca_imagen)])
    return _imagen(negocio.marca_imagen, negocio.marca_tipo, "El negocio no tiene logo")


@router.get("/marca-publica")
def ver_marca_publica(db: Session = Depends(get_db)):
    """El logo del negocio predeterminado, sin sesión (para la pantalla de
    inicio de sesión). No es información privada."""
    negocio = db.get(Negocio, settings.negocio_predeterminado, options=[undefer(Negocio.marca_imagen)])
    return _imagen(negocio.marca_imagen if negocio else None, negocio.marca_tipo if negocio else None,
                   "Sin logo", cache="no-cache")


@router.get("/marca-ticket")
def ver_marca_ticket(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """El logo como sale impreso en el ticket (en puntos blanco y negro)."""
    negocio = db.get(Negocio, usuario.negocio_id, options=[undefer(Negocio.marca_imagen)])
    if not negocio.marca_imagen:
        raise HTTPException(status_code=404, detail="El negocio no tiene logo")
    return Response(vista_previa_png(negocio.marca_imagen), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=31536000"})


@router.put("/marca", response_model=NegocioOut)
async def subir_marca(request: Request, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Cambia el logo de la farmacia (no toca la imagen de inicio)."""
    datos, tipo = await _leer_imagen(request)
    negocio = db.get(Negocio, usuario.negocio_id)
    negocio.marca_imagen, negocio.marca_tipo = datos, tipo
    negocio.marca_url = f"/negocio/marca?v={time.time_ns()}"
    return _guardar(db, negocio)


@router.delete("/marca", response_model=NegocioOut)
def quitar_marca(usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Quita el logo: vuelve la cruz y el ticket sale sin logo."""
    negocio = db.get(Negocio, usuario.negocio_id)
    negocio.marca_imagen = negocio.marca_tipo = negocio.marca_url = None
    return _guardar(db, negocio)
