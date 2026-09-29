from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import usuario_actual
from app.core.database import get_db
from app.models import EstadoSolicitud, SolicitudDevolucion, TipoDevolucion, Usuario
from app.schemas.solicitud import PiezaSolicitadaOut, RechazoIn, SolicitudIn, SolicitudOut
from app.services import solicitudes
from app.services.devoluciones import PiezaDevuelta
from app.services.errores import ERRORES_NEGOCIO, a_http

router = APIRouter(tags=["solicitudes de devolución"])


def _nombre(usuario: Usuario | None) -> str | None:
    return (usuario.nombre_completo or usuario.nombre_usuario) if usuario else None


def _out(s: SolicitudDevolucion) -> SolicitudOut:
    renglones = {r.id: r for r in s.venta.renglones}
    piezas = []
    for p in s.piezas:
        renglon = renglones.get(p["renglon_id"])
        cantidad = Decimal(p["cantidad"])
        piezas.append(PiezaSolicitadaOut(
            renglon_id=p["renglon_id"], nombre=renglon.nombre if renglon else "?", cantidad=cantidad,
            importe=(renglon.precio_unitario * cantidad).quantize(Decimal("0.01")) if renglon else Decimal(0),
        ))
    return SolicitudOut(
        id=s.id, venta_id=s.venta_id, folio=s.venta.folio, fecha_venta=s.venta.created_at, total_venta=s.venta.total,
        caja_id=s.caja_id, caja=s.caja.nombre, solicitada_por=_nombre(s.solicitada_por),
        tipo=s.tipo, motivo=s.motivo, piezas=piezas, total=s.total, efectivo=s.efectivo, tarjeta=s.tarjeta,
        estado=s.estado, resuelta_por=_nombre(s.resuelta_por), resuelta_en=s.resuelta_en,
        respuesta=s.respuesta, vista=s.vista, created_at=s.created_at,
    )


def _guardar(db: Session, s: SolicitudDevolucion) -> SolicitudOut:
    db.commit()
    db.refresh(s)
    return _out(s)


@router.post("/ventas/{venta_id}/solicitudes", response_model=SolicitudOut, status_code=201)
def pedir(venta_id: int, datos: SolicitudIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """El cajero pide una devolución o cancelación; la autoriza un administrador."""
    try:
        s = solicitudes.crear(
            db, usuario, venta_id, datos.caja_id, TipoDevolucion(datos.tipo), datos.motivo,
            [PiezaDevuelta(**p.model_dump()) for p in datos.piezas],
        )
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    return _guardar(db, s)


@router.get("/solicitudes", response_model=list[SolicitudOut])
def listar(
    estado: EstadoSolicitud | None = None,
    desde: datetime | None = None,
    limite: int = Query(50, le=200),
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    """Centro de notificaciones (solo admin)."""
    try:
        return [_out(s) for s in solicitudes.listar(db, usuario, estado, desde, limite)]
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/solicitudes/pendientes")
def contar_pendientes(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Cuántas esperan respuesta (para la campana de la barra, solo admin)."""
    try:
        return {"pendientes": solicitudes.contar_pendientes(db, usuario)}
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/solicitudes/caja/{caja_id}", response_model=list[SolicitudOut])
def de_caja(caja_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Lo que ve el cajero: sus solicitudes pendientes y las respuestas que no ha visto."""
    try:
        return [_out(s) for s in solicitudes.de_caja(db, usuario, caja_id)]
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.post("/solicitudes/{solicitud_id}/autorizar", response_model=SolicitudOut)
def autorizar(solicitud_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Hace la devolución o cancelación en la caja que la pidió (solo admin)."""
    try:
        s = solicitudes.autorizar(db, usuario, solicitud_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    return _guardar(db, s)


@router.post("/solicitudes/{solicitud_id}/rechazar", response_model=SolicitudOut)
def rechazar(
    solicitud_id: int, datos: RechazoIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db),
):
    try:
        s = solicitudes.rechazar(db, usuario, solicitud_id, datos.respuesta)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    return _guardar(db, s)


@router.post("/solicitudes/{solicitud_id}/vista", response_model=SolicitudOut)
def marcar_vista(solicitud_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """El cajero ya vio la respuesta."""
    try:
        s = solicitudes.marcar_vista(db, usuario, solicitud_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    return _guardar(db, s)
