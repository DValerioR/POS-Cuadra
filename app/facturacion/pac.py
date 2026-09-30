"""Los datos de una factura y el PAC que la timbra.

Cada PAC real (Facturapi, Facturama, el de PVWin...) será una clase con el
mismo método `timbrar`, que recibe `FacturaDatos` y regresa `Timbrado`. Se
elige con la variable PAC del .env; hoy solo existe "simulado".
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from xml.sax.saxutils import quoteattr

from app.core.config import settings
from app.services.errores import OperacionInvalida


@dataclass
class Concepto:
    clave_prod_serv: str
    clave_unidad: str
    cantidad: Decimal
    descripcion: str
    valor_unitario: Decimal  # sin impuestos, hasta 6 decimales
    importe: Decimal  # cantidad × valor unitario, sin impuestos
    no_identificacion: str | None = None  # la clave / código de barras del producto
    iva_tasa: Decimal = Decimal(0)  # 0.16 o 0
    iva: Decimal = Decimal(0)
    ieps_tasa: Decimal = Decimal(0)
    ieps: Decimal = Decimal(0)


@dataclass
class FacturaDatos:
    serie: str
    folio: int
    fecha: datetime
    lugar_expedicion: str  # código postal del emisor
    forma_pago: str
    metodo_pago: str
    emisor_rfc: str
    emisor_nombre: str
    emisor_regimen: str
    receptor_rfc: str
    receptor_nombre: str
    receptor_codigo_postal: str
    receptor_regimen: str
    uso_cfdi: str
    conceptos: list[Concepto] = field(default_factory=list)
    subtotal: Decimal = Decimal(0)
    iva: Decimal = Decimal(0)
    ieps: Decimal = Decimal(0)
    total: Decimal = Decimal(0)


@dataclass
class Timbrado:
    uuid: str
    fecha_timbrado: datetime
    xml: str
    pdf: bytes | None = None  # los PAC reales suelen regresar su PDF


class PacSimulado:
    """Para desarrollo y pruebas: arma un XML con la forma de un CFDI 4.0,
    sin sello y con un timbre falso. NO tiene validez fiscal."""

    nombre = "simulado"

    def timbrar(self, f: FacturaDatos) -> Timbrado:
        folio_fiscal = str(uuid.uuid4()).upper()
        ahora = datetime.now().replace(microsecond=0)
        a = lambda v: quoteattr(str(v))  # noqa: E731
        conceptos = []
        for c in f.conceptos:
            traslados = []
            if c.ieps_tasa:
                traslados.append(f'<cfdi:Traslado Base={a(f"{c.importe:.2f}")} Impuesto="003" TipoFactor="Tasa" '
                                 f'TasaOCuota={a(f"{c.ieps_tasa:.6f}")} Importe={a(f"{c.ieps:.2f}")}/>')
            base_iva = c.importe + c.ieps
            traslados.append(f'<cfdi:Traslado Base={a(f"{base_iva:.2f}")} Impuesto="002" TipoFactor="Tasa" '
                             f'TasaOCuota={a(f"{c.iva_tasa:.6f}")} Importe={a(f"{c.iva:.2f}")}/>')
            ident = f" NoIdentificacion={a(c.no_identificacion)}" if c.no_identificacion else ""
            conceptos.append(
                f'<cfdi:Concepto ClaveProdServ={a(c.clave_prod_serv)}{ident} Cantidad={a(f"{c.cantidad:f}")} '
                f'ClaveUnidad={a(c.clave_unidad)} Unidad="PZA" Descripcion={a(c.descripcion)} '
                f'ValorUnitario={a(f"{c.valor_unitario:.6f}")} Importe={a(f"{c.importe:.2f}")} ObjetoImp="02">'
                f'<cfdi:Impuestos><cfdi:Traslados>{"".join(traslados)}</cfdi:Traslados></cfdi:Impuestos></cfdi:Concepto>'
            )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" '
            f'Version="4.0" Serie={a(f.serie)} Folio={a(f.folio)} Fecha={a(f.fecha.strftime("%Y-%m-%dT%H:%M:%S"))} '
            f'FormaPago={a(f.forma_pago)} MetodoPago={a(f.metodo_pago)} SubTotal={a(f"{f.subtotal:.2f}")} Moneda="MXN" '
            f'Total={a(f"{f.total:.2f}")} TipoDeComprobante="I" Exportacion="01" LugarExpedicion={a(f.lugar_expedicion)} '
            'Sello="PRUEBA-SIN-VALIDEZ-FISCAL" NoCertificado="00000000000000000000" Certificado="">'
            f'<cfdi:Emisor Rfc={a(f.emisor_rfc)} Nombre={a(f.emisor_nombre)} RegimenFiscal={a(f.emisor_regimen)}/>'
            f'<cfdi:Receptor Rfc={a(f.receptor_rfc)} Nombre={a(f.receptor_nombre)} '
            f'DomicilioFiscalReceptor={a(f.receptor_codigo_postal)} RegimenFiscalReceptor={a(f.receptor_regimen)} '
            f'UsoCFDI={a(f.uso_cfdi)}/>'
            f'<cfdi:Conceptos>{"".join(conceptos)}</cfdi:Conceptos>'
            f'<cfdi:Complemento><tfd:TimbreFiscalDigital Version="1.1" UUID={a(folio_fiscal)} '
            f'FechaTimbrado={a(ahora.strftime("%Y-%m-%dT%H:%M:%S"))} RfcProvCertif="SIMULADO" '
            'SelloCFD="PRUEBA" NoCertificadoSAT="00000000000000000000" SelloSAT="PRUEBA"/></cfdi:Complemento>'
            '</cfdi:Comprobante>'
        )
        return Timbrado(uuid=folio_fiscal, fecha_timbrado=ahora, xml=xml)


def obtener_pac():
    """El PAC configurado (variable PAC del .env)."""
    nombre = (settings.pac or "").strip().lower()
    if nombre == "simulado":
        return PacSimulado()
    if not nombre:
        raise OperacionInvalida("Todavía no hay un PAC configurado para timbrar facturas")
    raise OperacionInvalida(f"El PAC «{nombre}» no está disponible en este sistema")
