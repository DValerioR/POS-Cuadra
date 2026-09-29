"""Imprimir tickets de venta. Un fallo de impresión nunca deshace una venta:
se informa para reimprimir cuando la impresora responda."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.impresion import transporte
from app.impresion.escpos import Ticket
from app.impresion.ticket import DatosTicket, armar_ticket
from app.models import Caja, MetodoPago, Negocio, Usuario, Venta


@dataclass
class ResultadoImpresion:
    impreso: bool
    error: str | None = None


def _datos(db: Session, venta: Venta, caja: Caja) -> DatosTicket:
    negocio = db.get(Negocio, venta.negocio_id)
    cajero = db.get(Usuario, venta.usuario_id)
    return DatosTicket(
        negocio=negocio.nombre,
        encabezado=negocio.ticket_encabezado,
        pie=negocio.ticket_pie,
        caja=db.get(Caja, venta.caja_id).nombre,
        cajero=cajero.nombre_completo,
        columnas=caja.impresora_columnas,
    )


def ticket_de_venta(db: Session, venta: Venta, caja: Caja, abrir_cajon: bool = False, reimpresion: bool = False) -> Ticket:
    return armar_ticket(venta, _datos(db, venta, caja), abrir_cajon=abrir_cajon, reimpresion=reimpresion)


def _mandar(caja: Caja, ticket: Ticket) -> ResultadoImpresion:
    try:
        impreso = transporte.enviar(caja, ticket.bytes())
    except transporte.ErrorImpresion as e:
        return ResultadoImpresion(impreso=False, error=str(e))
    if not impreso:
        return ResultadoImpresion(impreso=False, error=f"La caja '{caja.nombre}' no tiene impresora configurada")
    return ResultadoImpresion(impreso=True)


def imprimir_venta(db: Session, venta: Venta) -> ResultadoImpresion:
    """Al cobrar: imprime en la caja de la venta y abre el cajón si se movió
    efectivo (cobro, o diferencia regresada en un cambio de producto)."""
    caja = db.get(Caja, venta.caja_id)
    hubo_efectivo = any(p.metodo == MetodoPago.EFECTIVO for p in venta.pagos) or (
        venta.cambio_origen is not None and venta.cambio_origen.efectivo > 0
    )
    return _mandar(caja, ticket_de_venta(db, venta, caja, abrir_cajon=hubo_efectivo))


def reimprimir_venta(db: Session, venta: Venta, caja: Caja) -> ResultadoImpresion:
    """Reimpresión: marcada como tal y sin abrir el cajón."""
    return _mandar(caja, ticket_de_venta(db, venta, caja, reimpresion=True))


def imprimir_prueba(caja: Caja, abrir_cajon: bool) -> ResultadoImpresion:
    ticket = Ticket(caja.impresora_columnas)
    ticket.linea("PRUEBA DE IMPRESIÓN", "centro", negrita=True, doble=True)
    ticket.linea(f"Caja: {caja.nombre}", "centro")
    ticket.linea("Acentos: áéíóú ÁÉÍÓÚ ñ Ñ ü ¿¡", "centro")
    ticket.separador()
    ticket.columnas_izq_der("Si ves esto alineado", "$1,234.56")
    ticket.cortar()
    if abrir_cajon:
        ticket.abrir_cajon()
    return _mandar(caja, ticket)
