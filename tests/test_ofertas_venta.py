"""Ofertas aplicadas al vender: alta con sus reglas (mínimo, receta, una por
producto, fecha de fin), cálculo en el carrito, cobro, ticket, devoluciones
y quitar la oferta."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from app.asistente.consultas import hoy
from app.models import Lote, Producto
from tests.test_ventas import caja, r, vender  # noqa: F401  (fixtures)


def producto(db, negocio, nombre, costo, precio, existencia=20, iva=0, receta=False, caducidad=None):
    p = Producto(negocio_id=negocio.id, nombre=nombre, costo=D(costo), precio_venta=D(precio), iva_porcentaje=D(iva),
                 requiere_receta=receta)
    db.add(p)
    db.flush()
    db.add(Lote(negocio_id=negocio.id, producto_id=p.id, cantidad=D(existencia), caducidad=caducidad))
    db.commit()
    return p


@pytest.fixture
def prods(db, negocio):
    negocio.redondeo_precio_venta = D(1)
    db.commit()
    return {
        "panal": producto(db, negocio, "PAÑALES", 100, 250, iva=16),
        "toallitas": producto(db, negocio, "TOALLITAS", 20, 50, iva=16),
        "jarabe": producto(db, negocio, "JARABE", 50, 80, caducidad=hoy() + timedelta(days=60)),
        "antibiotico": producto(db, negocio, "AMOXICILINA", 100, 150, receta=True),
    }


def nueva(cliente, p, tipo, precio=None, dias=14, **extra):
    return cliente.post("/ofertas", json={"producto_id": p.id, "tipo": tipo, "precio": precio,
                                          "fin": (hoy() + timedelta(days=dias)).isoformat(), **extra})


def test_reglas_al_crear(como_admin, como_mostrador, prods):
    panal, jarabe, anti = prods["panal"], prods["jarabe"], prods["antibiotico"]
    assert nueva(como_mostrador, panal, "descuento", 200).status_code == 403
    # Mínimo de pañales: 100 × 1.10 × 1.16 = 127.60 → $128.
    r1 = nueva(como_admin, panal, "descuento", 120)
    assert r1.status_code == 409 and "$128.00" in r1.json()["detail"]
    assert nueva(como_admin, panal, "descuento", 260).status_code == 409  # más caro que el normal
    assert nueva(como_admin, panal, "2x1").status_code == 409  # $125 por pieza < $128
    assert nueva(como_admin, panal, "descuento", 200, dias=-1).status_code == 409  # fecha pasada
    assert nueva(como_admin, panal, "descuento", 200, dias=400).status_code == 409
    # Lo que caduca pronto puede ir al costo.
    assert nueva(como_admin, jarabe, "precio_especial", 50).status_code == 201
    assert nueva(como_admin, jarabe, "descuento", 60).status_code == 409  # ya tiene oferta
    # Con receta: solo descuento o precio especial.
    assert nueva(como_admin, anti, "3x2").status_code == 409
    assert nueva(como_admin, anti, "descuento", 140).status_code == 201


def test_cobro_con_3x2_y_devolucion(como_admin, caja, prods, db):
    panal = prods["panal"]
    assert nueva(como_admin, panal, "3x2").status_code == 201
    cot = como_admin.post("/ventas/cotizar", json={"renglones": [r(panal, 4)]}).json()
    assert cot["descuento"] == "250.00" and cot["total"] == "750.00"
    assert cot["renglones"][0]["oferta"] == "Oferta 3x2"

    v = vender(como_admin, caja, [r(panal, 4)], efectivo="750").json()
    assert v["total"] == "750.00"
    renglon = v["renglones"][0]
    assert renglon["precio_unitario"] == "250.00" and renglon["descuento"] == "250.00" and renglon["importe"] == "750.00"
    assert renglon["subtotal"] == "646.55"  # el desglose es sobre lo cobrado
    ticket = como_admin.get(f"/ventas/{v['id']}/ticket").text
    assert "Oferta 3x2" in ticket and "-$250.00" in ticket and "Usted ahorró" in ticket

    # Devolver 1 de 4 regresa lo pagado por pieza (750 / 4), no el precio normal.
    d = como_admin.post(f"/ventas/{v['id']}/devoluciones", json={
        "caja_id": caja.id, "motivo": "no le quedó", "piezas": [{"renglon_id": renglon["id"], "cantidad": "1"}]})
    assert d.status_code == 201, d.text
    assert d.json()["total"] == "187.50"


def test_paquete(como_admin, caja, prods):
    panal, toallitas = prods["panal"], prods["toallitas"]
    assert nueva(como_admin, panal, "paquete", 270, paquete_con_id=toallitas.id).status_code == 201
    # Las toallitas ya están en el paquete: no pueden tener otra oferta.
    assert nueva(como_admin, toallitas, "descuento", 45).status_code == 409
    cot = como_admin.post("/ventas/cotizar", json={"renglones": [r(panal, 1), r(toallitas, 2)]}).json()
    # Un paquete (300 → 270): $30 de ahorro repartido 250:50.
    assert [x["descuento"] for x in cot["renglones"]] == ["25.00", "5.00"]
    assert cot["total"] == "320.00"
    assert cot["renglones"][1]["oferta"] == "1 en paquete con PAÑALES"  # la otra toallita va a precio normal
    # Solo pañales: no hay paquete.
    assert como_admin.post("/ventas/cotizar", json={"renglones": [r(panal, 1)]}).json()["descuento"] == "0"


def test_paquete_por_pares(como_admin, caja, prods):
    panal, toallitas = prods["panal"], prods["toallitas"]
    assert nueva(como_admin, panal, "paquete", 270, paquete_con_id=toallitas.id).status_code == 201

    def cotizar(n_panal, n_toallitas):
        return como_admin.post("/ventas/cotizar", json={"renglones": [r(panal, n_panal), r(toallitas, n_toallitas)]}).json()

    # 2 pañales y 1 toallitas: un paquete ($270) y un pañal a precio normal ($250).
    cot = cotizar(2, 1)
    assert cot["total"] == "520.00"
    assert [x["oferta"] for x in cot["renglones"]] == ["1 en paquete con TOALLITAS", "Paquete con PAÑALES"]
    # 2 y 2: dos paquetes.
    assert cotizar(2, 2)["total"] == "540.00"


def test_paquete_no_se_rompe_al_devolver(como_admin, caja, prods):
    from tests.test_devoluciones import cambiar
    panal, toallitas, jarabe = prods["panal"], prods["toallitas"], prods["jarabe"]
    assert nueva(como_admin, panal, "paquete", 270, paquete_con_id=toallitas.id).status_code == 201
    v = vender(como_admin, caja, [r(panal, 2), r(toallitas, 1), r(jarabe, 1)], efectivo="600").json()
    assert v["total"] == "600.00"  # 270 del paquete + 250 del pañal de más + 80 del jarabe
    ids = {x["nombre"]: x["id"] for x in v["renglones"]}

    def devolver(**piezas):
        return como_admin.post(f"/ventas/{v['id']}/devoluciones", json={
            "caja_id": caja.id, "motivo": "no le quedó",
            "piezas": [{"renglon_id": ids[n.upper().replace("PANAL", "PAÑALES")], "cantidad": str(c)} for n, c in piezas.items()]})

    # Las toallitas solas romperían el paquete.
    d = devolver(toallitas=1)
    assert d.status_code == 409 and "regresar también" in d.json()["detail"]
    assert devolver(panal=2).status_code == 409  # el segundo pañal va en el paquete
    assert cambiar(como_admin, v, caja, [{"renglon_id": ids["TOALLITAS"], "cantidad": "1"}], [r(jarabe, 1)]).status_code == 409
    # El pañal de más se regresa a precio normal; el paquete queda completo.
    d = devolver(panal=1)
    assert d.status_code == 201, d.text
    assert d.json()["total"] == "250.00"
    # Ahora ya solo queda el paquete: se regresa completo o nada.
    assert devolver(panal=1).status_code == 409
    assert devolver(jarabe=1).json()["total"] == "80.00"
    d = devolver(panal=1, toallitas=1)
    assert d.status_code == 201, d.text
    assert d.json()["total"] == "270.00"


def test_quitar_y_vencida(como_admin, caja, prods, db):
    jarabe = prods["jarabe"]
    o = nueva(como_admin, jarabe, "precio_especial", 60).json()
    assert como_admin.post("/ventas/cotizar", json={"renglones": [r(jarabe, 2)]}).json()["total"] == "120.00"
    lista = como_admin.get("/ofertas/activas").json()
    assert [x["id"] for x in lista["activas"]] == [o["id"]]
    assert como_admin.get(f"/ofertas/producto/{jarabe.id}").json()["texto"] == "Precio especial"

    assert como_admin.post(f"/ofertas/{o['id']}/quitar").status_code == 200
    assert como_admin.post("/ventas/cotizar", json={"renglones": [r(jarabe, 2)]}).json()["total"] == "160.00"
    assert como_admin.get("/ofertas/activas").json()["terminadas"][0]["quitada_por"]
    # Ya quitada, se puede poner otra.
    otra = nueva(como_admin, jarabe, "descuento", 70)
    assert otra.status_code == 201 and otra.json()["texto"] == "Descuento 13%"  # 70 de 80


def test_si_baja_el_precio_normal_no_se_aplica(como_admin, caja, prods, db):
    jarabe = prods["jarabe"]
    assert nueva(como_admin, jarabe, "precio_especial", 70).status_code == 201
    jarabe.precio_venta = D(65)
    db.commit()
    assert como_admin.post("/ventas/cotizar", json={"renglones": [r(jarabe, 1)]}).json()["total"] == "65.00"


def test_minimo(como_admin, prods):
    m = como_admin.get("/ofertas/minimo", params={"producto_id": prods["jarabe"].id}).json()
    assert m["precio_minimo"] == "50.00" and m["caduca_pronto"] is True
