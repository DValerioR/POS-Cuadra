"""Lectura del XML de una factura electrónica (CFDI 3.3 o 4.0). Es exacta y
no usa IA: los datos vienen estructurados.

Del comprobante se toma el emisor (proveedor y RFC), serie + folio, fecha,
subtotal, descuento y total. De cada concepto: NoIdentificacion (clave del
proveedor, a veces el código de barras), descripción, cantidad, unidad,
valor unitario menos su descuento (costo sin impuestos) y las tasas de IVA e
IEPS. El lote y la caducidad no son campos del CFDI; algunos proveedores los
escriben en la descripción ("LOTE: A123 CAD: 05/2027") y de ahí se intentan
sacar.

Se usa defusedxml porque el archivo lo sube un usuario.
"""

import calendar
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.importador.facturas import FacturaLeida, RenglonLeido

NAMESPACES = ("http://www.sat.gob.mx/cfd/4", "http://www.sat.gob.mx/cfd/3")
IMPUESTO = {"002": "iva", "003": "ieps"}
RE_LOTE = re.compile(r"\bLOTE\s*[:#.]?\s*([A-Z0-9][A-Z0-9\-/]{1,20})", re.IGNORECASE)
RE_CADUCIDAD = re.compile(r"\b(?:CAD(?:UCIDAD)?|EXP|VENCE)\s*[:.]?\s*(\d{1,2})\s*[/\-]\s*(\d{2}|\d{4})\b", re.IGNORECASE)


class XmlInvalido(Exception):
    """No es un CFDI que se pueda leer."""


def _decimal(valor: str | None) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        return Decimal(valor)
    except InvalidOperation:
        return None


def _caducidad(descripcion: str) -> date | None:
    m = RE_CADUCIDAD.search(descripcion)
    if not m:
        return None
    mes, anio = int(m.group(1)), int(m.group(2))
    if anio < 100:
        anio += 2000
    if not 1 <= mes <= 12 or not 2000 <= anio <= 2100:
        return None
    return date(anio, mes, calendar.monthrange(anio, mes)[1])  # las cajas traen mes y año


def _hijo(nodo, nombre: str, ns: str):
    return nodo.find(f"{{{ns}}}{nombre}")


def leer_cfdi(datos: bytes) -> FacturaLeida:
    try:
        raiz = ElementTree.fromstring(datos)
    except (ElementTree.ParseError, DefusedXmlException, ValueError) as e:
        raise XmlInvalido(f"El archivo no es un XML válido ({e})")
    ns = next((n for n in NAMESPACES if raiz.tag == f"{{{n}}}Comprobante"), None)
    if ns is None:
        raise XmlInvalido("El XML no es una factura electrónica (CFDI)")
    if raiz.get("TipoDeComprobante") not in (None, "I"):
        raise XmlInvalido("El XML no es una factura de compra (tipo de comprobante distinto de Ingreso)")

    emisor = _hijo(raiz, "Emisor", ns)
    folio = "-".join(p for p in (raiz.get("Serie"), raiz.get("Folio")) if p) or None
    fecha = None
    if raiz.get("Fecha"):
        try:
            fecha = datetime.fromisoformat(raiz.get("Fecha")).date()
        except ValueError:
            pass
    subtotal = _decimal(raiz.get("SubTotal"))
    descuento = _decimal(raiz.get("Descuento")) or Decimal(0)
    factura = FacturaLeida(
        origen="xml",
        proveedor_nombre=(emisor.get("Nombre") or "").strip() or None if emisor is not None else None,
        proveedor_rfc=(emisor.get("Rfc") or "").strip().upper() or None if emisor is not None else None,
        folio=folio,
        fecha=fecha,
        subtotal=(subtotal - descuento) if subtotal is not None else None,
        total=_decimal(raiz.get("Total")),
    )
    if not folio:
        factura.dudas.append("La factura no trae serie ni folio; escríbelo a mano.")

    conceptos = _hijo(raiz, "Conceptos", ns)
    for c in (conceptos if conceptos is not None else []):
        if c.tag != f"{{{ns}}}Concepto":
            continue
        descripcion = " ".join((c.get("Descripcion") or "").split())
        cantidad = _decimal(c.get("Cantidad"))
        importe = _decimal(c.get("Importe"))
        desc_concepto = _decimal(c.get("Descuento")) or Decimal(0)
        costo = None
        if cantidad and importe is not None:
            costo = ((importe - desc_concepto) / cantidad).quantize(Decimal("0.0001"))
        # IVA: el de los traslados; 0 si el concepto no es objeto de impuesto
        # (ObjetoImp="01"); sin ninguno de los dos, no se sabe (None).
        tasas = {}
        con_impuestos = _hijo(c, "Impuestos", ns) is not None
        for traslado in c.iter(f"{{{ns}}}Traslado"):
            tipo = IMPUESTO.get(traslado.get("Impuesto"))
            tasa = _decimal(traslado.get("TasaOCuota"))
            if tipo and tasa is not None and traslado.get("TipoFactor") != "Exento":
                tasas[tipo] = (tasa * 100).quantize(Decimal("0.01")).normalize()
        lote = RE_LOTE.search(descripcion)
        factura.renglones.append(RenglonLeido(
            descripcion=descripcion,
            clave=(c.get("NoIdentificacion") or "").strip() or None,
            cantidad=cantidad,
            unidad=c.get("Unidad") or c.get("ClaveUnidad"),
            costo_unitario=costo,
            importe=(importe - desc_concepto) if importe is not None else None,
            iva=tasas.get("iva", Decimal(0)) if con_impuestos or c.get("ObjetoImp") == "01" else None,
            ieps=tasas.get("ieps", Decimal(0)) if con_impuestos else None,
            numero_lote=lote.group(1).upper() if lote else None,
            caducidad=_caducidad(descripcion),
        ))
    if not factura.renglones:
        raise XmlInvalido("El XML no trae conceptos (productos)")
    return factura
