from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Usuario, Venta
from app.schemas.venta import (
    LoteVendidoOut, PagoOut, RenglonOut, VentaIn, VentaOut, VentaResumenOut,
)
from app.services import ventas
from app.services.errores import ERRORES_NEGOCIO, a_http
from app.services.ventas import RenglonSolicitado

router = APIRouter(prefix="/ventas", tags=["ventas"])


def _venta_out(venta: Venta, avisos: list[str] | None = None) -> VentaOut:
    return VentaOut(
        id=venta.id, folio=venta.folio, turno_id=venta.turno_id, caja_id=venta.caja_id,
        usuario_id=venta.usuario_id, estado=venta.estado,
        subtotal=venta.subtotal, ieps=venta.ieps, iva=venta.iva, total=venta.total,
        cambio=sum((p.cambio or 0 for p in venta.pagos), Decimal(0)),
        created_at=venta.created_at,
        renglones=[
            RenglonOut(
                producto_id=r.producto_id, nombre=r.nombre, cantidad=r.cantidad,
                precio_unitario=r.precio_unitario, importe=r.importe,
                subtotal=r.subtotal, ieps=r.ieps, iva=r.iva,
                lotes=[
                    LoteVendidoOut(
                        lote_id=l.lote_id, cantidad=l.cantidad,
                        numero_lote=l.lote.numero_lote, caducidad=l.lote.caducidad,
                    )
                    for l in r.lotes
                ],
            )
            for r in venta.renglones
        ],
        pagos=[PagoOut(metodo=p.metodo, monto=p.monto, recibido=p.recibido, cambio=p.cambio) for p in venta.pagos],
        avisos=avisos or [],
    )


@router.post("", response_model=VentaOut, status_code=201)
def registrar_venta(datos: VentaIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Cobra una venta. Todo o nada: si falta existencia o el pago no alcanza,
    no se guarda nada. `tarjeta` + `efectivo_recibido`: lo que no cubre la
    tarjeta se paga en efectivo y se calcula el cambio."""
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
    return _venta_out(venta, avisos)


@router.get("/{venta_id}", response_model=VentaOut)
def obtener_venta(venta_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        return _venta_out(ventas.obtener_venta(db, usuario.negocio_id, venta_id))
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("", response_model=list[VentaResumenOut])
def listar_ventas(
    turno_id: int | None = None,
    desde: date | None = None,
    limite: int = Query(50, le=500),
    desplazamiento: int = 0,
    usuario: Usuario = Depends(solo_admin),
    db: Session = Depends(get_db),
):
    """Historial de ventas (solo admin)."""
    stmt = select(Venta).where(Venta.negocio_id == usuario.negocio_id)
    if turno_id is not None:
        stmt = stmt.where(Venta.turno_id == turno_id)
    if desde is not None:
        stmt = stmt.where(Venta.created_at >= desde)
    return db.scalars(stmt.order_by(Venta.id.desc()).limit(limite).offset(desplazamiento)).all()
