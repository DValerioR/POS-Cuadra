import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import usuario_actual
from app.core.config import settings
from app.core.database import get_db
from app.models import AjusteInventario, TipoAjuste, Usuario
from app.schemas.inventario import (
    AjusteIn,
    AjusteOut,
    AvanceCaducidadesOut,
    CapturaCaducidadIn,
    ConteoIn,
    ExistenciaOut,
    LoteOut,
    MovimientoOut,
    NoCaducaIn,
    PorCaducarOut,
)
from app.services import inventario
from app.services.errores import ERRORES_NEGOCIO, NoEncontrado, a_http

router = APIRouter(prefix="/inventario", tags=["inventario"])


@router.get("/productos/{producto_id}", response_model=ExistenciaOut)
def existencia_producto(producto_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Existencia total y lotes del producto, en el orden en que deben salir (FEFO)."""
    try:
        producto = inventario.obtener_producto(db, usuario.negocio_id, producto_id)
    except NoEncontrado as e:
        raise a_http(e)
    return _existencia(db, producto)


def _existencia(db: Session, producto) -> ExistenciaOut:
    lotes = inventario.lotes_fefo(db, producto.id)
    return ExistenciaOut(
        producto_id=producto.id,
        clave=producto.clave,
        nombre=producto.nombre,
        controla_lote=inventario.controla_lote(db, producto),
        no_caduca=producto.no_caduca,
        existencia=sum((l.cantidad for l in lotes), 0),
        existencia_registrada=inventario.existencia_total(db, producto.id),
        sin_caducidad=sum((l.cantidad for l in lotes if l.caducidad is None), 0),
        lotes=[LoteOut.model_validate(l) for l in lotes],
    )


@router.put("/productos/{producto_id}/no-caduca", response_model=ExistenciaOut)
def marcar_no_caduca(
    producto_id: int, datos: NoCaducaIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)
):
    """Marca que el producto no caduca (admin y bodega): ya no se le pide
    caducidad y sale del avance de caducidades. Se puede desmarcar."""
    try:
        producto = inventario.marcar_no_caduca(db, usuario.negocio_id, usuario.id, producto_id, datos.no_caduca)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return _existencia(db, producto)


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
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
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
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(ajuste)
    return ajuste


@router.post("/conteo", response_model=ExistenciaOut)
def registrar_conteo(datos: ConteoIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Conteo físico del total del producto: la existencia queda igual al
    conteo (se respetan los lotes con caducidad mientras alcance)."""
    try:
        inventario.fijar_existencia(db, usuario.negocio_id, usuario.id, datos.producto_id, datos.conteo, datos.motivo)
        producto = inventario.obtener_producto(db, usuario.negocio_id, datos.producto_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return _existencia(db, producto)


@router.get("/productos/{producto_id}/movimientos", response_model=list[MovimientoOut])
def movimientos(
    producto_id: int, limite: int = Query(50, le=200),
    usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db),
):
    """Ajustes, mermas y capturas de caducidad del producto, del más reciente al más viejo."""
    try:
        return inventario.movimientos(db, usuario.negocio_id, producto_id, limite)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/por-caducar", response_model=list[PorCaducarOut])
def por_caducar(
    meses: int = Query(6, ge=0, le=24), usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db),
):
    """Lotes ya caducados y los que caducan en los próximos `meses`."""
    hoy = datetime.now(ZoneInfo(settings.zona_horaria)).date()
    mes = hoy.month - 1 + meses
    anio, mes = hoy.year + mes // 12, mes % 12 + 1
    hasta = date(anio, mes, min(hoy.day, calendar.monthrange(anio, mes)[1]))
    return inventario.por_caducar(db, usuario.negocio_id, hoy, hasta)


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
