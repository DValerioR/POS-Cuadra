"""Facturar un ticket (CFDI 4.0) con el PAC simulado."""

from decimal import Decimal as D

import pytest

from app.core.config import settings
from tests.test_devoluciones import cancelar, devolver, pieza
from tests.test_ventas import amoxicilina, caja, r, shampoo, vender  # noqa: F401  (fixtures)

CLIENTE = {"rfc": "CARA620802A15", "nombre": "José Ángel Caro Rincón", "codigo_postal": "46470",
           "regimen_fiscal": "612", "uso_cfdi": "G03"}


@pytest.fixture
def fiscal(db, negocio, monkeypatch):
    negocio.razon_social, negocio.rfc = "Zaida Valerio Barrantes", "VABZ611024RW3"
    negocio.regimen_fiscal, negocio.codigo_postal = "612", "46470"
    db.commit()
    monkeypatch.setattr(settings, "pac", "simulado")


def facturar(cliente, folio, **extra):
    return cliente.post("/cfdi", json={**CLIENTE, "folio_ticket": folio, **extra})


def test_preparar_y_facturar(como_admin, db, fiscal, caja, shampoo, amoxicilina):
    shampoo.clave_sat = "53131600"
    db.commit()
    v = vender(como_admin, caja, [r(shampoo, 2), r(amoxicilina, 1)], efectivo="400").json()
    p = como_admin.get(f"/cfdi/ticket/{v['folio']}").json()
    assert p["puede_facturar"] and p["forma_pago"] == "01" and p["total"] == "317.50"
    sh = next(c for c in p["conceptos"] if c["descripcion"] == "SHAMPOO 400ML")
    assert (sh["clave_prod_serv"], sh["valor_unitario"], sh["importe"], sh["iva"]) == ("53131600", "100.000000", "200.00", "32.00")
    assert any("01010101" in a for a in p["avisos"])  # la amoxicilina no tiene clave SAT

    f = facturar(como_admin, v["folio"])
    assert f.status_code == 201, f.text
    f = f.json()
    assert (f["serie"], f["folio"], f["receptor_nombre"], f["de_prueba"], f["total"]) == \
        ("C", 1, "JOSÉ ÁNGEL CARO RINCÓN", True, "317.50")
    d = como_admin.get(f"/cfdi/{f['id']}").json()
    assert d["emisor_rfc"] == "VABZ611024RW3" and len(d["conceptos"]) == 2 and d["rfc_prov_certif"] == "SIMULADO"
    xml = como_admin.get(f"/cfdi/{f['id']}/xml")
    assert b'Rfc="CARA620802A15"' in xml.content and b'UsoCFDI="G03"' in xml.content
    # No se factura dos veces; el cliente queda guardado.
    assert facturar(como_admin, v["folio"]).status_code in (400, 409, 422)
    assert como_admin.get(f"/cfdi/ticket/{v['folio']}").json()["puede_facturar"] is False
    assert como_admin.get("/cfdi/clientes/cara620802a15").json()["nombre"] == "JOSÉ ÁNGEL CARO RINCÓN"
    assert [x["folio_ticket"] for x in como_admin.get("/cfdi").json()] == [v["folio"]]


def test_tarjeta_de_debito(como_mostrador, fiscal, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], tarjeta="116").json()
    assert como_mostrador.get(f"/cfdi/ticket/{v['folio']}").json()["con_tarjeta"] is True
    f = facturar(como_mostrador, v["folio"], tarjeta="28").json()
    assert f["forma_pago"] == "28"


@pytest.mark.parametrize("cambio, texto", [
    ({"regimen_fiscal": "601"}, "personas morales"),  # RFC de persona física con régimen de moral
    ({"regimen_fiscal": "616"}, "S01"),
    ({"rfc": "XAXX010101000"}, "RFC"),
    ({"rfc": "ABC"}, "RFC"),
    ({"codigo_postal": "123"}, "código postal"),
])
def test_validaciones(como_admin, fiscal, caja, shampoo, cambio, texto):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()
    resp = facturar(como_admin, v["folio"], **cambio)
    assert resp.status_code in (400, 409, 422) and texto in resp.json()["detail"], resp.text


def test_tickets_que_no_se_facturan(como_admin, fiscal, caja, shampoo):
    v1 = vender(como_admin, caja, [r(shampoo, 2)], efectivo="300").json()
    devolver(como_admin, v1, caja, [pieza(v1, 0, 1)])
    assert "devoluciones" in como_admin.get(f"/cfdi/ticket/{v1['folio']}").json()["motivo"]
    v2 = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()
    cancelar(como_admin, v2, caja)
    assert "cancelado" in como_admin.get(f"/cfdi/ticket/{v2['folio']}").json()["motivo"]
    assert como_admin.get("/cfdi/ticket/99999").status_code == 404


def test_sin_datos_fiscales_o_sin_pac(como_admin, db, negocio, caja, shampoo, monkeypatch):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()
    assert "Datos del negocio" in como_admin.get(f"/cfdi/ticket/{v['folio']}").json()["motivo"]
    negocio.razon_social, negocio.rfc, negocio.regimen_fiscal, negocio.codigo_postal = "X", "VABZ611024RW3", "612", "46470"
    db.commit()
    monkeypatch.setattr(settings, "pac", "")
    resp = facturar(como_admin, v["folio"])
    assert resp.status_code in (400, 409, 422) and "PAC" in resp.json()["detail"]


def test_bodega_no_factura(como_bodega):
    assert como_bodega.get("/cfdi").status_code == 403
