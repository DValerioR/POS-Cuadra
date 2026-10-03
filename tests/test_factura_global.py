"""Factura global al público en general y cancelación de facturas ante el SAT
(con el PAC simulado)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.config import settings
from app.models import Factura, Venta, VentaEnGlobal
from app.services.factura_global import periodo
from tests.test_devoluciones import cancelar, devolver, pieza
from tests.test_facturacion import facturar, fiscal  # noqa: F401  (fixture)
from tests.test_ventas import amoxicilina, caja, r, shampoo, vender  # noqa: F401  (fixtures)

AYER = date.today() - timedelta(days=1)


def a_ayer(db, *ventas):
    """Mueve las ventas al día de ayer (la global solo se hace de periodos ya cerrados)."""
    for v in ventas:
        venta = db.get(Venta, v["id"])
        venta.created_at = datetime.combine(AYER, time(12), ZoneInfo(settings.zona_horaria))
    db.commit()


def global_de_ayer(cliente, **extra):
    return cliente.post("/cfdi/global", json={"periodicidad": "01", "fecha": AYER.isoformat(), **extra})


@pytest.mark.parametrize("periodicidad, dia, esperado", [
    ("01", date(2026, 9, 17), (date(2026, 9, 17), date(2026, 9, 17), "09", 2026)),
    ("02", date(2026, 9, 17), (date(2026, 9, 14), date(2026, 9, 20), "09", 2026)),  # lunes a domingo
    ("02", date(2026, 10, 1), (date(2026, 10, 1), date(2026, 10, 4), "10", 2026)),  # sin pasar del mes
    ("03", date(2026, 9, 15), (date(2026, 9, 1), date(2026, 9, 15), "09", 2026)),
    ("03", date(2026, 2, 20), (date(2026, 2, 16), date(2026, 2, 28), "02", 2026)),
    ("04", date(2026, 9, 17), (date(2026, 9, 1), date(2026, 9, 30), "09", 2026)),
    ("05", date(2026, 2, 10), (date(2026, 1, 1), date(2026, 2, 28), "13", 2026)),
    ("05", date(2026, 12, 5), (date(2026, 11, 1), date(2026, 12, 31), "18", 2026)),
])
def test_periodos(periodicidad, dia, esperado):
    assert periodo(periodicidad, dia) == esperado


def test_global_con_tickets_libres(como_admin, db, fiscal, caja, shampoo, amoxicilina):
    v1 = vender(como_admin, caja, [r(shampoo, 2), r(amoxicilina, 1)], efectivo="400").json()  # IVA 16 y 0
    v2 = vender(como_admin, caja, [r(shampoo, 1)], tarjeta="116").json()
    v3 = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()  # se factura a un cliente
    v4 = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()  # se cancela
    v5 = vender(como_admin, caja, [r(shampoo, 2)], efectivo="232").json()  # devuelven una pieza
    assert facturar(como_admin, v3["folio"]).status_code == 201
    cancelar(como_admin, v4, caja)
    devolver(como_admin, v5, caja, [pieza(v5, 0, 1)])
    a_ayer(db, v1, v2, v3, v4, v5)

    p = como_admin.get(f"/cfdi/global?periodicidad=01&fecha={AYER.isoformat()}").json()
    assert p["puede_facturar"], p["motivo"]
    assert [t["folio"] for t in p["tickets"]] == [v1["folio"], v2["folio"], v5["folio"]]
    assert p["total"] == "549.50"  # 317.50 + 116 + 116 (la mitad del ticket con devolución)
    assert p["forma_pago"] == "01" and p["con_tarjeta"] is True

    f = global_de_ayer(como_admin)
    assert f.status_code == 201, f.text
    f = f.json()
    assert (f["tipo"], f["receptor_rfc"], f["receptor_nombre"], f["total"]) == \
        ("global", "XAXX010101000", "PUBLICO EN GENERAL", "549.50")
    assert f["periodo"] == f"Diaria: {AYER:%d/%m/%Y}" and f["folio_ticket"] is None
    xml = como_admin.get(f"/cfdi/{f['id']}/xml").content.decode()
    assert f'<cfdi:InformacionGlobal Periodicidad="01" Meses="{AYER.month:02d}" Año="{AYER.year}"/>' in xml
    assert 'UsoCFDI="S01"' in xml and 'RegimenFiscalReceptor="616"' in xml and 'ClaveUnidad="ACT"' in xml
    assert xml.count(f'NoIdentificacion="{v1["folio"]}"') == 2  # un concepto por cada tasa de IVA
    d = como_admin.get(f"/cfdi/{f['id']}").json()
    assert d["tickets"] == [v1["folio"], v2["folio"], v5["folio"]]

    # Los tickets ya no se facturan aparte ni entran en otra global.
    assert "factura global" in como_admin.get(f"/cfdi/ticket/{v1['folio']}").json()["motivo"]
    otra = como_admin.get(f"/cfdi/global?periodicidad=01&fecha={AYER.isoformat()}").json()
    assert not otra["puede_facturar"] and "No hay tickets" in otra["motivo"]


def test_periodo_que_no_ha_terminado(como_admin, fiscal, caja, shampoo):
    vender(como_admin, caja, [r(shampoo, 1)], efectivo="116")
    p = como_admin.get(f"/cfdi/global?periodicidad=01&fecha={date.today().isoformat()}").json()
    assert not p["puede_facturar"] and "no termina" in p["motivo"]
    res = como_admin.post("/cfdi/global", json={"periodicidad": "01", "fecha": date.today().isoformat()})
    assert res.status_code == 409


def test_global_solo_admin(como_mostrador):
    assert como_mostrador.get(f"/cfdi/global?periodicidad=01&fecha={AYER.isoformat()}").status_code == 403


def test_cancelar_factura_y_volver_a_facturar(como_admin, db, fiscal, caja, shampoo):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    f = facturar(como_admin, v["folio"]).json()
    assert como_admin.post(f"/cfdi/{f['id']}/cancelar", json={"motivo": "01"}).status_code == 409  # motivo no ofrecido
    c = como_admin.post(f"/cfdi/{f['id']}/cancelar", json={"motivo": "02"})
    assert c.status_code == 200, c.text
    assert (c.json()["estado"], c.json()["cancelacion_motivo"]) == ("cancelada", "02")
    assert como_admin.post(f"/cfdi/{f['id']}/cancelar", json={"motivo": "02"}).status_code == 409  # ya cancelada
    # El ticket se puede facturar otra vez (con otro folio).
    otra = facturar(como_admin, v["folio"])
    assert otra.status_code == 201 and otra.json()["folio"] == 2


def test_cancelar_global_libera_los_tickets(como_admin, db, fiscal, caja, shampoo):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    a_ayer(db, v)
    f = global_de_ayer(como_admin).json()
    assert como_admin.post(f"/cfdi/{f['id']}/cancelar", json={"motivo": "02"}).json()["estado"] == "cancelada"
    assert db.query(VentaEnGlobal).count() == 0
    assert como_admin.get(f"/cfdi/ticket/{v['folio']}").json()["puede_facturar"] is True
    assert global_de_ayer(como_admin).status_code == 201


def test_solo_admin_cancela(como_mostrador, como_admin, fiscal, caja, shampoo):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    f = facturar(como_admin, v["folio"]).json()
    assert como_mostrador.post(f"/cfdi/{f['id']}/cancelar", json={"motivo": "02"}).status_code == 403


def test_reintentar_global_sin_confirmar(como_admin, db, fiscal, caja, shampoo, monkeypatch):
    from app.facturacion import pac as pac_mod

    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    a_ayer(db, v)
    original = pac_mod.PacSimulado.timbrar

    def se_corta(self, datos):
        raise pac_mod.TimbradoIncierto("Se cortó la conexión")

    monkeypatch.setattr(pac_mod.PacSimulado, "timbrar", se_corta)
    assert global_de_ayer(como_admin).status_code == 409
    pendiente = como_admin.get("/cfdi/pendientes").json()
    assert len(pendiente) == 1 and pendiente[0]["tipo"] == "global" and pendiente[0]["total"] == "116.00"
    # Mientras tanto el ticket está apartado.
    assert "global" in como_admin.get(f"/cfdi/ticket/{v['folio']}").json()["motivo"]
    monkeypatch.setattr(pac_mod.PacSimulado, "timbrar", original)
    f = como_admin.post(f"/cfdi/pendientes/{pendiente[0]['id']}/reintentar")
    assert f.status_code == 201, f.text
    assert f.json()["tipo"] == "global" and db.query(VentaEnGlobal).one().factura_id == f.json()["id"]
    assert como_admin.get("/cfdi/pendientes").json() == []
    assert db.query(Factura).count() == 1
