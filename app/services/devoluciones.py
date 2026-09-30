"""Cancelaciones, devoluciones y cambios de producto. Solo admin, con motivo.
Las piezas regresan siempre al lote del que salieron, y el dinero sale del
turno abierto de la caja indicada (ver models/devolucion.py).

El cajero no las hace: pide una devolución o cancelación y un administrador
la autoriza desde cualquier computadora (services/solicitudes.py, que usa
`calcular_reembolso` para decir cuánto se regresaría).

Cada registro de devolución guarda el valor devuelto (`total`) y cuánto de
eso se regresó en dinero (`efectivo` + `tarjeta`). En devoluciones y
cancelaciones todo el valor se regresa en dinero; en un cambio de producto
el valor se usa como saldo a favor en la venta nueva y solo la diferencia,
si la hay, se regresa en efectivo.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Devolucion, DevolucionRenglon, EstadoVenta, Lote, MetodoPago, RolUsuario, TipoDevolucion, Usuario, Venta,
    VentaRenglon, VentaRenglonLote,
)
from app.services import turnos, ventas
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso
from app.services.ventas import RenglonSolicitado

CENTAVO = Decimal("0.01")

# (asignación de lote vendida, cantidad que regresa, importe)
Piezas = list[tuple[VentaRenglonLote, Decimal, Decimal]]


@dataclass
class PiezaDevuelta:
    renglon_id: int
    cantidad: Decimal
    lote_id: int | None = None  # lote de la caja devuelta; sin él, el primero con piezas por devolver


def _validar(db: Session, usuario: Usuario, venta_id: int, caja_id: int, motivo: str):
    if usuario.rol != RolUsuario.ADMIN:
        raise SinPermiso("Solo un administrador puede cancelar, hacer devoluciones o cambios")
    return validar_operacion(db, usuario.negocio_id, venta_id, caja_id, motivo)


def validar_operacion(db: Session, negocio_id: int, venta_id: int, caja_id: int, motivo: str):
    """Motivo, venta no cancelada y turno abierto en la caja. Bloquea la venta."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise OperacionInvalida("El motivo es obligatorio")
    venta = db.scalar(
        select(Venta).where(Venta.id == venta_id, Venta.negocio_id == negocio_id).with_for_update()
    )
    if venta is None:
        raise NoEncontrado("Venta no encontrada")
    if venta.estado == EstadoVenta.CANCELADA:
        raise OperacionInvalida("La venta ya está cancelada")
    caja = turnos.obtener_caja(db, negocio_id, caja_id)
    turno = turnos.turno_abierto(db, caja.id)
    if turno is None:
        raise OperacionInvalida(f"La caja '{caja.nombre}' no tiene turno abierto para regresar el dinero")
    return venta, turno, motivo


def _tarjeta_reembolsada(db: Session, venta: Venta) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(Devolucion.tarjeta), 0)).where(Devolucion.venta_id == venta.id))


def _por_regresar(db: Session, venta: Venta) -> Decimal:
    """Valor de la venta que aún no se ha devuelto (en dinero o como saldo de un cambio)."""
    devuelto = db.scalar(select(func.coalesce(func.sum(Devolucion.total), 0)).where(Devolucion.venta_id == venta.id))
    return venta.total - devuelto


def _repartir_reembolso(db: Session, venta: Venta, total: Decimal) -> tuple[Decimal, Decimal]:
    """Regresa por el mismo método con que se pagó; si fue mixto, primero a
    tarjeta (hasta lo que se pagó con tarjeta) y el resto en efectivo."""
    pagado_tarjeta = sum((p.monto for p in venta.pagos if p.metodo == MetodoPago.TARJETA), Decimal(0))
    tarjeta = min(total, pagado_tarjeta - _tarjeta_reembolsada(db, venta))
    return total - tarjeta, tarjeta


def _registrar(
    db: Session, usuario: Usuario, venta: Venta, turno, tipo: TipoDevolucion, motivo: str,
    piezas: Piezas, total: Decimal,
) -> Devolucion:
    """Regresa las piezas a su lote y registra la devolución por `total`, que
    nunca pasa de lo que falta por regresar de la venta. En devoluciones y
    cancelaciones el dinero se reparte por método de pago; en un cambio el
    dinero lo fija quien llama (solo la diferencia, en efectivo)."""
    total = min(total, _por_regresar(db, venta))
    if tipo == TipoDevolucion.CAMBIO:
        efectivo, tarjeta = Decimal(0), Decimal(0)
    else:
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


def _piezas_solicitadas(venta: Venta, solicitadas: list[PiezaDevuelta]) -> Piezas:
    """Valida qué piezas se devuelven y de qué lote. Nunca más de lo vendido."""
    if not solicitadas:
        raise OperacionInvalida("Indica qué piezas se devuelven")
    renglones = {r.id: r for r in venta.renglones}
    piezas: Piezas = []
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
                piezas.append((asignacion, tomar, ventas.importe_de_piezas(renglon, tomar)))
                ya_pedido[asignacion.id] += tomar
                pendiente -= tomar
    _paquetes_completos(venta, ya_pedido)
    return piezas


def _paquetes_completos(venta: Venta, ya_pedido: dict[int, Decimal]) -> None:
    """Lo vendido en paquete solo se regresa completo: si se devuelve algo de
    un paquete, deben venir todas las piezas pendientes de sus productos
    (así nadie se queda con un producto a precio de paquete)."""
    paquetes: dict[int, list[VentaRenglon]] = defaultdict(list)
    for r in venta.renglones:
        if r.oferta is not None and r.oferta.tipo == "paquete" and r.descuento > 0:
            paquetes[r.oferta_id].append(r)
    for renglones in paquetes.values():
        pedido = {r.id: sum((ya_pedido[a.id] for a in r.lotes), Decimal(0)) for r in renglones}
        if not any(pedido.values()):
            continue
        pendientes = {r.id: sum((a.cantidad - a.cantidad_devuelta for a in r.lotes), Decimal(0)) for r in renglones}
        if any(pedido[r.id] < pendientes[r.id] for r in renglones):
            lista = " y ".join(f"{pendientes[r.id].normalize():f} {r.nombre}" for r in renglones)
            raise OperacionInvalida(
                f"Se vendió en paquete: para devolverlo hay que regresar el paquete completo ({lista})"
            )



def calcular_reembolso(
    db: Session, venta: Venta, tipo: TipoDevolucion, solicitadas: list[PiezaDevuelta] | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    """(total, efectivo, tarjeta) que se regresaría con una devolución o
    cancelación, sin registrar nada. Valida las piezas igual que al hacerla."""
    if tipo == TipoDevolucion.CANCELACION:
        total = _por_regresar(db, venta)
        if total <= 0:
            raise OperacionInvalida("Todo lo de esta venta ya se devolvió")
    elif tipo == TipoDevolucion.DEVOLUCION:
        piezas = _piezas_solicitadas(venta, solicitadas or [])
        total = min(sum((importe for _, _, importe in piezas), Decimal(0)), _por_regresar(db, venta))
    else:
        raise OperacionInvalida("Los cambios de producto los hace un administrador en la caja")
    efectivo, tarjeta = _repartir_reembolso(db, venta, total)
    return total, efectivo, tarjeta


def cancelar_venta(db: Session, usuario: Usuario, venta_id: int, caja_id: int, motivo: str) -> Devolucion:
    """Cancela toda la venta: regresa lo que no se haya devuelto antes. No hace commit."""
    venta, turno, motivo = _validar(db, usuario, venta_id, caja_id, motivo)
    piezas: Piezas = []
    for renglon in venta.renglones:
        for asignacion in renglon.lotes:
            pendiente = asignacion.cantidad - asignacion.cantidad_devuelta
            if pendiente > 0:
                piezas.append((asignacion, pendiente, ventas.importe_de_piezas(renglon, pendiente)))
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
    piezas = _piezas_solicitadas(venta, solicitadas)
    total = sum((importe for _, _, importe in piezas), Decimal(0))
    return _registrar(db, usuario, venta, turno, TipoDevolucion.DEVOLUCION, motivo, piezas, total)


def cambiar_productos(
    db: Session,
    usuario: Usuario,
    venta_id: int,
    caja_id: int,
    motivo: str,
    devueltas: list[PiezaDevuelta],
    nuevos: list[RenglonSolicitado],
    tarjeta: Decimal = Decimal(0),
    efectivo_recibido: Decimal = Decimal(0),
) -> tuple[Devolucion, Venta, list[str]]:
    """Cambio de producto: el cliente regresa piezas de una venta y se lleva
    otras. El valor de lo devuelto es saldo a favor en la venta nueva:
    - si lo nuevo cuesta más, el cliente paga la diferencia (efectivo/tarjeta);
    - si cuesta menos, la diferencia se le regresa en efectivo.
    Todo en una operación. No hace commit."""
    venta, turno, motivo = _validar(db, usuario, venta_id, caja_id, motivo)
    if not nuevos:
        raise OperacionInvalida("Indica qué se lleva el cliente; si no se lleva nada, es una devolución")
    piezas = _piezas_solicitadas(venta, devueltas)
    credito = sum((importe for _, _, importe in piezas), Decimal(0))

    # Primero regresan las piezas, por si se lleva el mismo producto de otro lote.
    devolucion = _registrar(db, usuario, venta, turno, TipoDevolucion.CAMBIO, motivo, piezas, credito)
    nueva, avisos = ventas.registrar_venta(
        db, usuario, caja_id, nuevos, tarjeta, efectivo_recibido, saldo_a_favor=devolucion.total,
    )
    diferencia_a_favor = devolucion.total - nueva.total
    if diferencia_a_favor > 0:
        devolucion.efectivo = diferencia_a_favor  # siempre en efectivo
    devolucion.venta_nueva_id = nueva.id
    db.flush()
    return devolucion, nueva, avisos
