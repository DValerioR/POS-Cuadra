from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import usuario_actual
from app.core.database import get_db
from app.models import AjusteInventario, TipoAjuste, Usuario
from app.schemas.inventario import (
    AjusteIn,
    AjusteOut,
    AvanceCaducidadesOut,
    CapturaCaducidadIn,
    ExistenciaOut,
    LoteOut,
)
from app.services import inventario
from app.services.inventario import NoEncontrado, OperacionInvalida, SinPermiso

router = APIRouter(prefix="/inventario", tags=["inventario"])


def _http(error: Exception) -> HTTPException:
    codigo = {NoEncontrado: 404, SinPermiso: 403, OperacionInvalida: 409}[type(error)]
    return HTTPException(status_code=codigo, detail=str(error))


@router.get("/productos/{producto_id}", response_model=ExistenciaOut)
def existencia_producto(producto_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Existencia total y lotes del producto, en el orden en que deben salir (FEFO)."""
    try:
        producto = inventario.obtener_producto(db, usuario.negocio_id, producto_id)
    except NoEncontrado as e:
        raise _http(e)
    lotes = inventario.lotes_fefo(db, producto.id)
    return ExistenciaOut(
        producto_id=producto.id,
        clave=producto.clave,
        nombre=producto.nombre,
        controla_lote=inventario.controla_lote(db, producto),
        existencia=sum((l.cantidad for l in lotes), 0),
        sin_caducidad=sum((l.cantidad for l in lotes if l.caducidad is None), 0),
        lotes=[LoteOut.model_validate(l) for l in lotes],
    )


@router.post("/captura-caducidad", response_model=LoteOut, status_code=201)
def capturar_caducidad(
    datos: CapturaCaducidadIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)
):
    """Registra la caducidad de piezas que estaban "sin caducidad" (inventario
    heredado). Regresa el lote real al que pasaron."""
    try:
        lote = inventario.capturar_caducidad(
            db, usuario.negocio_id, usuario.id, datos.producto_id,
            datos.caducidad, datos.cantidad, datos.numero_lote,
        )
    except (NoEncontrado, SinPermiso, OperacionInvalida) as e:
        db.rollback()
        raise _http(e)
    db.commit()
    db.refresh(lote)
    return lote


@router.post("/ajustes", response_model=AjusteOut, status_code=201)
def registrar_ajuste(datos: AjusteIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Ajuste por conteo físico (+/-) o merma (-), siempre con motivo."""
    try:
        ajuste = inventario.ajustar(
            db, usuario.negocio_id, usuario.id, datos.producto_id,
            TipoAjuste(datos.tipo), datos.cantidad, datos.motivo, datos.lote_id,
        )
    except (NoEncontrado, SinPermiso, OperacionInvalida) as e:
        db.rollback()
        raise _http(e)
    db.commit()
    db.refresh(ajuste)
    return ajuste


@router.get("/ajustes", response_model=list[AjusteOut])
def listar_ajustes(
    producto_id: int | None = None,
    tipo: TipoAjuste | None = None,
    desde: date | None = None,
    limite: int = Query(100, le=500),
    desplazamiento: int = 0,
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    """Bitácora de ajustes, del más reciente al más antiguo."""
    stmt = select(AjusteInventario).where(AjusteInventario.negocio_id == usuario.negocio_id)
    if producto_id is not None:
        stmt = stmt.where(AjusteInventario.producto_id == producto_id)
    if tipo is not None:
        stmt = stmt.where(AjusteInventario.tipo == tipo)
    if desde is not None:
        stmt = stmt.where(AjusteInventario.created_at >= desde)
    stmt = stmt.order_by(AjusteInventario.id.desc()).limit(limite).offset(desplazamiento)
    return db.scalars(stmt).all()


@router.get("/avance-caducidades", response_model=AvanceCaducidadesOut)
def avance_caducidades(
    limite: int = Query(50, le=500),
    desplazamiento: int = 0,
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    """Avance de la captura de caducidades del inventario heredado, y los
    productos pendientes (los de más piezas primero)."""
    return inventario.avance_caducidades(db, usuario.negocio_id, limite, desplazamiento)
