"""Los datos de una factura y el PAC que la timbra.

Cada PAC es una clase con el mismo método `timbrar`, que recibe
`FacturaDatos` y regresa `Timbrado`. Se elige con la variable PAC del .env:
"simulado" (de prueba, sin validez) o "facturapi" (con FACTURAPI_KEY).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from xml.sax.saxutils import quoteattr

import httpx
from defusedxml import ElementTree

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
    pac_id: str | None = None  # el identificador de la factura en el PAC (para cancelarla)


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


class PacFacturapi:
    """Timbra con Facturapi (facturapi.io). Facturapi arma y sella el CFDI con
    el CSD que el negocio subió a su panel; aquí solo se mandan los datos.
    Con una clave sk_test_ las facturas son de prueba (sin validez)."""

    URL = "https://www.facturapi.io/v2"

    def __init__(self, clave: str, transport: httpx.BaseTransport | None = None):
        self.clave = clave
        self.de_prueba = clave.startswith("sk_test_")
        self.nombre = "facturapi-pruebas" if self.de_prueba else "facturapi"
        self._transport = transport  # para las pruebas automáticas

    def _cliente(self) -> httpx.Client:
        return httpx.Client(base_url=self.URL, auth=(self.clave, ""), timeout=60.0, transport=self._transport)

    @staticmethod
    def _error(r: httpx.Response) -> OperacionInvalida:
        if r.status_code == 401:
            return OperacionInvalida("Facturapi no aceptó la clave. Revísala en Facturar un ticket → Conexión con Facturapi")
        try:
            mensaje = r.json().get("message") or r.text
        except ValueError:
            mensaje = r.text
        return OperacionInvalida(f"Facturapi rechazó la factura: {mensaje}")

    @staticmethod
    def _cuerpo(f: FacturaDatos) -> dict:
        items = []
        for c in f.conceptos:
            impuestos = [{"type": "IVA", "rate": float(c.iva_tasa)}]
            if c.ieps_tasa:
                # Por omisión Facturapi suma el IEPS a la base del IVA, igual que el ticket.
                impuestos.append({"type": "IEPS", "rate": float(c.ieps_tasa)})
            producto = {
                "description": c.descripcion, "product_key": c.clave_prod_serv, "unit_key": c.clave_unidad,
                "unit_name": "Pieza", "price": float(c.valor_unitario), "tax_included": False,
                "taxability": "02", "taxes": impuestos,
            }
            if c.no_identificacion:
                producto["sku"] = c.no_identificacion
            items.append({"quantity": float(c.cantidad), "product": producto})
        return {
            "customer": {
                "legal_name": f.receptor_nombre, "tax_id": f.receptor_rfc, "tax_system": f.receptor_regimen,
                "address": {"zip": f.receptor_codigo_postal},
            },
            "items": items, "use": f.uso_cfdi, "payment_form": f.forma_pago, "payment_method": f.metodo_pago,
            "series": f.serie, "folio_number": f.folio,
        }

    def timbrar(self, f: FacturaDatos) -> Timbrado:
        try:
            with self._cliente() as http:
                r = http.post("/invoices", json=self._cuerpo(f))
                if r.status_code >= 400:
                    raise self._error(r)
                factura = r.json()
                # Ya está timbrada: si falla la descarga, se reintenta.
                xml = pdf = None
                for _ in range(3):
                    try:
                        if xml is None:
                            rx = http.get(f"/invoices/{factura['id']}/xml")
                            rx.raise_for_status()
                            xml = rx.content.decode("utf-8")
                        if pdf is None:
                            rp = http.get(f"/invoices/{factura['id']}/pdf")
                            rp.raise_for_status()
                            pdf = rp.content
                        break
                    except httpx.HTTPError:
                        continue
        except httpx.HTTPError:
            raise OperacionInvalida("No hay conexión con Facturapi (¿el servidor tiene internet?). La factura no se timbró")
        if xml is None:
            raise OperacionInvalida(f"La factura se timbró en Facturapi (UUID {factura.get('uuid')}) pero no se pudo bajar "
                           "el XML. Búscala en el panel de Facturapi antes de volver a intentar")
        stamp = factura.get("stamp") or {}
        fecha = datetime.fromisoformat(stamp["date"].replace("Z", "+00:00")) if stamp.get("date") else datetime.now()
        return Timbrado(uuid=factura["uuid"], fecha_timbrado=fecha, xml=xml, pdf=pdf, pac_id=factura["id"])

    def probar(self) -> dict:
        """Confirma que la clave sirve (consulta una factura; no timbra nada)."""
        try:
            with self._cliente() as http:
                r = http.get("/invoices", params={"limit": 1})
        except httpx.HTTPError:
            return {"ok": False, "mensaje": "No hay conexión con Facturapi. ¿El servidor tiene internet?"}
        if r.status_code == 401:
            return {"ok": False, "mensaje": "Facturapi no aceptó la clave. Cópiala otra vez desde su panel."}
        if r.status_code >= 400:
            return {"ok": False, "mensaje": f"Facturapi respondió con un error ({r.status_code}). Intenta más tarde."}
        modo = "de pruebas: las facturas NO tienen validez fiscal" if self.de_prueba else "real: las facturas tienen validez fiscal"
        return {"ok": True, "mensaje": f"La clave funciona. Modo {modo}."}


def es_de_prueba(pac: str) -> bool:
    """Si una factura timbrada por ese PAC es de prueba (sin validez fiscal)."""
    return pac in ("simulado", "facturapi-pruebas")


def totales_xml(xml: str) -> dict[str, Decimal]:
    """Subtotal, IVA, IEPS y total como quedaron en el CFDI timbrado (el PAC
    puede redondear algún centavo distinto al ticket)."""
    raiz = ElementTree.fromstring(xml.encode("utf-8"))
    local = lambda n: n.tag.split("}")[-1]  # noqa: E731
    iva = ieps = Decimal(0)
    for hijo in raiz:
        if local(hijo) != "Impuestos":  # solo el resumen del comprobante, no el de cada concepto
            continue
        for t in hijo.iter():
            if local(t) == "Traslado" and t.attrib.get("Importe"):
                if t.attrib.get("Impuesto") == "002":
                    iva += Decimal(t.attrib["Importe"])
                elif t.attrib.get("Impuesto") == "003":
                    ieps += Decimal(t.attrib["Importe"])
    return {"subtotal": Decimal(raiz.attrib["SubTotal"]), "iva": iva, "ieps": ieps, "total": Decimal(raiz.attrib["Total"])}


def obtener_pac():
    """El PAC configurado (variable PAC del .env)."""
    nombre = (settings.pac or "").strip().lower()
    if nombre == "simulado":
        return PacSimulado()
    if nombre == "facturapi":
        if not settings.facturapi_key:
            raise OperacionInvalida("Falta la clave de Facturapi (Facturar un ticket → Conexión con Facturapi)")
        return PacFacturapi(settings.facturapi_key)
    if not nombre:
        raise OperacionInvalida("Todavía no hay un PAC configurado para timbrar facturas")
    raise OperacionInvalida(f"El PAC «{nombre}» no está disponible en este sistema")
