"""Usos de IA y facturas contra los topes mensuales del plan."""

from datetime import timedelta

import pytest

from app.core.config import settings
from app.models import TipoUso, UsoServicio
from app.services import facturacion, usos
from app.whatsapp import bot
from tests.test_asistente import Bloque, Respuesta, api, clave  # noqa: F401  (fixtures)
from tests.test_bot_whatsapp import decir, ia, recibir, wa  # noqa: F401  (fixtures)
from tests.test_facturacion import facturar, fiscal  # noqa: F401  (fixtures)
from tests.test_ventas import caja, r, shampoo, vender  # noqa: F401  (fixtures)


def respuesta(texto="Listo."):
    return Respuesta([Bloque(type="text", text=texto)], "end_turn")


@pytest.fixture
def topes(monkeypatch):
    def poner(ia=None, facturas=None):
        monkeypatch.setattr(settings, "tope_ia_mes", ia)
        monkeypatch.setattr(settings, "tope_facturas_mes", facturas)
    poner()
    return poner


def test_sin_tope_solo_cuenta(como_admin, api, topes, db, negocio):
    api["guion"] = [respuesta(), respuesta()]
    for _ in range(2):
        assert como_admin.post("/asistente/preguntar", json={"texto": "hola"}).status_code == 200
    res = como_admin.get("/usos").json()
    assert res["ia"] == {"usados": 2, "tope": None, "restantes": None, "porcentaje": None, "estado": "sin_tope"}
    assert res["factura"]["usados"] == 0


def test_asistente_se_detiene_en_el_tope(como_admin, api, topes):
    topes(ia=2)
    api["guion"] = [respuesta(), respuesta()]
    assert como_admin.post("/asistente/preguntar", json={"texto": "uno"}).status_code == 200
    assert como_admin.get("/usos").json()["ia"]["estado"] == "bien"
    assert como_admin.post("/asistente/preguntar", json={"texto": "dos"}).status_code == 200
    r_ = como_admin.post("/asistente/preguntar", json={"texto": "tres"})
    assert r_.status_code == 409 and "los 2 usos de IA" in r_.json()["detail"]
    assert len(api["enviado"]) == 2  # la tercera ya no llegó a la API
    assert como_admin.get("/usos").json()["ia"] == {
        "usados": 2, "tope": 2, "restantes": 0, "porcentaje": 100, "estado": "agotado"}


def test_si_falla_la_api_no_cuenta(como_admin, api, topes, monkeypatch):
    def sin_conexion(*a):
        raise usos.OperacionInvalida("No hay conexión")

    monkeypatch.setattr("app.asistente.chat._llamar", sin_conexion)
    assert como_admin.post("/asistente/preguntar", json={"texto": "hola"}).status_code == 409
    assert como_admin.get("/usos").json()["ia"]["usados"] == 0


def test_el_mes_pasado_no_cuenta(db, negocio, topes):
    topes(ia=1)
    db.add(UsoServicio(negocio_id=negocio.id, tipo=TipoUso.IA, origen="asistente",
                       created_at=usos.inicio_del_mes() - timedelta(minutes=1)))
    db.commit()
    usos.revisar(db, negocio.id, TipoUso.IA)  # no lanza
    usos.registrar(db, negocio.id, TipoUso.IA, "asistente")
    with pytest.raises(usos.OperacionInvalida, match="Se renuevan el 1 de"):
        usos.revisar(db, negocio.id, TipoUso.IA)


def test_cada_negocio_lleva_su_cuenta(db, negocio, otro_negocio, topes):
    topes(ia=1)
    usos.registrar(db, negocio.id, TipoUso.IA, "asistente")
    assert usos.agotado(db, negocio.id, TipoUso.IA)
    assert not usos.agotado(db, otro_negocio.id, TipoUso.IA)


def test_aviso_cuando_se_esta_acabando(db, negocio, topes):
    topes(facturas=5)
    for _ in range(4):
        usos.registrar(db, negocio.id, TipoUso.FACTURA, "factura")
    f = usos.resumen(db, negocio.id)["factura"]
    assert (f["usados"], f["restantes"], f["porcentaje"], f["estado"]) == (4, 1, 80, "por_acabarse")


def test_facturas_de_prueba_no_cuentan(como_admin, fiscal, caja, shampoo, topes):
    topes(facturas=0)
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    assert facturar(como_admin, v["folio"]).status_code == 201
    assert como_admin.get("/usos").json()["factura"]["usados"] == 0


def test_facturas_reales_se_detienen_en_el_tope(como_admin, fiscal, caja, shampoo, topes, monkeypatch):
    monkeypatch.setattr(facturacion, "es_de_prueba", lambda pac: False)
    topes(facturas=1)
    v1 = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    v2 = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    assert facturar(como_admin, v1["folio"]).status_code == 201
    r_ = facturar(como_admin, v2["folio"])
    assert r_.status_code == 409 and "las 1 facturas" in r_.json()["detail"]
    assert como_admin.get(f"/cfdi/ticket/{v2['folio']}").json()["puede_facturar"] is True  # la venta sigue ahí
    assert como_admin.get("/usos").json()["factura"]["usados"] == 1


def test_bot_cuenta_y_al_acabarse_pasa_a_persona(db, negocio, wa, ia, topes, monkeypatch):
    monkeypatch.setattr(bot.horario, "esta_abierto", lambda h, cuando=None: True)
    topes(ia=1)
    ia["respuestas"] = [decir("¡Hola! ¿En qué le ayudo?")]
    c = recibir(db, negocio, "Hola")
    assert c.estado.value == "bot" and usos.usados(db, negocio.id, TipoUso.IA) == 1
    c = recibir(db, negocio, "¿Tienen paracetamol?")
    assert c.motivo_persona == "Se acabaron los usos de IA del mes"
    assert wa.enviados[-1]["texto"] == bot.MENSAJE_FALLA and len(ia["llamadas"]) == 1


def test_solo_admin_ve_los_usos(como_mostrador):
    assert como_mostrador.get("/usos").status_code == 403
