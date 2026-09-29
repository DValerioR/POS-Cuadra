from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Negocio, Usuario
from app.schemas.negocio import NegocioOut, NegocioUpdate

router = APIRouter(prefix="/negocio", tags=["negocio"])


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
