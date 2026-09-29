"""Ventas: precios, impuestos, lotes (FEFO, lote elegido, captura de
caducidad), cobro (efectivo, tarjeta, mixto), turnos, permisos y folios."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.models import Caja, Categoria, Lote, Producto, Turno, TipoTurno
from app.services.ventas import desglosar


@pytest.fixture
def caja(db, negocio, admin) -> Caja:
    """Caja con turno abierto (fondo 500)."""
    c = Caja(negocio_id=negocio.id, nombre="Mostrador 1")
    db.add(c)
    db.commit()
    db.add(Turno(negocio_id=negocio.id, caja_id=c.id, tipo=TipoTurno.MANANA, fondo_inicial=D(500), abierto_por_id=admin.id))
    db.commit()
    return c


def producto(db, negocio, nombre, precio, lotes=(), iva=0, ieps=0, **extra) -> Producto:
    """lotes: [(cantidad, caducidad o None, numero_lote o None), ...]"""
    p = Producto(negocio_id=negocio.id, nombre=nombre, precio_venta=D(precio),
                 iva_porcentaje=D(iva), ieps_porcentaje=D(ieps), **extra)
    db.add(p)
    db.commit()
    for cantidad, caducidad, numero in lotes:
        db.add(Lote(negocio_id=negocio.id, producto_id=p.id, cantidad=D(cantidad), caducidad=caducidad, numero_lote=numero))
    db.commit()
    return p


@pytest.fixture
def amoxicilina(db, negocio):
    # Lotes desordenados a propósito: FEFO debe tomar primero el de enero.
    return producto(db, negocio, "AMOXICILINA 500MG", "85.50", [
        (5, date(2027, 6, 30), "B"),
        (2, date(2027, 1, 31), "A"),
        (10, None, None),  # heredado de PVWin, sin caducidad
    ])


@pytest.fixture
def shampoo(db, negocio):
    return producto(db, negocio, "SHAMPOO 400ML", "116.00", [(20, None, None)], iva=16)


def vender(cliente, caja, renglones, tarjeta="0", efectivo="0"):
    return cliente.post("/ventas", json={
        "caja_id": caja.id, "renglones": renglones, "tarjeta": tarjeta, "efectivo_recibido": efectivo,
    })


def r(p, cantidad, **extra):
    return {"producto_id": p.id, "cantidad": str(cantidad), **extra}


def existencias(db, p):
    db.expire_all()
    return {(l.numero_lote, l.caducidad): l.cantidad for l in db.query(Lote).filter_by(producto_id=p.id)}


# --- Impuestos ----------------------------------------------------------------

@pytest.mark.parametrize(("importe", "iva", "ieps", "esperado"), [
    ("116.00", 16, 0, ("100.00", "0.00", "16.00")),
    ("85.50", 0, 0, ("85.50", "0.00", "0.00")),
    ("25.00", 16, 8, ("19.96", "1.60", "3.44")),  # IVA sobre subtotal + IEPS
    ("0.10", 16, 0, ("0.09", "0.00", "0.01")),
])
def test_desglose_de_impuestos(importe, iva, ieps, esperado):
    subtotal, i_ieps, i_iva = desglosar(D(importe), D(iva), D(ieps))
    assert (str(subtotal), str(i_ieps), str(i_iva)) == esperado
    assert subtotal + i_ieps + i_iva == D(importe)


# --- Venta básica ----------------------------------------------------------------

def test_venta_en_efectivo_con_cambio(como_mostrador, mostrador, caja, shampoo):
    res = vender(como_mostrador, caja, [r(shampoo, 2)], efectivo="300")
    assert res.status_code == 201, res.text
    v = res.json()
    assert (v["total"], v["subtotal"], v["iva"], v["cambio"]) == ("232.00", "200.00", "32.00", "68.00")
    assert v["usuario_id"] == mostrador.id
    assert v["folio"] == 1
    assert v["pagos"] == [{"metodo": "efectivo", "monto": "232.00", "recibido": "300.00", "cambio": "68.00"}]


def test_venta_con_tarjeta(como_mostrador, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], tarjeta="116").json()
    assert v["pagos"] == [{"metodo": "tarjeta", "monto": "116.00", "recibido": None, "cambio": None}]
    assert v["cambio"] == "0"


def test_pago_mixto(como_mostrador, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 2)], tarjeta="200", efectivo="50").json()
    assert [(p["metodo"], p["monto"], p["cambio"]) for p in v["pagos"]] == [
        ("tarjeta", "200.00", None), ("efectivo", "32.00", "18.00"),
    ]


@pytest.mark.parametrize(("tarjeta", "efectivo", "mensaje"), [
    ("0", "100", "Faltan 16.00"),
    ("200", "0", "mayor que el total"),
    ("116", "20", "no se necesita efectivo"),
])
def test_pagos_invalidos(como_mostrador, caja, shampoo, db, tarjeta, efectivo, mensaje):
    res = vender(como_mostrador, caja, [r(shampoo, 1)], tarjeta=tarjeta, efectivo=efectivo)
    assert res.status_code == 409
    assert mensaje in res.json()["detail"]
    assert existencias(db, shampoo)[(None, None)] == D(20)  # no se descontó nada


def test_folios_consecutivos(como_mostrador, caja, shampoo):
    folios = [vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()["folio"] for _ in range(3)]
    assert folios == [1, 2, 3]


def test_precio_se_congela_en_la_venta(como_mostrador, como_admin, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    como_admin.put(f"/productos/{shampoo.id}", json={"precio_venta": "999"})
    assert como_mostrador.get(f"/ventas/{v['id']}").json()["renglones"][0]["precio_unitario"] == "116.00"


# --- Lotes ------------------------------------------------------------------------

def test_fefo_toma_primero_el_que_caduca_antes(como_mostrador, caja, amoxicilina, db):
    v = vender(como_mostrador, caja, [r(amoxicilina, 4)], efectivo="342").json()
    # 2 del lote A (enero) y 2 del lote B (junio); el sin caducidad no se toca.
    assert [(l["numero_lote"], l["cantidad"]) for l in v["renglones"][0]["lotes"]] == [("A", "2.00"), ("B", "2.00")]
    assert existencias(db, amoxicilina) == {
        ("A", date(2027, 1, 31)): D(0), ("B", date(2027, 6, 30)): D(3), (None, None): D(10),
    }


def test_fefo_completa_con_lote_sin_caducidad(como_mostrador, caja, amoxicilina, db):
    vender(como_mostrador, caja, [r(amoxicilina, 9)], efectivo="769.50")
    assert existencias(db, amoxicilina)[(None, None)] == D(8)


def test_vendedor_indica_el_lote_que_entrego(como_mostrador, caja, amoxicilina, db):
    lote_b = db.query(Lote).filter_by(producto_id=amoxicilina.id, numero_lote="B").one()
    v = vender(como_mostrador, caja, [r(amoxicilina, 1, lote_id=lote_b.id)], efectivo="85.50").json()
    assert v["renglones"][0]["lotes"][0]["numero_lote"] == "B"
    assert existencias(db, amoxicilina)[("A", date(2027, 1, 31))] == D(2)  # FEFO no se aplicó


def test_lote_elegido_sin_suficientes_piezas(como_mostrador, caja, amoxicilina, db):
    lote_a = db.query(Lote).filter_by(producto_id=amoxicilina.id, numero_lote="A").one()
    res = vender(como_mostrador, caja, [r(amoxicilina, 3, lote_id=lote_a.id)], efectivo="999")
    assert res.status_code == 409


def test_captura_caducidad_al_vender(como_mostrador, caja, amoxicilina, db):
    """La caja en mano no tenía caducidad registrada: se captura y se vende de ahí."""
    v = vender(como_mostrador, caja, [r(amoxicilina, 2, caducidad="2027-09-30", numero_lote="C")], efectivo="171").json()
    assert v["renglones"][0]["lotes"][0]["caducidad"] == "2027-09-30"
    ex = existencias(db, amoxicilina)
    assert ex[(None, None)] == D(8)  # salieron 2 del sin caducidad...
    assert ex[("C", date(2027, 9, 30))] == D(0)  # ...pasaron al lote C y se vendieron


def test_misma_pieza_no_se_vende_dos_veces_en_una_venta(como_mostrador, caja, db, negocio):
    p = producto(db, negocio, "UNICO", "10", [(1, None, None)])
    res = vender(como_mostrador, caja, [r(p, 1), r(p, 1)], efectivo="20")
    assert res.status_code == 409
    assert existencias(db, p)[(None, None)] == D(1)  # todo o nada


def test_sin_existencia_no_se_vende(como_mostrador, caja, db, negocio):
    p = producto(db, negocio, "AGOTADO", "10", [(2, None, None)])
    res = vender(como_mostrador, caja, [r(p, 3)], efectivo="30")
    assert res.status_code == 409
    assert "Solo hay 2" in res.json()["detail"]


# --- Validaciones -----------------------------------------------------------------

def test_producto_sin_precio(como_mostrador, caja, db, negocio):
    p = Producto(negocio_id=negocio.id, nombre="SIN PRECIO")
    db.add(p)
    db.commit()
    res = vender(como_mostrador, caja, [r(p, 1)], efectivo="10")
    assert res.status_code == 409
    assert "no tiene precio" in res.json()["detail"]


def test_producto_desactivado(como_mostrador, caja, db, negocio):
    p = producto(db, negocio, "VIEJO", "10", [(5, None, None)], activo=False)
    assert vender(como_mostrador, caja, [r(p, 1)], efectivo="10").status_code == 409


def test_aviso_de_receta(como_mostrador, caja, db, negocio):
    p = producto(db, negocio, "CIPROFLOXACINO", "50", [(5, None, None)], requiere_receta=True)
    v = vender(como_mostrador, caja, [r(p, 1)], efectivo="50").json()
    assert v["avisos"] == ["CIPROFLOXACINO: requiere receta médica"]


def test_caducidad_en_producto_sin_control_de_lote(como_mostrador, caja, db, negocio):
    cat = Categoria(negocio_id=negocio.id, nombre="Dulces", controla_lote=False)
    db.add(cat)
    db.commit()
    p = producto(db, negocio, "CHICLE", "5", [(10, None, None)], categoria_id=cat.id)
    assert vender(como_mostrador, caja, [r(p, 1, caducidad="2027-01-01")], efectivo="5").status_code == 409
    assert vender(como_mostrador, caja, [r(p, 1)], efectivo="5").status_code == 201


def test_venta_vacia_o_cantidad_cero(como_mostrador, caja, shampoo):
    assert vender(como_mostrador, caja, []).status_code == 422
    assert vender(como_mostrador, caja, [r(shampoo, 0)]).status_code == 422


# --- Turnos y permisos ------------------------------------------------------------

def test_sin_turno_abierto_no_se_vende(como_mostrador, db, negocio, shampoo):
    sin_turno = Caja(negocio_id=negocio.id, nombre="Mostrador 2")
    db.add(sin_turno)
    db.commit()
    res = vender(como_mostrador, sin_turno, [r(shampoo, 1)], efectivo="116")
    assert res.status_code == 409
    assert "no tiene turno abierto" in res.json()["detail"]


def test_bodega_no_vende(como_bodega, caja, shampoo):
    assert vender(como_bodega, caja, [r(shampoo, 1)], efectivo="116").status_code == 403


def test_corte_suma_las_ventas(como_mostrador, caja, shampoo, db):
    vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="200")  # 116 efectivo
    vender(como_mostrador, caja, [r(shampoo, 2)], tarjeta="200", efectivo="32")  # 200 tarjeta + 32 efectivo
    turno = db.query(Turno).filter_by(caja_id=caja.id).one()
    c = como_mostrador.get(f"/turnos/{turno.id}/corte").json()
    assert (c["ventas_efectivo"], c["ventas_tarjeta"]) == ("148.00", "200.00")
    assert c["efectivo_esperado"] == "648.00"  # fondo 500 + 148 (el cambio no cuenta)
    cerrado = como_mostrador.post(f"/turnos/{turno.id}/cerrar", json={"efectivo_contado": "648", "tarjeta_contado": "200"}).json()
    assert (cerrado["diferencia_efectivo"], cerrado["diferencia_tarjeta"]) == ("0.00", "0.00")


def test_venta_de_otro_negocio_es_invisible(como_mostrador, como_admin, caja, shampoo, cliente_de, crear_usuario, otro_negocio):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    ajeno = cliente_de(crear_usuario(otro_negocio))
    assert ajeno.get(f"/ventas/{v['id']}").status_code == 404
    assert ajeno.post("/ventas", json={
        "caja_id": caja.id, "renglones": [r(shampoo, 1)], "efectivo_recibido": "116",
    }).status_code == 404


def test_historial_de_ventas_solo_admin(como_mostrador, como_admin, caja, shampoo):
    vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116")
    assert como_mostrador.get("/ventas").status_code == 200  # solo las de hoy (ver test_solicitudes)
    assert [v["total"] for v in como_admin.get("/ventas").json()] == ["116.00"]


def test_buscar_venta_por_folio(como_mostrador, como_admin, caja, shampoo):
    primera = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    vender(como_mostrador, caja, [r(shampoo, 2)], efectivo="232")
    assert [v["id"] for v in como_admin.get("/ventas", params={"folio": primera["folio"]}).json()] == [primera["id"]]
    assert como_admin.get("/ventas", params={"folio": 999}).json() == []
