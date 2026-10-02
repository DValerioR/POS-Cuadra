from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import solo_admin
from app.core.database import get_db
from app.models import Usuario
from app.services import usos

router = APIRouter(prefix="/usos", tags=["usos del plan"])


@router.get("")
def resumen(usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Lo usado este mes de IA y de facturas reales contra los topes del plan
    (solo admin)."""
    return usos.resumen(db, usuario.negocio_id)
