from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.negocio import Negocio
from app.schemas.negocio import NegocioOut, NegocioUpdate

router = APIRouter(prefix="/negocios", tags=["negocios"])


@router.get("/{negocio_id}", response_model=NegocioOut)
def obtener_negocio(negocio_id: int, db: Session = Depends(get_db)):
    negocio = db.get(Negocio, negocio_id)
    if negocio is None:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    return negocio


@router.put("/{negocio_id}", response_model=NegocioOut)
def actualizar_negocio(negocio_id: int, datos: NegocioUpdate, db: Session = Depends(get_db)):
    """Configuración del negocio. Mandar `redondeo_precio_venta: null` apaga el redondeo."""
    negocio = db.get(Negocio, negocio_id)
    if negocio is None:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(negocio, campo, valor)
    db.commit()
    db.refresh(negocio)
    return negocio
