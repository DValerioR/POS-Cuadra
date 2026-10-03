"""Los datos de una factura y el PAC que la timbra.

Cada PAC es una clase con los mismos métodos: `timbrar`, que recibe
`FacturaDatos` y regresa `Timbrado`; `recuperar`, que busca en el PAC una
factura que quizá ya se timbró (misma serie y folio) y la regresa, o None si
no está; `cancelar`, que pide al SAT cancelar una factura, y
`estado_cancelacion`, que revisa cómo va una cancelación que espera al cliente. Se elige con la variable PAC del .env: "simulado" (de prueba, sin
validez) o "facturapi" (con FACTURAPI_KEY).

`timbrar` lanza OperacionInvalida cuando es seguro que NO se timbró (el PAC
la rechazó o ni siquiera hubo conexión) y TimbradoIncierto cuando no se sabe
(se cortó la conexión con la petición ya enviada, el PAC falló por dentro o
se timbró y no se pudo bajar el XML). Ver services/facturacion.py.
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
    clave_unidad: str  # H87 pieza; ACT actividad (los tickets de la factura global)
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
    # Factura global (InformacionGlobal): periodicidad 01-05, meses 01-18, año.
    global_periodicidad: str | None = None
    global_meses: str | None = None
    global_anio: int | None = None


# Periodicidad de la factura global: clave del SAT -> nombre en Facturapi.
PERIODICIDAD_FACTURAPI = {"01": "day", "02": "week", "03": "fortnight", "04": "month", "05": "two_months"}


@dataclass
class Cancelacion:
    """Cómo quedó una solicitud de cancelación."""
    estado: str  # "cancelada", "pendiente" (espera al cliente), "rechazada" (sigue vigente)
    mensaje: str | None = None


class TimbradoIncierto(Exception):
    """No se sabe si el PAC timbró la factura. `pac_id` va si el PAC alcanzó
    a contestar (entonces sí se timbró y solo falta bajarla)."""

    def __init__(self, mensaje: str, pac_id: str | None = None):
        super().__init__(mensaje)
        self.pac_id = pac_id


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

    def recuperar(self, f: FacturaDatos, pac_id: str | None = None) -> Timbrado | None:
        return None  # el simulado nunca se queda a medias

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
                f'ClaveUnidad={a(c.clave_unidad)} Unidad={a("PZA" if c.clave_unidad == "H87" else "Actividad")} '
                f'Descripcion={a(c.descripcion)} '
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
            + (f'<cfdi:InformacionGlobal Periodicidad={a(f.global_periodicidad)} Meses={a(f.global_meses)} '
               f'Año={a(f.global_anio)}/>' if f.global_periodicidad else "")
            + f'<cfdi:Emisor Rfc={a(f.emisor_rfc)} Nombre={a(f.emisor_nombre)} RegimenFiscal={a(f.emisor_regimen)}/>'
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

    def cancelar(self, pac_id: str | None, uuid_factura: str, motivo: str) -> Cancelacion:
        return Cancelacion("cancelada")

    def estado_cancelacion(self, pac_id: str | None, uuid_factura: str) -> Cancelacion:
        return Cancelacion("cancelada")


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
                "unit_name": "Pieza" if c.clave_unidad == "H87" else "Actividad",
                "price": float(c.valor_unitario), "tax_included": False,
                "taxability": "02", "taxes": impuestos,
            }
            if c.no_identificacion:
                producto["sku"] = c.no_identificacion
            items.append({"quantity": float(c.cantidad), "product": producto})
        cuerpo = {
            "customer": {
                "legal_name": f.receptor_nombre, "tax_id": f.receptor_rfc, "tax_system": f.receptor_regimen,
                "address": {"zip": f.receptor_codigo_postal},
            },
            "items": items, "use": f.uso_cfdi, "payment_form": f.forma_pago, "payment_method": f.metodo_pago,
            "series": f.serie, "folio_number": f.folio,
        }
        if f.global_periodicidad:
            cuerpo["global"] = {"periodicity": PERIODICIDAD_FACTURAPI[f.global_periodicidad],
                                "months": f.global_meses, "year": f.global_anio}
        return cuerpo

    def timbrar(self, f: FacturaDatos) -> Timbrado:
        with self._cliente() as http:
            try:
                r = http.post("/invoices", json=self._cuerpo(f))
            except (httpx.ConnectError, httpx.ConnectTimeout):
                # No llegó a salir: seguro que no se timbró.
                raise OperacionInvalida("No hay conexión con Facturapi (¿el servidor tiene internet?). La factura no se timbró")
            except httpx.HTTPError:
                raise TimbradoIncierto("Se cortó la conexión con Facturapi mientras timbraba")
            if r.status_code >= 500:
                raise TimbradoIncierto(f"Facturapi tuvo un problema por dentro ({r.status_code}) mientras timbraba")
            if r.status_code >= 400:
                raise self._error(r)
            return self._descargar(http, r.json())

    @staticmethod
    def _descargar(http: httpx.Client, factura: dict) -> Timbrado:
        """XML y PDF de una factura ya timbrada (con reintentos)."""
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
        if xml is None:
            raise TimbradoIncierto(f"La factura se timbró en Facturapi (UUID {factura.get('uuid')}) pero no se pudo "
                                   "bajar el XML", pac_id=factura["id"])
        stamp = factura.get("stamp") or {}
        fecha = datetime.fromisoformat(stamp["date"].replace("Z", "+00:00")) if stamp.get("date") else datetime.now()
        return Timbrado(uuid=factura["uuid"], fecha_timbrado=fecha, xml=xml, pdf=pdf, pac_id=factura["id"])

    def recuperar(self, f: FacturaDatos, pac_id: str | None = None) -> Timbrado | None:
        """La factura ya timbrada en Facturapi, o None si no está. Sin pac_id
        se busca entre las del cliente (por RFC) la de la misma serie y folio
        que no esté cancelada. Si no se puede consultar, TimbradoIncierto:
        sin saberlo no se vuelve a timbrar."""
        try:
            with self._cliente() as http:
                if pac_id:
                    r = http.get(f"/invoices/{pac_id}")
                    if r.status_code == 404:
                        return None
                    r.raise_for_status()
                    return self._descargar(http, r.json())
                r = http.get("/invoices", params={"q": f.receptor_rfc, "limit": 50})
                r.raise_for_status()
                for factura in r.json().get("data", []):
                    if (str(factura.get("series") or "") == f.serie and str(factura.get("folio_number")) == str(f.folio)
                            and factura.get("status") != "canceled"):
                        return self._descargar(http, factura)
                return None
        except httpx.HTTPError:
            raise TimbradoIncierto("No se pudo consultar Facturapi para revisar si la factura ya estaba timbrada", pac_id)

    @staticmethod
    def _cancelacion(factura: dict) -> Cancelacion:
        """El estado de cancelación según la factura de Facturapi."""
        if factura.get("status") == "canceled":
            return Cancelacion("cancelada")
        estado = factura.get("cancellation_status")
        if estado == "pending":
            return Cancelacion("pendiente", "El cliente debe aceptar la cancelación en el portal del SAT (tiene 72 horas)")
        if estado == "rejected":
            return Cancelacion("rechazada", "El cliente rechazó la cancelación: la factura sigue vigente")
        if estado == "expired":
            return Cancelacion("rechazada", "La solicitud de cancelación venció: la factura sigue vigente")
        return Cancelacion("rechazada", "Facturapi no canceló la factura: sigue vigente")

    def cancelar(self, pac_id: str | None, uuid_factura: str, motivo: str) -> Cancelacion:
        if not pac_id:
            raise OperacionInvalida("Esta factura no tiene identificador de Facturapi; cancélala desde su panel")
        try:
            with self._cliente() as http:
                r = http.delete(f"/invoices/{pac_id}", params={"motive": motivo})
        except httpx.HTTPError:
            raise OperacionInvalida("No hubo conexión con Facturapi. La cancelación no se pidió; intenta de nuevo")
        if r.status_code >= 400:
            if r.status_code == 401:
                raise self._error(r)
            try:
                mensaje = r.json().get("message") or r.text
            except ValueError:
                mensaje = r.text
            raise OperacionInvalida(f"Facturapi no pudo cancelar la factura: {mensaje}")
        return self._cancelacion(r.json())

    def estado_cancelacion(self, pac_id: str | None, uuid_factura: str) -> Cancelacion:
        if not pac_id:
            raise OperacionInvalida("Esta factura no tiene identificador de Facturapi; revísala en su panel")
        try:
            with self._cliente() as http:
                r = http.get(f"/invoices/{pac_id}")
                r.raise_for_status()
        except httpx.HTTPError:
            raise OperacionInvalida("No se pudo consultar Facturapi. Intenta más tarde")
        return self._cancelacion(r.json())

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
