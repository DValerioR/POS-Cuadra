"""Registro de ventas: precios, desglose de impuestos, descuento de lotes y
cobro. Todo ocurre en una sola transacción: si algo falla (sin precio, pago
insuficiente...) no se guarda nada.

Si el sistema no tiene todas las piezas que se venden, la venta NO se
detiene (físicamente sí las hay; el registro está mal): lo que falta se
descuenta del lote "sin caducidad" del producto, que queda en negativo, y se
crea un aviso para que un administrador cuente y corrija la existencia
(models/aviso_inventario.py).

Concurrencia: al empezar se bloquea el renglón del negocio. Eso da folios
consecutivos sin huecos ni repetidos y hace que las ventas de las dos cajas
se registren una tras otra, así que dos cajas nunca venden la misma pieza
ni se bloquean mutuamente.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AvisoInventario, Lote, MetodoPago, Negocio, Pago, Producto, RolUsuario, Usuario, Venta,
    VentaRenglon, VentaRenglonLote,
)
from app.services import inventario, ofertas_venta, turnos
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso

CENTAVO = Decimal("0.01")
ROLES_VENTA = {RolUsuario.ADMIN, RolUsuario.MOSTRADOR}


@dataclass
class RenglonSolicitado:
    producto_id: int
    cantidad: Decimal
    # Lote que el vendedor entregó (escaneado o elegido). Sin lote = FEFO.
    lote_id: int | None = None
    # Caducidad de la caja en mano, para producto con piezas "sin caducidad".
    caducidad: date | None = None
    numero_lote: str | None = None


def desglosar(importe: Decimal, iva_pct: Decimal, ieps_pct: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Separa un importe con impuestos en (subtotal, ieps, iva). El IEPS se
    calcula sobre el subtotal y el IVA sobre subtotal + IEPS. El IVA se obtiene
    por diferencia para que los tres sumen exactamente el importe."""
    factor = (1 + ieps_pct / 100) * (1 + iva_pct / 100)
    subtotal = (importe / factor).quantize(CENTAVO)
    ieps = (subtotal * ieps_pct / 100).quantize(CENTAVO)
    return subtotal, ieps, importe - subtotal - ieps


def _asignar_lotes(
    db: Session, producto: Producto, cantidad: Decimal, lote_id: int | None,
) -> tuple[list[tuple[Lote, Decimal]], Decimal]:
    """De qué lotes salen las piezas: con lote_id, de ese; si no, FEFO.
    Regresa (asignaciones, faltantes). Las faltantes (las que el sistema no
    tenía) también salen, del lote sin caducidad, que queda en negativo."""
    asignados: list[tuple[Lote, Decimal]] = []
    pendiente = cantidad
    if lote_id is not None:
        lote = db.scalar(select(Lote).where(Lote.id == lote_id, Lote.producto_id == producto.id).with_for_update())
        if lote is None:
            raise NoEncontrado(f"Lote no encontrado para {producto.nombre}")
        tomar = min(max(lote.cantidad, Decimal(0)), pendiente)
        if tomar > 0:
            asignados.append((lote, tomar))
            pendiente -= tomar
    else:
        for lote in inventario.lotes_fefo(db, producto.id, bloquear=True):
            if pendiente == 0:
                break
            tomar = min(lote.cantidad, pendiente)
            asignados.append((lote, tomar))
            pendiente -= tomar

    faltantes = pendiente
    if faltantes > 0:
        sin_caducidad = inventario.lote_sin_caducidad(db, producto, crear=True)
        for i, (lote, tomado) in enumerate(asignados):
            if lote.id == sin_caducidad.id:  # ya se tomaron piezas de ahí: una sola asignación
                asignados[i] = (lote, tomado + faltantes)
                break
        else:
            asignados.append((sin_caducidad, faltantes))
    return asignados, faltantes


def _capturar_en_venta(db: Session, usuario: Usuario, producto: Producto, r: RenglonSolicitado) -> int | None:
    """El vendedor capturó la caducidad de la caja en mano: esas piezas pasan
    del lote sin caducidad a su lote real, y se venden de ahí. Regresa el lote."""
    if not inventario.controla_lote(db, producto):
        raise OperacionInvalida(f"{producto.nombre} no maneja caducidad")
    sin_caducidad = inventario.lote_sin_caducidad(db, producto, crear=False)
    disponibles = sin_caducidad.cantidad if sin_caducidad else Decimal(0)
    if disponibles <= 0:
        return None  # el sistema no tiene esas piezas: se vende igual y se avisa (ver _asignar_lotes)
    lote = inventario.capturar_caducidad(
        db, usuario.negocio_id, usuario.id, producto.id, r.caducidad, min(r.cantidad, disponibles), r.numero_lote,
    )
    return lote.id


def _pagos(total: Decimal, tarjeta: Decimal, efectivo_recibido: Decimal) -> list[Pago]:
    """Lo que no cubre la tarjeta se paga en efectivo (así el pago mixto sale solo)."""
    if tarjeta < 0 or efectivo_recibido < 0:
        raise OperacionInvalida("Los pagos no pueden ser negativos")
    if tarjeta > total:
        raise OperacionInvalida(f"El pago con tarjeta ({tarjeta}) es mayor que el total ({total})")
    efectivo = total - tarjeta
    if efectivo_recibido < efectivo:
        raise OperacionInvalida(f"Faltan {efectivo - efectivo_recibido} por pagar")
    if efectivo == 0 and efectivo_recibido > 0:
        raise OperacionInvalida("El total ya está cubierto; no se necesita efectivo")

    pagos = []
    if tarjeta > 0:
        pagos.append(Pago(metodo=MetodoPago.TARJETA, monto=tarjeta))
    if efectivo > 0:
        pagos.append(Pago(
            metodo=MetodoPago.EFECTIVO, monto=efectivo, recibido=efectivo_recibido, cambio=efectivo_recibido - efectivo,
        ))
    return pagos


def validar_renglon(db: Session, negocio_id: int, r: RenglonSolicitado) -> Producto:
    producto = inventario.obtener_producto(db, negocio_id, r.producto_id)
    if not producto.activo:
        raise OperacionInvalida(f"{producto.nombre} está desactivado")
    if producto.precio_venta is None:
        raise OperacionInvalida(f"{producto.nombre} no tiene precio de venta")
    if r.cantidad <= 0:
        raise OperacionInvalida(f"Cantidad inválida para {producto.nombre}")
    return producto


def cotizar(db: Session, negocio_id: int, renglones: list[RenglonSolicitado]) -> dict:
    """Lo que costaría el carrito con las ofertas de hoy, sin registrar nada.
    Es el mismo cálculo del cobro, para que la pantalla muestre lo que se cobrará."""
    productos = [validar_renglon(db, negocio_id, r) for r in renglones]
    aplicadas = ofertas_venta.calcular(db, negocio_id, [(p, r.cantidad) for p, r in zip(productos, renglones)])
    lista = []
    for r, p, a in zip(renglones, productos, aplicadas):
        bruto = (p.precio_venta * r.cantidad).quantize(CENTAVO)
        lista.append({"producto_id": p.id, "cantidad": r.cantidad, "precio_unitario": p.precio_venta,
                      "descuento": a.descuento, "importe": bruto - a.descuento,
                      "oferta": a.texto if a.descuento else None})
    return {"renglones": lista, "descuento": sum((x["descuento"] for x in lista), Decimal(0)),
            "total": sum((x["importe"] for x in lista), Decimal(0))}


def importe_de_piezas(renglon: VentaRenglon, cantidad: Decimal) -> Decimal:
    """Lo que se cobró por `cantidad` piezas del renglón (con su parte del
    descuento de la oferta), para devolverlas."""
    if not renglon.descuento:
        return (renglon.precio_unitario * cantidad).quantize(CENTAVO)
    return (renglon.importe * cantidad / renglon.cantidad).quantize(CENTAVO)


def registrar_venta(
    db: Session,
    usuario: Usuario,
    caja_id: int,
    renglones: list[RenglonSolicitado],
    tarjeta: Decimal = Decimal(0),
    efectivo_recibido: Decimal = Decimal(0),
    saldo_a_favor: Decimal = Decimal(0),
) -> tuple[Venta, list[str]]:
    """Registra la venta y regresa (venta, avisos). `saldo_a_favor` es el valor
    de piezas devueltas en un cambio de producto: se aplica primero y el resto
    se cobra. No hace commit."""
    if usuario.rol not in ROLES_VENTA:
        raise SinPermiso(f"El rol {usuario.rol.value} no puede vender")
    if not renglones:
        raise OperacionInvalida("La venta no tiene productos")
    caja = turnos.obtener_caja(db, usuario.negocio_id, caja_id)
    turno = turnos.turno_abierto(db, caja.id)
    if turno is None:
        raise OperacionInvalida(f"La caja '{caja.nombre}' no tiene turno abierto")

    # Bloqueo del negocio: serializa las ventas y da el siguiente folio.
    db.scalar(select(Negocio).where(Negocio.id == usuario.negocio_id).with_for_update())
    folio = (db.scalar(select(func.max(Venta.folio)).where(Venta.negocio_id == usuario.negocio_id)) or 0) + 1

    venta = Venta(
        negocio_id=usuario.negocio_id, folio=folio, turno_id=turno.id, caja_id=caja.id, usuario_id=usuario.id,
        subtotal=Decimal(0), ieps=Decimal(0), iva=Decimal(0), total=Decimal(0),
    )
    db.add(venta)
    avisos: list[str] = []
    sin_existencia: list[tuple[Producto, Decimal, Decimal]] = []  # producto, vendidas, faltantes

    productos = [validar_renglon(db, usuario.negocio_id, r) for r in renglones]
    aplicadas = ofertas_venta.calcular(db, usuario.negocio_id, [(p, r.cantidad) for p, r in zip(productos, renglones)])

    for r, producto, oferta in zip(renglones, productos, aplicadas):
        lote_id = r.lote_id
        if r.caducidad is not None and lote_id is None:
            lote_id = _capturar_en_venta(db, usuario, producto, r)

        asignados, faltantes = _asignar_lotes(db, producto, r.cantidad, lote_id)
        for lote, cantidad in asignados:
            lote.cantidad -= cantidad
        db.flush()  # que el siguiente renglón del mismo producto vea lo ya descontado
        if faltantes > 0:
            sin_existencia.append((producto, r.cantidad, faltantes))
            piezas = "1 pieza" if faltantes == 1 else f"{faltantes.normalize():f} piezas"
            avisos.append(f"{producto.nombre}: el sistema no tenía {piezas}; se avisó al administrador para revisarlo")

        importe = (producto.precio_venta * r.cantidad).quantize(CENTAVO) - oferta.descuento
        subtotal, ieps, iva = desglosar(importe, producto.iva_porcentaje, producto.ieps_porcentaje)
        venta.renglones.append(VentaRenglon(
            producto_id=producto.id, nombre=producto.nombre, cantidad=r.cantidad,
            precio_unitario=producto.precio_venta, importe=importe,
            descuento=oferta.descuento, oferta_id=oferta.oferta.id if oferta.oferta and oferta.descuento else None,
            oferta_texto=oferta.texto if oferta.descuento else None,
            iva_porcentaje=producto.iva_porcentaje, ieps_porcentaje=producto.ieps_porcentaje,
            subtotal=subtotal, ieps=ieps, iva=iva,
            lotes=[VentaRenglonLote(lote_id=lote.id, cantidad=cantidad) for lote, cantidad in asignados],
        ))
        if producto.requiere_receta:
            avisos.append(f"{producto.nombre}: requiere receta médica")

    venta.subtotal = sum((x.subtotal for x in venta.renglones), Decimal(0))
    venta.ieps = sum((x.ieps for x in venta.renglones), Decimal(0))
    venta.iva = sum((x.iva for x in venta.renglones), Decimal(0))
    venta.total = sum((x.importe for x in venta.renglones), Decimal(0))
    saldo_aplicado = min(saldo_a_favor, venta.total)
    venta.pagos = ([Pago(metodo=MetodoPago.SALDO_A_FAVOR, monto=saldo_aplicado)] if saldo_aplicado > 0 else []) + _pagos(
        venta.total - saldo_aplicado, tarjeta, efectivo_recibido
    )
    db.flush()
    for producto, vendidas, faltantes in sin_existencia:
        db.add(AvisoInventario(
            negocio_id=venta.negocio_id, producto_id=producto.id, venta_id=venta.id, caja_id=venta.caja_id,
            usuario_id=usuario.id, vendidas=vendidas, faltantes=faltantes,
        ))
    db.flush()
    return venta, avisos


def obtener_venta(db: Session, negocio_id: int, venta_id: int) -> Venta:
    venta = db.get(Venta, venta_id)
    if venta is None or venta.negocio_id != negocio_id:
        raise NoEncontrado("Venta no encontrada")
    return venta

