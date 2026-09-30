"""Sugerencias del asistente para el reporte de faltantes: ventas por semana,
revisión de la respuesta de la IA y columnas en el Excel."""

import json
from datetime import datetime, time, timedelta
from decimal import Decimal as D
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.asistente.consultas import _zona, hoy
from app.models import Caja, EstadoVenta, Producto, Proveedor, TipoTurno, Turno, Venta, VentaRenglon
from app.services import configuracion_ia, sugerencias_pedido
from app.services.errores import OperacionInvalida


@pytest.fixture
def datos(db, negocio, admin):
    caja = Caja(negocio_id=negocio.id, nombre="Mostrador 1")
    db.add(caja)
    db.flush()
    turno = Turno(negocio_id=negocio.id, caja_id=caja.id, tipo=TipoTurno.MANANA, fondo_inicial=D(0), abierto_por_id=admin.id)
    nadro = Proveedor(negocio_id=negocio.id, nombre="Nadro")
    amox = Producto(negocio_id=negocio.id, nombre="AMOXICILINA", clave="1", minimo=D(5), maximo=D(20))
    gasas = Producto(negocio_id=negocio.id, nombre="GASAS", clave="3", minimo=D(3), maximo=D(12))
    db.add_all([turno, nadro, amox, gasas])
    db.commit()
    return {"caja": caja, "turno": turno, "admin": admin, "nadro": nadro, "amox": amox, "gasas": gasas}


def venta(db, negocio, d, producto, cantidad, dias_atras, estado=EstadoVenta.COMPLETADA):
    folio = (db.query(Venta).count() or 0) + 1
    v = Venta(negocio_id=negocio.id, folio=folio, turno_id=d["turno"].id, caja_id=d["caja"].id, usuario_id=d["admin"].id,
              estado=estado, subtotal=D(0), ieps=D(0), iva=D(0), total=D(0),
              created_at=datetime.combine(hoy() - timedelta(days=dias_atras), time(12), _zona()))
    db.add(v)
    db.flush()
    db.add(VentaRenglon(venta_id=v.id, producto_id=producto.id, nombre=producto.nombre, cantidad=D(cantidad),
                        precio_unitario=D(0), importe=D(0), iva_porcentaje=D(0), ieps_porcentaje=D(0),
                        subtotal=D(0), ieps=D(0), iva=D(0)))
    db.commit()


def test_ventas_por_semana(db, negocio, datos):
    amox = datos["amox"]
    venta(db, negocio, datos, amox, 3, 0)
    venta(db, negocio, datos, amox, 2, 0)
    venta(db, negocio, datos, amox, 4, 7)
    venta(db, negocio, datos, amox, 9, 7, estado=EstadoVenta.CANCELADA)  # no cuenta
    venta(db, negocio, datos, amox, 50, 7 * 20)  # fuera de las 12 semanas
    inicios, ventas = sugerencias_pedido.ventas_por_semana(db, negocio.id, {amox.id, datos["gasas"].id})
    assert len(inicios) == 12 and inicios[-1].weekday() == 0
    assert ventas[amox.id][-2:] == [4, 5] and sum(ventas[amox.id]) == 9
    assert ventas[datos["gasas"].id] == [0] * 12


def test_interpretar_revisa_la_respuesta():
    renglones = [{"producto_id": 1, "sugerido": D(10)}, {"producto_id": 2, "sugerido": D(4)}]
    ventas = {1: [1] * 12, 2: [0] * 12}
    texto = json.dumps({"sugerencias": [
        {"producto_id": 1, "cantidad": 999, "motivo": "  Vende   mucho  "},  # tope: max(10, 3×12) + 10 = 46
        {"producto_id": 2, "cantidad": -3, "motivo": "negativo"},  # se descarta
        {"producto_id": 77, "cantidad": 5, "motivo": "no está en el reporte"},
    ]})
    assert sugerencias_pedido.interpretar(texto, renglones, ventas) == {1: {"cantidad": 46, "motivo": "Vende mucho"}}
    with pytest.raises(OperacionInvalida):
        sugerencias_pedido.interpretar("no es json", renglones, ventas)


def test_excel_con_sugerencias(como_bodega, db, negocio, datos, monkeypatch):
    amox = datos["amox"]
    r = como_bodega.post("/entradas", json={"proveedor_id": datos["nadro"].id, "folio": "N1", "fecha_recepcion": "2026-09-01",
                                            "renglones": [{"producto_id": amox.id, "cantidad": "1", "costo_unitario": "45"}]})
    assert r.status_code == 201, r.text
    venta(db, negocio, datos, amox, 6, 3)
    enviado = {}

    def falsa(cliente, texto):
        enviado["texto"] = texto
        return json.dumps({"sugerencias": [{"producto_id": amox.id, "cantidad": 25, "motivo": "Vende rápido"}]})

    monkeypatch.setattr(configuracion_ia, "cliente", lambda: object())
    monkeypatch.setattr(sugerencias_pedido, "_llamar", falsa)
    r = como_bodega.get("/reportes/faltantes/excel", params={"proveedor_id": datos["nadro"].id, "sugerencias": True})
    assert r.status_code == 200, r.text
    assert "AMOXICILINA" in enviado["texto"] and "GASAS" in enviado["texto"]
    wb = load_workbook(BytesIO(r.content))
    assert [c.value for c in wb["Pedido"][3]][-2:] == ["Sugerencia del asistente", "Motivo"]
    assert [c.value for c in wb["Pedido"][4]][-2:] == [25, "Vende rápido"]
    assert [c.value for c in wb["Sin proveedor registrado"][2]][-2:] == [None, "sin sugerencia"]


def test_sin_clave_avisa(como_bodega, datos, monkeypatch):
    monkeypatch.setattr(configuracion_ia.settings, "anthropic_api_key", None)
    r = como_bodega.get("/reportes/faltantes/excel", params={"proveedor_id": datos["nadro"].id, "sugerencias": True})
    assert r.status_code in (400, 409, 422) and "clave" in r.json()["detail"]
    # Sin la casilla no usa la IA.
    assert como_bodega.get("/reportes/faltantes/excel", params={"proveedor_id": datos["nadro"].id}).status_code == 200
