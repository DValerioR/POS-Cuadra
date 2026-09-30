"""Reporte de ventas de un día o un periodo (solo administradores).

Qué cuenta cada cifra:
- vendido: total con impuestos de las ventas NO canceladas del periodo.
- canceladas: ventas del periodo que se cancelaron completas (no suman).
- devuelto: lo que se regresó en devoluciones parciales y cambios hechos en el
  periodo (pueden ser de ventas de otros días: es lo que salió de la caja).
- venta_neta = vendido − devuelto.
- efectivo / tarjeta: cómo se cobraron las ventas no canceladas (el "saldo a
  favor" de un cambio no es dinero y no cuenta).
- ganancia_estimada: de las piezas vendidas que tienen costo (el del lote
  del que salieron o, si no, el del producto por pieza): su venta sin
  impuestos − su costo. `porcentaje_con_costo` dice qué parte de la venta sin
  impuestos cubre. Es estimada: no descuenta devoluciones.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Caja, Categoria, Devolucion, EstadoVenta, Lote, MetodoPago, Pago, Producto, TipoDevolucion, Usuario, Venta,
    VentaRenglon, VentaRenglonLote,
)
from app.services.errores import OperacionInvalida

CENTAVO = Decimal("0.01")


def hoy() -> date:
    return datetime.now(ZoneInfo(settings.zona_horaria)).date()


def _rango(desde: date, hasta: date) -> tuple[datetime, datetime]:
    if hasta < desde:
        raise OperacionInvalida("La fecha final no puede ser antes que la inicial")
    if (hasta - desde).days > 731:
        raise OperacionInvalida("El periodo máximo es de 2 años")
    zona = ZoneInfo(settings.zona_horaria)
    return datetime.combine(desde, time.min, tzinfo=zona), datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=zona)


def _d(valor) -> Decimal:
    return Decimal(valor or 0).quantize(CENTAVO)


def reporte(db: Session, negocio_id: int, desde: date, hasta: date, limite_productos: int = 20) -> dict:
    inicio, fin = _rango(desde, hasta)
    del_periodo = and_(Venta.negocio_id == negocio_id, Venta.created_at >= inicio, Venta.created_at < fin)
    validas = and_(del_periodo, Venta.estado != EstadoVenta.CANCELADA)

    tickets, vendido, subtotal, iva, ieps = db.execute(select(
        func.count(), func.sum(Venta.total), func.sum(Venta.subtotal), func.sum(Venta.iva), func.sum(Venta.ieps),
    ).where(validas)).one()
    canceladas, total_canceladas = db.execute(
        select(func.count(), func.sum(Venta.total)).where(del_periodo, Venta.estado == EstadoVenta.CANCELADA)).one()
    piezas = db.scalar(select(func.sum(VentaRenglon.cantidad)).join(Venta, Venta.id == VentaRenglon.venta_id).where(validas))
    pagos = dict(db.execute(
        select(Pago.metodo, func.sum(Pago.monto)).join(Venta, Venta.id == Pago.venta_id).where(validas).group_by(Pago.metodo)
    ).all())
    devoluciones, devuelto = db.execute(select(func.count(), func.sum(Devolucion.total)).where(
        Devolucion.negocio_id == negocio_id, Devolucion.created_at >= inicio, Devolucion.created_at < fin,
        Devolucion.tipo != TipoDevolucion.CANCELACION)).one()

    # Costo de lo vendido: por lote; si el lote no tiene costo, el del producto por pieza.
    costo_pieza = func.coalesce(Lote.costo_unitario, Producto.costo / func.nullif(Producto.factor_conversion, 0))
    venta_pieza = VentaRenglon.subtotal / func.nullif(VentaRenglon.cantidad, 0)
    con_costo = costo_pieza.is_not(None)
    ganancia, subtotal_con_costo, sin_costo = db.execute(
        select(func.sum(VentaRenglonLote.cantidad * (venta_pieza - costo_pieza)),
               func.sum(VentaRenglonLote.cantidad * venta_pieza).filter(con_costo),
               func.count().filter(costo_pieza.is_(None)))
        .select_from(VentaRenglonLote)
        .join(VentaRenglon, VentaRenglon.id == VentaRenglonLote.renglon_id)
        .join(Venta, Venta.id == VentaRenglon.venta_id)
        .join(Lote, Lote.id == VentaRenglonLote.lote_id)
        .join(Producto, Producto.id == VentaRenglon.producto_id)
        .where(validas)
    ).one()

    vendido, devuelto = _d(vendido), _d(devuelto)
    tickets = tickets or 0
    return {
        "desde": desde, "hasta": hasta,
        "tickets": tickets,
        "vendido": vendido,
        "promedio_ticket": _d(vendido / tickets) if tickets else _d(0),
        "piezas": Decimal(piezas or 0).normalize(),
        "devoluciones": devoluciones or 0, "devuelto": devuelto,
        "venta_neta": vendido - devuelto,
        "canceladas": canceladas or 0, "total_canceladas": _d(total_canceladas),
        "efectivo": _d(pagos.get(MetodoPago.EFECTIVO)), "tarjeta": _d(pagos.get(MetodoPago.TARJETA)),
        "subtotal": _d(subtotal), "iva": _d(iva), "ieps": _d(ieps),
        "ganancia_estimada": _d(ganancia),
        "porcentaje_con_costo": (Decimal(subtotal_con_costo or 0) * 100 / Decimal(subtotal)).quantize(Decimal("1"))
        if subtotal else Decimal(0),
        "piezas_sin_costo": sin_costo or 0,
        "por_hora": _agrupar(db, validas, func.extract("hour", func.timezone(settings.zona_horaria, Venta.created_at)), int),
        "por_dia": _agrupar(db, validas, func.date(func.timezone(settings.zona_horaria, Venta.created_at)), lambda d: d),
        "por_cajero": _agrupar_join(db, validas, Usuario.nombre_completo, Usuario, Usuario.id == Venta.usuario_id),
        "por_caja": _agrupar_join(db, validas, Caja.nombre, Caja, Caja.id == Venta.caja_id),
        "por_categoria": _por_categoria(db, validas),
        "productos": _productos(db, validas, limite_productos),
    }


def _agrupar(db, filtro, clave, convertir) -> list[dict]:
    filas = db.execute(select(clave, func.count(), func.sum(Venta.total)).where(filtro).group_by(clave).order_by(clave)).all()
    return [{"grupo": convertir(g), "tickets": n, "vendido": _d(t)} for g, n, t in filas]


def _agrupar_join(db, filtro, nombre, tabla, union) -> list[dict]:
    filas = db.execute(select(nombre, func.count(), func.sum(Venta.total)).join(tabla, union).where(filtro)
                       .group_by(nombre).order_by(func.sum(Venta.total).desc())).all()
    return [{"grupo": g, "tickets": n, "vendido": _d(t)} for g, n, t in filas]


def _por_categoria(db, filtro) -> list[dict]:
    nombre = func.coalesce(Categoria.nombre, "Sin categoría")
    filas = db.execute(
        select(nombre, func.sum(VentaRenglon.cantidad), func.sum(VentaRenglon.importe))
        .join(Venta, Venta.id == VentaRenglon.venta_id)
        .join(Producto, Producto.id == VentaRenglon.producto_id)
        .outerjoin(Categoria, Categoria.id == Producto.categoria_id)
        .where(filtro).group_by(nombre).order_by(func.sum(VentaRenglon.importe).desc())
    ).all()
    return [{"grupo": g, "piezas": Decimal(p).normalize(), "vendido": _d(t)} for g, p, t in filas]


def _productos(db, filtro, limite) -> list[dict]:
    filas = db.execute(
        select(VentaRenglon.producto_id, func.max(VentaRenglon.nombre), func.sum(VentaRenglon.cantidad),
               func.sum(VentaRenglon.importe))
        .join(Venta, Venta.id == VentaRenglon.venta_id).where(filtro)
        .group_by(VentaRenglon.producto_id).order_by(func.sum(VentaRenglon.importe).desc()).limit(limite)
    ).all()
    return [{"producto_id": pid, "nombre": n, "piezas": Decimal(p).normalize(), "vendido": _d(t)} for pid, n, p, t in filas]
