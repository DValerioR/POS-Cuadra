from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.auth import usuario_actual
from app.core.database import get_db
from app.models import Usuario
from app.schemas.venta_en_espera import VentaEnEsperaIn, VentaEnEsperaOut
from app.services import ventas_en_espera
from app.services.errores import ERRORES_NEGOCIO, a_http
from app.services.ventas_en_espera import RenglonEnEspera

router = APIRouter(prefix="/ventas-en-espera", tags=["ventas en espera"])


@router.get("", response_model=list[VentaEnEsperaOut])
def listar(caja_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Las ventas guardadas de una caja, de la más vieja a la más nueva."""
    try:
        return ventas_en_espera.listar(db, usuario, caja_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.post("", response_model=VentaEnEsperaOut, status_code=201)
def guardar(datos: VentaEnEsperaIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Guarda la venta de la pantalla para atender a otro cliente (máximo 5 por caja)."""
    try:
        espera = ventas_en_espera.guardar(
            db, usuario, datos.caja_id, [RenglonEnEspera(**r.model_dump()) for r in datos.renglones], datos.nota,
        )
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(espera)
    return espera


@router.post("/{espera_id}/retomar", response_model=VentaEnEsperaOut)
def retomar(espera_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Saca la venta de la lista y la regresa para cargarla en la pantalla."""
    try:
        espera = ventas_en_espera.retomar(db, usuario, espera_id)
        salida = VentaEnEsperaOut.model_validate(espera)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return salida


@router.delete("/{espera_id}", status_code=204)
def borrar(espera_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        ventas_en_espera.borrar(db, usuario, espera_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return Response(status_code=204)
