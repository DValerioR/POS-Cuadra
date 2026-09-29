from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import usuario_actual
from app.core.config import settings
from app.core.database import get_db
from app.models import RolUsuario, Usuario, Venta
from app.schemas.venta import (
    CambioIn, CambioOut, CancelarIn, DevolucionOut, DevolverIn, ImpresionOut, LoteVendidoOut, PagoOut, ReimprimirIn, RenglonOut, VentaIn,
    VentaOut, VentaResumenOut,
)
from app.services import devoluciones, impresion, turnos, ventas
from app.services.devoluciones import PiezaDevuelta
from app.services.errores import ERRORES_NEGOCIO, a_http
from app.services.ventas import RenglonSolicitado

router = APIRouter(prefix="/ventas", tags=["ventas"])


def _venta_out(venta: Venta, avisos: list[str] | None = None, impreso: ImpresionOut | None = None) -> VentaOut:
    return VentaOut(
        id=venta.id, folio=venta.folio, turno_id=venta.turno_id, caja_id=venta.caja_id,
        usuario_id=venta.usuario_id, estado=venta.estado,
        subtotal=venta.subtotal, ieps=venta.ieps, iva=venta.iva, total=venta.total,
        cambio=sum((p.cambio or 0 for p in venta.pagos), Decimal(0)),
        created_at=venta.created_at,
        renglones=[
            RenglonOut(
                id=r.id, producto_id=r.producto_id, nombre=r.nombre, cantidad=r.cantidad,
                precio_unitario=r.precio_unitario, importe=r.importe,
                subtotal=r.subtotal, ieps=r.ieps, iva=r.iva,
                cantidad_devuelta=sum((l.cantidad_devuelta for l in r.lotes), Decimal(0)),
                lotes=[
                    LoteVendidoOut(
                        lote_id=l.lote_id, cantidad=l.cantidad, cantidad_devuelta=l.cantidad_devuelta,
                        numero_lote=l.lote.numero_lote, caducidad=l.lote.caducidad,
                    )
                    for l in r.lotes
                ],
            )
            for r in venta.renglones
        ],
        pagos=[PagoOut(metodo=p.metodo, monto=p.monto, recibido=p.recibido, cambio=p.cambio) for p in venta.pagos],
        devoluciones=[DevolucionOut.model_validate(d) for d in venta.devoluciones],
        avisos=avisos or [],
        impresion=impreso,
    )


@router.post("", response_model=VentaOut, status_code=201)
def registrar_venta(datos: VentaIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Cobra una venta. Todo o nada: si falta existencia o el pago no alcanza,
    no se guarda nada. `tarjeta` + `efectivo_recibido`: lo que no cubre la
    tarjeta se paga en efectivo y se calcula el cambio.

    Después de guardarla imprime el ticket (y abre el cajón si hubo
    efectivo). Si la impresión falla, la venta queda guardada igual y
    `impresion.error` dice por qué, para reimprimir."""
    try:
        venta, avisos = ventas.registrar_venta(
            db, usuario, datos.caja_id,
            [RenglonSolicitado(**r.model_dump()) for r in datos.renglones],
            datos.tarjeta, datos.efectivo_recibido,
        )
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(venta)
    r = impresion.imprimir_venta(db, venta)
    return _venta_out(venta, avisos, ImpresionOut(impreso=r.impreso, error=r.error))


@router.get("/{venta_id}", response_model=VentaOut)
def obtener_venta(venta_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        return _venta_out(ventas.obtener_venta(db, usuario.negocio_id, venta_id))
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/{venta_id}/ticket", response_class=PlainTextResponse)
def ver_ticket(venta_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """El ticket como texto, para verlo en pantalla sin impresora."""
    try:
        venta = ventas.obtener_venta(db, usuario.negocio_id, venta_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    caja = turnos.obtener_caja(db, usuario.negocio_id, venta.caja_id)
    return impresion.ticket_de_venta(db, venta, caja).texto()


@router.post("/{venta_id}/imprimir", response_model=ImpresionOut)
def reimprimir(
    venta_id: int, datos: ReimprimirIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)
):
    """Reimprime el ticket (marcado como reimpresión; no abre el cajón)."""
    try:
        venta = ventas.obtener_venta(db, usuario.negocio_id, venta_id)
        caja = turnos.obtener_caja(db, usuario.negocio_id, datos.caja_id or venta.caja_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    r = impresion.reimprimir_venta(db, venta, caja)
    return ImpresionOut(impreso=r.impreso, error=r.error)


@router.get("", response_model=list[VentaResumenOut])
def listar_ventas(
    turno_id: int | None = None,
    folio: int | None = None,
    desde: date | None = None,
    limite: int = Query(50, le=500),
    desplazamiento: int = 0,
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    """Historial de ventas. `folio` es el número del ticket.

    El administrador ve todo. Quien cobra (para pedir una devolución) busca
    cualquier venta por folio, pero sin folio solo ve las de hoy."""
    if usuario.rol == RolUsuario.BODEGA:
        raise HTTPException(status_code=403, detail="Tu usuario no tiene acceso a las ventas")
    stmt = select(Venta).where(Venta.negocio_id == usuario.negocio_id)
    if turno_id is not None:
        stmt = stmt.where(Venta.turno_id == turno_id)
    if folio is not None:
        stmt = stmt.where(Venta.folio == folio)
    if desde is not None:
        stmt = stmt.where(Venta.created_at >= desde)
    if usuario.rol != RolUsuario.ADMIN and folio is None:
        zona = ZoneInfo(settings.zona_horaria)
        stmt = stmt.where(Venta.created_at >= datetime.combine(datetime.now(zona).date(), time.min, tzinfo=zona))
    return db.scalars(stmt.order_by(Venta.id.desc()).limit(limite).offset(desplazamiento)).all()


@router.post("/{venta_id}/cancelar", response_model=DevolucionOut, status_code=201)
def cancelar_venta(venta_id: int, datos: CancelarIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Cancela toda la venta (solo admin, con motivo): las piezas regresan a su
    lote y el dinero sale del turno abierto de `caja_id`."""
    try:
        devolucion = devoluciones.cancelar_venta(db, usuario, venta_id, datos.caja_id, datos.motivo)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(devolucion)
    return devolucion


@router.post("/{venta_id}/devoluciones", response_model=DevolucionOut, status_code=201)
def devolver_piezas(venta_id: int, datos: DevolverIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Devuelve algunas piezas (solo admin, con motivo). Regresan a su lote
    original; el dinero se regresa por el método con que se pagó."""
    try:
        devolucion = devoluciones.devolver_piezas(
            db, usuario, venta_id, datos.caja_id, datos.motivo,
            [PiezaDevuelta(**p.model_dump()) for p in datos.piezas],
        )
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(devolucion)
    return devolucion


@router.post("/{venta_id}/cambio", response_model=CambioOut, status_code=201)
def cambiar_productos(venta_id: int, datos: CambioIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Cambio de producto (solo admin, con motivo): el cliente regresa piezas
    de esta venta y se lleva otras. Lo devuelto es saldo a favor; si lo nuevo
    cuesta más paga la diferencia, si cuesta menos se le regresa en efectivo.
    Imprime el ticket de la venta nueva."""
    try:
        devolucion, nueva, avisos = devoluciones.cambiar_productos(
            db, usuario, venta_id, datos.caja_id, datos.motivo,
            [PiezaDevuelta(**p.model_dump()) for p in datos.devueltas],
            [RenglonSolicitado(**r.model_dump()) for r in datos.nuevos],
            datos.tarjeta, datos.efectivo_recibido,
        )
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(devolucion)
    db.refresh(nueva)
    r = impresion.imprimir_venta(db, nueva)
    return CambioOut(
        valor_devuelto=devolucion.total,
        total_nuevo=nueva.total,
        paga_cliente=max(nueva.total - devolucion.total, Decimal(0)).quantize(Decimal("0.01")),
        se_le_regresa=devolucion.efectivo,
        devolucion=DevolucionOut.model_validate(devolucion),
        venta=_venta_out(nueva, avisos, ImpresionOut(impreso=r.impreso, error=r.error)),
    )
