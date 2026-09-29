"""Cancelaciones y devoluciones. Solo admin, con motivo. Las piezas regresan
siempre al lote del que salieron, y el dinero sale del turno abierto de la
caja indicada (ver models/devolucion.py).
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Devolucion, DevolucionRenglon, EstadoVenta, Lote, MetodoPago, Pago, RolUsuario, TipoDevolucion, Usuario,
    Venta, VentaRenglon, VentaRenglonLote,
)
from app.services import turnos
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso

CENTAVO = Decimal("0.01")


@dataclass
class PiezaDevuelta:
    renglon_id: int
    cantidad: Decimal
    lote_id: int | None = None  # lote de la caja devuelta; sin él, el primero con piezas por devolver


def _validar(db: Session, usuario: Usuario, venta_id: int, caja_id: int, motivo: str):
    if usuario.rol != RolUsuario.ADMIN:
        raise SinPermiso("Solo un administrador puede cancelar o hacer devoluciones")
    motivo = (motivo or "").strip()
    if not motivo:
        raise OperacionInvalida("El motivo es obligatorio")
    venta = db.scalar(
        select(Venta).where(Venta.id == venta_id, Venta.negocio_id == usuario.negocio_id).with_for_update()
    )
    if venta is None:
        raise NoEncontrado("Venta no encontrada")
    if venta.estado == EstadoVenta.CANCELADA:
        raise OperacionInvalida("La venta ya está cancelada")
    caja = turnos.obtener_caja(db, usuario.negocio_id, caja_id)
    turno = turnos.turno_abierto(db, caja.id)
    if turno is None:
        raise OperacionInvalida(f"La caja '{caja.nombre}' no tiene turno abierto para regresar el dinero")
    return venta, turno, motivo


def _reembolsado(db: Session, venta: Venta) -> tuple[Decimal, Decimal]:
    """(efectivo, tarjeta) ya regresados de esta venta."""
    efectivo, tarjeta = db.execute(
        select(func.coalesce(func.sum(Devolucion.efectivo), 0), func.coalesce(func.sum(Devolucion.tarjeta), 0))
        .where(Devolucion.venta_id == venta.id)
    ).one()
    return efectivo, tarjeta


def _repartir_reembolso(db: Session, venta: Venta, total: Decimal) -> tuple[Decimal, Decimal]:
    """Regresa por el mismo método con que se pagó; si fue mixto, primero a
    tarjeta (hasta lo que se pagó con tarjeta) y el resto en efectivo."""
    pagado_tarjeta = sum((p.monto for p in venta.pagos if p.metodo == MetodoPago.TARJETA), Decimal(0))
    _, tarjeta_ya = _reembolsado(db, venta)
    tarjeta = min(total, pagado_tarjeta - tarjeta_ya)
    return total - tarjeta, tarjeta


def _por_regresar(db: Session, venta: Venta) -> Decimal:
    efectivo, tarjeta = _reembolsado(db, venta)
    return venta.total - efectivo - tarjeta


def _registrar(
    db: Session, usuario: Usuario, venta: Venta, turno, tipo: TipoDevolucion, motivo: str,
    piezas: list[tuple[VentaRenglonLote, Decimal, Decimal]], total: Decimal,
) -> Devolucion:
    """piezas: (asignación de lote, cantidad, importe). Regresa las piezas a su
    lote y registra la devolución por `total`, que nunca pasa de lo que falta
    por regresar de la venta."""
    total = min(total, _por_regresar(db, venta))
    efectivo, tarjeta = _repartir_reembolso(db, venta, total)
    devolucion = Devolucion(
        negocio_id=venta.negocio_id, venta_id=venta.id, turno_id=turno.id, caja_id=turno.caja_id,
        usuario_id=usuario.id, tipo=tipo, motivo=motivo, total=total, efectivo=efectivo, tarjeta=tarjeta,
    )
    for asignacion, cantidad, importe in piezas:
        lote = db.scalar(select(Lote).where(Lote.id == asignacion.lote_id).with_for_update())
        lote.cantidad += cantidad
        asignacion.cantidad_devuelta += cantidad
        devolucion.renglones.append(DevolucionRenglon(
            venta_renglon_lote_id=asignacion.id, lote_id=lote.id, cantidad=cantidad, importe=importe,
        ))
    db.add(devolucion)
    db.flush()
    return devolucion


def cancelar_venta(db: Session, usuario: Usuario, venta_id: int, caja_id: int, motivo: str) -> Devolucion:
    """Cancela toda la venta: regresa lo que no se haya devuelto antes. No hace commit."""
    venta, turno, motivo = _validar(db, usuario, venta_id, caja_id, motivo)
    piezas = []
    for renglon in venta.renglones:
        for asignacion in renglon.lotes:
            pendiente = asignacion.cantidad - asignacion.cantidad_devuelta
            if pendiente > 0:
                piezas.append((asignacion, pendiente, (renglon.precio_unitario * pendiente).quantize(CENTAVO)))
    if not piezas and _por_regresar(db, venta) == 0:
        raise OperacionInvalida("Todo lo de esta venta ya se devolvió")
    # El dinero es todo lo que falta por regresar (así no se pierden centavos).
    devolucion = _registrar(
        db, usuario, venta, turno, TipoDevolucion.CANCELACION, motivo, piezas, _por_regresar(db, venta),
    )
    venta.estado = EstadoVenta.CANCELADA
    return devolucion


def devolver_piezas(
    db: Session, usuario: Usuario, venta_id: int, caja_id: int, motivo: str, solicitadas: list[PiezaDevuelta],
) -> Devolucion:
    """Devuelve algunas piezas. No hace commit."""
    venta, turno, motivo = _validar(db, usuario, venta_id, caja_id, motivo)
    if not solicitadas:
        raise OperacionInvalida("Indica qué piezas se devuelven")
    renglones = {r.id: r for r in venta.renglones}

    piezas = []
    ya_pedido: dict[int, Decimal] = defaultdict(Decimal)  # por asignación, en esta solicitud
    for s in solicitadas:
        renglon: VentaRenglon | None = renglones.get(s.renglon_id)
        if renglon is None:
            raise NoEncontrado("Ese renglón no es de esta venta")
        if s.cantidad <= 0:
            raise OperacionInvalida("La cantidad a devolver debe ser mayor que cero")
        candidatas = [a for a in renglon.lotes if s.lote_id is None or a.lote_id == s.lote_id]
        if not candidatas:
            raise OperacionInvalida(f"{renglon.nombre} no se vendió de ese lote")
        disponibles = sum(a.cantidad - a.cantidad_devuelta - ya_pedido[a.id] for a in candidatas)
        if s.cantidad > disponibles:
            raise OperacionInvalida(f"De {renglon.nombre} solo se pueden devolver {disponibles} piezas")

        pendiente = s.cantidad
        for asignacion in candidatas:
            libre = asignacion.cantidad - asignacion.cantidad_devuelta - ya_pedido[asignacion.id]
            tomar = min(libre, pendiente)
            if tomar > 0:
                piezas.append((asignacion, tomar, (renglon.precio_unitario * tomar).quantize(CENTAVO)))
                ya_pedido[asignacion.id] += tomar
                pendiente -= tomar

    total = sum((importe for _, _, importe in piezas), Decimal(0))
    return _registrar(db, usuario, venta, turno, TipoDevolucion.DEVOLUCION, motivo, piezas, total)
