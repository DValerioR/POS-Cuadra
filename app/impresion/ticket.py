"""Arma el ticket de una venta. Solo arma; enviarlo a la impresora es cosa
de impresion/transporte.py."""

from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.impresion.escpos import Ticket
from app.models import EstadoVenta, MetodoPago, Venta


@dataclass
class DatosTicket:
    """Lo que el ticket necesita además de la venta."""

    negocio: str
    encabezado: str | None  # dirección, teléfono, RFC... (varias líneas)
    pie: str | None  # "Gracias por su compra", políticas...
    caja: str
    cajero: str
    columnas: int = 48
    logo: tuple[int, int, bytes] | None = None  # ver impresion/logo.py


def _dinero(valor: Decimal) -> str:
    return f"${valor:,.2f}"


def _cantidad(valor: Decimal) -> str:
    """2.00 -> "2", 1.50 -> "1.5"."""
    return f"{valor.normalize():f}"


def armar_ticket(venta: Venta, datos: DatosTicket, abrir_cajon: bool = False, reimpresion: bool = False) -> Ticket:
    t = Ticket(datos.columnas)
    fecha = venta.created_at.astimezone(ZoneInfo(settings.zona_horaria))

    if datos.logo:
        t.imagen(*datos.logo)
    t.linea(datos.negocio, "centro", negrita=True)
    for renglon in (datos.encabezado or "").splitlines():
        t.linea(renglon.strip(), "centro")
    t.separador()
    t.columnas_izq_der(f"Folio: {venta.folio}", fecha.strftime("%d/%m/%Y %H:%M"))
    t.izq_der_o_dos_renglones(f"Caja: {datos.caja}", f"Atendió: {datos.cajero}")
    if reimpresion:
        t.linea("REIMPRESIÓN", "centro", negrita=True)
    if venta.cambio_origen is not None:
        t.linea(f"CAMBIO DE PRODUCTO (folio {venta.cambio_origen.venta.folio})", "centro", negrita=True)
    t.separador()

    for r in venta.renglones:
        if r.cantidad == 1:  # una pieza: nombre e importe en el mismo renglón
            t.columnas_izq_der(r.nombre, _dinero(r.importe + r.descuento))
        else:
            t.linea(r.nombre)
            t.columnas_izq_der(f"  {_cantidad(r.cantidad)} x {_dinero(r.precio_unitario)}", _dinero(r.importe + r.descuento))
        if r.descuento:
            t.columnas_izq_der(f"  {r.oferta_texto or 'Oferta'}", f"-{_dinero(r.descuento)}")
        for asignacion in r.lotes:
            lote = asignacion.lote
            if lote.caducidad is None and lote.numero_lote is None:
                continue  # piezas heredadas sin datos de lote
            partes = []
            if lote.numero_lote:
                partes.append(f"Lote {lote.numero_lote}")
            if lote.caducidad:
                partes.append(f"Cad {lote.caducidad:%m/%Y}")
            if len(r.lotes) > 1:
                partes.append(f"({_cantidad(asignacion.cantidad)})")
            t.linea("  " + "  ".join(partes))
    t.separador()

    impuestos = ([f"IEPS {_dinero(venta.ieps)}"] if venta.ieps else []) + [f"IVA {_dinero(venta.iva)}"]
    t.izq_der_o_dos_renglones(f"Subtotal {_dinero(venta.subtotal)}", "  ".join(impuestos))
    t.columnas_izq_der("TOTAL", _dinero(venta.total), negrita=True)
    ahorro = sum((r.descuento for r in venta.renglones), Decimal(0))
    if ahorro:
        t.columnas_izq_der("Usted ahorró", _dinero(ahorro), negrita=True)

    for pago in venta.pagos:
        if pago.metodo == MetodoPago.EFECTIVO:
            t.izq_der_o_dos_renglones(f"Efectivo {_dinero(pago.recibido)}", f"Cambio {_dinero(pago.cambio)}")
        elif pago.metodo == MetodoPago.SALDO_A_FAVOR:
            t.columnas_izq_der("Saldo por producto devuelto", _dinero(pago.monto))
        else:
            t.columnas_izq_der(pago.metodo.value.capitalize(), _dinero(pago.monto))

    if venta.cambio_origen is not None and venta.cambio_origen.efectivo > 0:
        t.columnas_izq_der("Diferencia a su favor", _dinero(venta.cambio_origen.efectivo), negrita=True)

    if venta.estado == EstadoVenta.CANCELADA:
        t.separador()
        t.linea("*** VENTA CANCELADA ***", "centro", negrita=True)

    if datos.pie:
        t.separador()
        for renglon in datos.pie.splitlines():
            t.linea(renglon.strip(), "centro")

    t.cortar()
    if abrir_cajon:
        t.abrir_cajon()
    return t
