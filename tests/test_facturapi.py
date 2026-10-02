"""Timbrar con Facturapi (con su API simulada aquí) y la conexión desde el
programa: la clave se guarda en un .env temporal y solo la maneja un administrador."""

import json

import httpx
import pytest

from app.core import config
from app.core.config import settings
from app.facturacion import pac as pac_mod
from tests.test_facturacion import facturar, fiscal  # noqa: F401  (fixture)
from tests.test_ventas import caja, r, shampoo, vender  # noqa: F401  (fixtures)

CLAVE_PRUEBAS = "sk_test_" + "a" * 30 + "WXYZ"
CLAVE_REAL = "sk_live_" + "b" * 30 + "1234"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
 Version="4.0" Serie="C" Folio="1" Fecha="2026-10-01T10:00:00" SubTotal="200.00" Total="232.01" LugarExpedicion="46470">
 <cfdi:Emisor Rfc="VABZ611024RW3" Nombre="ZAIDA VALERIO BARRANTES" RegimenFiscal="612"/>
 <cfdi:Conceptos><cfdi:Concepto ClaveProdServ="01010101" Cantidad="2" ClaveUnidad="H87" Descripcion="SHAMPOO 400ML"
  ValorUnitario="100.000000" Importe="200.00"><cfdi:Impuestos><cfdi:Traslados>
  <cfdi:Traslado Base="200.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="32.01"/>
 </cfdi:Traslados></cfdi:Impuestos></cfdi:Concepto></cfdi:Conceptos>
 <cfdi:Impuestos TotalImpuestosTrasladados="32.01"><cfdi:Traslados>
  <cfdi:Traslado Base="200.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="32.01"/>
 </cfdi:Traslados></cfdi:Impuestos>
 <cfdi:Complemento><tfd:TimbreFiscalDigital Version="1.1" UUID="11111111-2222-3333-4444-555555555555"
  FechaTimbrado="2026-10-01T10:00:05" RfcProvCertif="AAA010101AAA" SelloSAT="abc" NoCertificadoSAT="300"/></cfdi:Complemento>
</cfdi:Comprobante>"""


class FacturapiFalso:
    """Responde como la API de Facturapi y guarda lo que se le mandó."""

    FACTURA = {"id": "inv_123", "uuid": "11111111-2222-3333-4444-555555555555", "total": 232.01,
               "series": "C", "folio_number": 1, "status": "valid", "stamp": {"date": "2026-10-01T16:00:05.000Z"}}

    def __init__(self, timbrar=None):
        self.pedidos = []
        self.timbrar = timbrar  # httpx.Response para POST /invoices, o una excepción
        self.lista = []  # lo que regresa la búsqueda GET /invoices
        self.xml_falla = False  # el XML no se puede bajar
        self.consulta_falla = False  # GET /invoices y /invoices/{id} sin conexión

    @property
    def posts(self):
        return [p for p in self.pedidos if p.method == "POST"]

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        ruta = pedido.url.path
        if pedido.method == "POST" and ruta == "/v2/invoices":
            if isinstance(self.timbrar, Exception):
                raise self.timbrar
            return self.timbrar or httpx.Response(200, json=self.FACTURA)
        if ruta == "/v2/invoices/inv_123/xml":
            if self.xml_falla:
                return httpx.Response(500, json={"message": "error"})
            return httpx.Response(200, content=XML.encode("utf-8"))
        if ruta == "/v2/invoices/inv_123/pdf":
            return httpx.Response(200, content=b"%PDF-1.4 falso")
        if self.consulta_falla and ruta.startswith("/v2/invoices"):
            raise httpx.ConnectError("sin red")
        if pedido.method == "GET" and ruta == "/v2/invoices/inv_123":
            return httpx.Response(200, json=self.FACTURA)
        if pedido.method == "GET" and ruta == "/v2/invoices":
            return httpx.Response(200, json={"data": self.lista, "page": 1})
        return httpx.Response(404, json={"message": "no existe"})


@pytest.fixture(autouse=True)
def env_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / ".env"
    ruta.write_text("DATABASE_URL=postgresql+psycopg://x\nPAC=simulado\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_PATH", ruta)
    monkeypatch.setattr(settings, "pac", "simulado")
    monkeypatch.setattr(settings, "facturapi_key", None)
    return ruta


@pytest.fixture
def facturapi(monkeypatch):
    falso = FacturapiFalso()
    original = pac_mod.PacFacturapi._cliente

    def cliente(self):
        self._transport = httpx.MockTransport(falso)
        return original(self)

    monkeypatch.setattr(pac_mod.PacFacturapi, "_cliente", cliente)
    monkeypatch.setattr(settings, "pac", "facturapi")
    monkeypatch.setattr(settings, "facturapi_key", CLAVE_PRUEBAS)
    return falso


def test_timbrar_con_facturapi(como_admin, fiscal, facturapi, caja, shampoo):  # noqa: F811
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    resp = facturar(como_admin, v["folio"])
    assert resp.status_code == 201, resp.text
    f = resp.json()
    # Se guarda lo timbrado, aunque el PAC haya redondeado un centavo distinto al ticket.
    assert (f["uuid"], f["total"], f["pac"], f["de_prueba"]) == ("11111111-2222-3333-4444-555555555555", "232.01",
                                                                 "facturapi-pruebas", True)

    post = facturapi.pedidos[0]
    assert post.headers["authorization"] == httpx.BasicAuth(CLAVE_PRUEBAS, "")._auth_header
    cuerpo = json.loads(post.content)
    assert cuerpo["customer"] == {"legal_name": "JOSÉ ÁNGEL CARO RINCÓN", "tax_id": "CARA620802A15",
                                  "tax_system": "612", "address": {"zip": "46470"}}
    assert (cuerpo["use"], cuerpo["payment_form"], cuerpo["payment_method"], cuerpo["series"], cuerpo["folio_number"]) == \
        ("G03", "01", "PUE", "C", 1)
    item = cuerpo["items"][0]
    assert item["quantity"] == 2 and item["product"]["price"] == 100.0 and item["product"]["tax_included"] is False
    assert item["product"]["taxes"] == [{"type": "IVA", "rate": 0.16}]

    d = como_admin.get(f"/cfdi/{f['id']}").json()
    assert (d["iva"], d["subtotal"], d["rfc_prov_certif"], d["tiene_pdf"]) == ("32.01", "200.00", "AAA010101AAA", True)
    assert como_admin.get(f"/cfdi/{f['id']}/pdf").content == b"%PDF-1.4 falso"


def test_con_clave_real_no_es_de_prueba(como_admin, fiscal, facturapi, caja, shampoo, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "facturapi_key", CLAVE_REAL)
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    f = facturar(como_admin, v["folio"]).json()
    assert (f["pac"], f["de_prueba"]) == ("facturapi", False)


@pytest.mark.parametrize("respuesta, texto", [
    (httpx.Response(400, json={"message": "El RFC del receptor no está en la lista del SAT"}), "lista del SAT"),
    (httpx.Response(401, json={"message": "Unauthorized"}), "no aceptó la clave"),
    (httpx.ConnectError("sin red"), "No hay conexión"),
])
def test_si_facturapi_falla_no_se_guarda(como_admin, fiscal, facturapi, caja, shampoo, respuesta, texto):  # noqa: F811
    facturapi.timbrar = respuesta
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()
    resp = facturar(como_admin, v["folio"])
    assert resp.status_code in (400, 409, 422) and texto in resp.json()["detail"], resp.text
    assert como_admin.get("/cfdi").json() == []
    assert como_admin.get(f"/cfdi/ticket/{v['folio']}").json()["puede_facturar"] is True


def test_guardar_probar_y_quitar_la_clave(como_admin, facturapi, env_temporal, monkeypatch):
    monkeypatch.setattr(settings, "pac", "simulado")
    monkeypatch.setattr(settings, "facturapi_key", None)
    assert como_admin.get("/cfdi/conexion").json()["configurada"] is False

    r1 = como_admin.put("/cfdi/conexion/clave", json={"clave": f"  {CLAVE_PRUEBAS} "})
    assert r1.json() == {"pac": "facturapi", "configurada": True, "termina_en": "WXYZ", "de_prueba": True}
    assert CLAVE_PRUEBAS not in r1.text
    env = env_temporal.read_text(encoding="utf-8").splitlines()
    assert f"FACTURAPI_KEY={CLAVE_PRUEBAS}" in env and "PAC=facturapi" in env and env.count("PAC=simulado") == 0
    assert como_admin.post("/cfdi/conexion/probar").json()["ok"] is True
    assert como_admin.get("/cfdi/catalogos").json()["de_prueba"] is True

    como_admin.put("/cfdi/conexion/clave", json={"clave": CLAVE_REAL})
    assert como_admin.get("/cfdi/catalogos").json()["de_prueba"] is False
    assert env_temporal.read_text(encoding="utf-8").count("FACTURAPI_KEY") == 1

    assert como_admin.delete("/cfdi/conexion/clave").json()["configurada"] is False
    env = env_temporal.read_text(encoding="utf-8")
    assert "FACTURAPI_KEY" not in env and "PAC=simulado" in env and settings.pac == "simulado"


@pytest.mark.parametrize("clave", ["sk-ant-123", "sk_test_corta", f"{CLAVE_PRUEBAS}\nPAC=otro", "pk_test_" + "a" * 30])
def test_clave_invalida(como_admin, clave, env_temporal):
    resp = como_admin.put("/cfdi/conexion/clave", json={"clave": clave})
    assert resp.status_code in (400, 409, 422)
    assert "FACTURAPI_KEY" not in env_temporal.read_text(encoding="utf-8")


def test_solo_admin_maneja_la_clave(como_mostrador):
    assert como_mostrador.get("/cfdi/conexion").status_code == 403
    assert como_mostrador.put("/cfdi/conexion/clave", json={"clave": CLAVE_PRUEBAS}).status_code == 403


# --- Si no se sabe si quedó timbrada: reintentar sin duplicar -----------------------

def _pendientes(cliente):
    return cliente.get("/cfdi/pendientes").json()


@pytest.mark.parametrize("falla", [httpx.ReadTimeout("se cortó"), httpx.Response(502, json={"message": "Bad gateway"})])
def test_corte_a_la_mitad_queda_pendiente(como_admin, fiscal, facturapi, caja, shampoo, falla):  # noqa: F811
    facturapi.timbrar = falla
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    resp = facturar(como_admin, v["folio"])
    assert resp.status_code == 409 and "Reintentar" in resp.json()["detail"]
    [p] = _pendientes(como_admin)
    assert (p["serie"], p["folio"], p["folio_ticket"], p["receptor_rfc"]) == ("C", 1, v["folio"], "CARA620802A15")
    t = como_admin.get(f"/cfdi/ticket/{v['folio']}").json()
    assert t["puede_facturar"] is False and t["pendiente"]["id"] == p["id"]
    # No deja volver a timbrar desde el formulario: eso podría duplicarla.
    assert facturar(como_admin, v["folio"]).status_code == 409
    assert len(facturapi.posts) == 1


def test_reintentar_encuentra_la_que_si_se_timbro(como_admin, fiscal, facturapi, caja, shampoo):  # noqa: F811
    facturapi.timbrar = httpx.ReadTimeout("se cortó")
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    facturar(como_admin, v["folio"])
    [p] = _pendientes(como_admin)
    facturapi.lista = [{**facturapi.FACTURA, "folio_number": 7}, facturapi.FACTURA]  # la buena es la C-1
    resp = como_admin.post(f"/cfdi/pendientes/{p['id']}/reintentar")
    assert resp.status_code == 201, resp.text
    f = resp.json()
    assert (f["serie"], f["folio"], f["uuid"], f["folio_ticket"]) == ("C", 1, "11111111-2222-3333-4444-555555555555", v["folio"])
    assert len(facturapi.posts) == 1  # no se volvió a timbrar
    busqueda = next(x for x in facturapi.pedidos if x.method == "GET" and x.url.path == "/v2/invoices")
    assert busqueda.url.params["q"] == "CARA620802A15"
    assert _pendientes(como_admin) == []
    assert como_admin.get(f"/cfdi/ticket/{v['folio']}").json()["puede_facturar"] is False  # ya facturado


def test_reintentar_timbra_si_no_estaba(como_admin, fiscal, facturapi, caja, shampoo):  # noqa: F811
    facturapi.timbrar = httpx.ReadTimeout("se cortó")
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    facturar(como_admin, v["folio"])
    [p] = _pendientes(como_admin)
    facturapi.lista = [{**facturapi.FACTURA, "status": "canceled"}]  # cancelada no cuenta
    facturapi.timbrar = None
    resp = como_admin.post(f"/cfdi/pendientes/{p['id']}/reintentar")
    assert resp.status_code == 201 and resp.json()["folio"] == 1
    assert len(facturapi.posts) == 2
    assert json.loads(facturapi.posts[1].content)["folio_number"] == 1  # mismo folio


def test_timbrada_sin_xml_se_baja_al_reintentar(como_admin, fiscal, facturapi, caja, shampoo):  # noqa: F811
    facturapi.xml_falla = True
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    resp = facturar(como_admin, v["folio"])
    assert resp.status_code == 409 and "no se pudo bajar el XML" in resp.json()["detail"]
    [p] = _pendientes(como_admin)
    facturapi.xml_falla = False
    assert como_admin.post(f"/cfdi/pendientes/{p['id']}/reintentar").status_code == 201
    assert any(x.url.path == "/v2/invoices/inv_123" for x in facturapi.pedidos)  # la buscó por su id
    assert len(facturapi.posts) == 1


def test_sin_conexion_para_revisar_sigue_pendiente(como_admin, fiscal, facturapi, caja, shampoo):  # noqa: F811
    facturapi.timbrar = httpx.ReadTimeout("se cortó")
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    facturar(como_admin, v["folio"])
    [p] = _pendientes(como_admin)
    facturapi.consulta_falla = True
    resp = como_admin.post(f"/cfdi/pendientes/{p['id']}/reintentar")
    assert resp.status_code == 409 and "No se pudo consultar Facturapi" in resp.json()["detail"]
    [p2] = _pendientes(como_admin)
    assert p2["intentos"] == 2 and len(facturapi.posts) == 1
    assert como_admin.delete(f"/cfdi/pendientes/{p['id']}").status_code == 409  # tampoco se descarta a ciegas


def test_descartar_solo_si_no_se_timbro(como_admin, fiscal, facturapi, caja, shampoo):  # noqa: F811
    facturapi.timbrar = httpx.ReadTimeout("se cortó")
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    facturar(como_admin, v["folio"])
    [p] = _pendientes(como_admin)
    facturapi.lista = [facturapi.FACTURA]
    resp = como_admin.delete(f"/cfdi/pendientes/{p['id']}")
    assert resp.status_code == 409 and "sí quedó timbrada" in resp.json()["detail"]
    facturapi.lista = []
    assert como_admin.delete(f"/cfdi/pendientes/{p['id']}").status_code == 204
    assert _pendientes(como_admin) == []
    assert como_admin.get(f"/cfdi/ticket/{v['folio']}").json()["puede_facturar"] is True


def test_el_folio_pendiente_no_se_reusa(como_admin, fiscal, facturapi, caja, shampoo):  # noqa: F811
    facturapi.timbrar = httpx.ReadTimeout("se cortó")
    v1 = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    v2 = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    facturar(como_admin, v1["folio"])
    facturapi.timbrar = None
    facturar(como_admin, v2["folio"])
    assert json.loads(facturapi.posts[1].content)["folio_number"] == 2


def test_rechazo_claro_no_deja_pendiente(como_admin, fiscal, facturapi, caja, shampoo):  # noqa: F811
    facturapi.timbrar = httpx.Response(400, json={"message": "El RFC del receptor no está en la lista del SAT"})
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()
    assert facturar(como_admin, v["folio"]).status_code == 409
    assert _pendientes(como_admin) == []


def test_otro_negocio_no_ve_ni_reintenta(como_admin, fiscal, facturapi, caja, shampoo, otro_negocio,  # noqa: F811
                                         crear_usuario, cliente_de):
    facturapi.timbrar = httpx.ReadTimeout("se cortó")
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()
    facturar(como_admin, v["folio"])
    [p] = _pendientes(como_admin)
    otro = cliente_de(crear_usuario(otro_negocio))
    assert otro.get("/cfdi/pendientes").json() == []
    assert otro.post(f"/cfdi/pendientes/{p['id']}/reintentar").status_code == 404


def test_reintentar_sin_datos_fiscales_explica(como_admin, db, negocio, fiscal, facturapi, caja, shampoo):  # noqa: F811
    facturapi.timbrar = httpx.ReadTimeout("se cortó")
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()
    facturar(como_admin, v["folio"])
    [p] = _pendientes(como_admin)
    negocio.rfc = None
    db.commit()
    t = como_admin.get(f"/cfdi/ticket/{v['folio']}").json()
    assert t["pendiente"] and "no se pudo confirmar" in t["motivo"]  # el pendiente se avisa primero
    resp = como_admin.post(f"/cfdi/pendientes/{p['id']}/reintentar")
    assert resp.status_code == 409 and "Faltan datos fiscales" in resp.json()["detail"]
    assert len(_pendientes(como_admin)) == 1
