from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Caja, Turno, Usuario
from app.schemas.turno import (
    AbrirTurnoIn, CajaIn, CajaOut, CajaUpdate, CerrarTurnoIn, CorteOut, PruebaImpresionIn, TurnoOut,
)
from app.schemas.venta import ImpresionOut
from app.services import impresion, turnos
from app.services.errores import ERRORES_NEGOCIO, a_http

router = APIRouter(tags=["turnos"])


# --- Cajas -----------------------------------------------------------------

def _guardar_caja(db: Session, caja: Caja) -> CajaOut:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una caja con ese nombre")
    db.refresh(caja)
    return CajaOut.de(caja)


@router.get("/cajas", response_model=list[CajaOut])
def listar_cajas(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    cajas = db.scalars(select(Caja).where(Caja.negocio_id == usuario.negocio_id).order_by(Caja.nombre))
    return [CajaOut.de(c) for c in cajas]


@router.post("/cajas", response_model=CajaOut, status_code=201)
def crear_caja(datos: CajaIn, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    caja = Caja(negocio_id=usuario.negocio_id, nombre=datos.nombre.strip())
    db.add(caja)
    return _guardar_caja(db, caja)


@router.put("/cajas/{caja_id}", response_model=CajaOut)
def actualizar_caja(caja_id: int, datos: CajaUpdate, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    try:
        caja = turnos.obtener_caja(db, usuario.negocio_id, caja_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(caja, campo, valor)
    return _guardar_caja(db, caja)


@router.post("/cajas/{caja_id}/prueba-impresion", response_model=ImpresionOut)
def prueba_impresion(
    caja_id: int, datos: PruebaImpresionIn, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)
):
    """Imprime un ticket de prueba (y abre el cajón si se pide) para
    verificar la configuración de la impresora de la caja."""
    try:
        caja = turnos.obtener_caja(db, usuario.negocio_id, caja_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    r = impresion.imprimir_prueba(caja, datos.abrir_cajon)
    return ImpresionOut(impreso=r.impreso, error=r.error)


# --- Turnos ----------------------------------------------------------------

@router.post("/turnos", response_model=TurnoOut, status_code=201)
def abrir_turno(datos: AbrirTurnoIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        turno = turnos.abrir_turno(db, usuario, datos.caja_id, datos.tipo, datos.fondo_inicial)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(turno)
    return turno


@router.get("/turnos/abierto", response_model=TurnoOut | None)
def turno_abierto(caja_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """El turno abierto de una caja, o null si no hay."""
    try:
        caja = turnos.obtener_caja(db, usuario.negocio_id, caja_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    return turnos.turno_abierto(db, caja.id)


@router.get("/turnos/{turno_id}/corte", response_model=CorteOut)
def ver_corte(turno_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Lo que se espera en caja ahora, para mostrarlo antes de contar y cerrar."""
    try:
        turno = turnos.obtener_turno(db, usuario.negocio_id, turno_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    t = turnos.totales_del_turno(db, turno)
    return CorteOut(
        turno_id=turno.id,
        fondo_inicial=t.fondo_inicial,
        ventas_efectivo=t.ventas_efectivo,
        ventas_tarjeta=t.ventas_tarjeta,
        reembolsos_efectivo=t.reembolsos_efectivo,
        reembolsos_tarjeta=t.reembolsos_tarjeta,
        efectivo_esperado=t.efectivo_esperado,
        tarjeta_esperado=t.tarjeta_esperado,
    )


@router.post("/turnos/{turno_id}/cerrar", response_model=TurnoOut)
def cerrar_turno(
    turno_id: int, datos: CerrarTurnoIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)
):
    try:
        turno = turnos.cerrar_turno(
            db, usuario, turno_id, datos.efectivo_contado, datos.tarjeta_contado, datos.notas
        )
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(turno)
    return turno


@router.get("/turnos", response_model=list[TurnoOut])
def listar_turnos(
    caja_id: int | None = None,
    desde: date | None = None,
    limite: int = Query(50, le=500),
    desplazamiento: int = 0,
    usuario: Usuario = Depends(solo_admin),
    db: Session = Depends(get_db),
):
    """Historial de turnos y cortes (solo admin: son reportes de dinero)."""
    stmt = select(Turno).where(Turno.negocio_id == usuario.negocio_id)
    if caja_id is not None:
        stmt = stmt.where(Turno.caja_id == caja_id)
    if desde is not None:
        stmt = stmt.where(Turno.abierto_en >= desde)
    return db.scalars(stmt.order_by(Turno.id.desc()).limit(limite).offset(desplazamiento)).all()
