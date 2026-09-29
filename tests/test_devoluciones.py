"""Cancelaciones y devoluciones: piezas a su lote original, reembolso por el
método de pago, efecto en el corte del turno correcto, permisos."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.models import Lote, Turno, TipoTurno
from tests.test_ventas import amoxicilina, caja, existencias, r, shampoo, vender  # noqa: F401  (fixtures)


def cancelar(cliente, venta, caja, motivo="cliente se arrepintió"):
    return cliente.post(f"/ventas/{venta['id']}/cancelar", json={"caja_id": caja.id, "motivo": motivo})


def devolver(cliente, venta, caja, piezas, motivo="producto equivocado"):
    return cliente.post(f"/ventas/{venta['id']}/devoluciones", json={"caja_id": caja.id, "motivo": motivo, "piezas": piezas})


def pieza(venta, indice, cantidad, lote_id=None):
    return {"renglon_id": venta["renglones"][indice]["id"], "cantidad": str(cantidad), "lote_id": lote_id}


def corte(cliente, db, caja):
    turno = db.query(Turno).filter_by(caja_id=caja.id, cerrado_en=None).one()
    return cliente.get(f"/turnos/{turno.id}/corte").json()


# --- Cancelación ----------------------------------------------------------------

def test_cancelar_regresa_piezas_a_sus_lotes(como_admin, caja, amoxicilina, db):
    v = vender(como_admin, caja, [r(amoxicilina, 4)], efectivo="342").json()  # 2 de A + 2 de B
    res = cancelar(como_admin, v, caja)
    assert res.status_code == 201
    assert (res.json()["tipo"], res.json()["total"], res.json()["efectivo"]) == ("cancelacion", "342.00", "342.00")
    assert existencias(db, amoxicilina) == {
        ("A", date(2027, 1, 31)): D(2), ("B", date(2027, 6, 30)): D(5), (None, None): D(10),
    }
    assert como_admin.get(f"/ventas/{v['id']}").json()["estado"] == "cancelada"


def test_cancelar_en_el_mismo_turno_se_compensa(como_admin, caja, shampoo, db):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()
    cancelar(como_admin, v, caja)
    c = corte(como_admin, db, caja)
    assert (c["ventas_efectivo"], c["reembolsos_efectivo"], c["efectivo_esperado"]) == ("116.00", "116.00", "500.00")


def test_cancelar_venta_de_turno_cerrado(como_admin, admin, caja, shampoo, db):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    viejo = db.query(Turno).filter_by(caja_id=caja.id).one()
    como_admin.post(f"/turnos/{viejo.id}/cerrar", json={"efectivo_contado": "616", "tarjeta_contado": "0"})
    como_admin.post("/turnos", json={"caja_id": caja.id, "tipo": "tarde", "fondo_inicial": "300"})

    cancelar(como_admin, v, caja)

    db.expire_all()
    cerrado = db.get(Turno, viejo.id)
    assert cerrado.efectivo_esperado == D("616.00")  # el corte cerrado no cambia
    assert corte(como_admin, db, caja)["efectivo_esperado"] == "184.00"  # 300 - 116: sale del turno actual


def test_no_se_cancela_dos_veces(como_admin, caja, shampoo):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    cancelar(como_admin, v, caja)
    assert cancelar(como_admin, v, caja).status_code == 409


def test_cancelar_despues_de_devolucion_parcial(como_admin, caja, shampoo, db):
    v = vender(como_admin, caja, [r(shampoo, 3)], efectivo="348").json()
    devolver(como_admin, v, caja, [pieza(v, 0, 1)])
    res = cancelar(como_admin, v, caja).json()
    assert res["total"] == "232.00"  # solo lo que faltaba
    assert existencias(db, shampoo)[(None, None)] == D(20)
    detalle = como_admin.get(f"/ventas/{v['id']}").json()
    assert sum(D(d["total"]) for d in detalle["devoluciones"]) == D("348.00")


# --- Devolución parcial ---------------------------------------------------------

def test_devolver_algunas_piezas(como_admin, caja, shampoo, db):
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="232").json()
    res = devolver(como_admin, v, caja, [pieza(v, 0, 1)])
    assert res.status_code == 201
    assert (res.json()["tipo"], res.json()["total"]) == ("devolucion", "116.00")
    assert existencias(db, shampoo)[(None, None)] == D(19)
    detalle = como_admin.get(f"/ventas/{v['id']}").json()
    assert detalle["estado"] == "completada"
    assert detalle["renglones"][0]["cantidad_devuelta"] == "1.00"


def test_devolucion_al_lote_indicado(como_admin, caja, amoxicilina, db):
    v = vender(como_admin, caja, [r(amoxicilina, 4)], efectivo="342").json()  # 2 de A + 2 de B
    lote_b = db.query(Lote).filter_by(producto_id=amoxicilina.id, numero_lote="B").one()
    devolver(como_admin, v, caja, [pieza(v, 0, 1, lote_id=lote_b.id)])
    ex = existencias(db, amoxicilina)
    assert (ex[("A", date(2027, 1, 31))], ex[("B", date(2027, 6, 30))]) == (D(0), D(4))


def test_no_se_devuelve_mas_de_lo_vendido(como_admin, caja, shampoo):
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="232").json()
    assert devolver(como_admin, v, caja, [pieza(v, 0, 3)]).status_code == 409
    devolver(como_admin, v, caja, [pieza(v, 0, 2)])
    assert devolver(como_admin, v, caja, [pieza(v, 0, 1)]).status_code == 409


def test_misma_pieza_dos_veces_en_una_solicitud(como_admin, caja, shampoo, db):
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="232").json()
    assert devolver(como_admin, v, caja, [pieza(v, 0, 2), pieza(v, 0, 1)]).status_code == 409
    assert existencias(db, shampoo)[(None, None)] == D(18)  # todo o nada


def test_lote_que_no_es_de_la_venta(como_admin, caja, amoxicilina, db):
    v = vender(como_admin, caja, [r(amoxicilina, 1)], efectivo="85.50").json()  # sale del lote A
    sin_caducidad = db.query(Lote).filter_by(producto_id=amoxicilina.id, numero_lote=None).one()
    assert devolver(como_admin, v, caja, [pieza(v, 0, 1, lote_id=sin_caducidad.id)]).status_code == 409


def test_renglon_de_otra_venta(como_admin, caja, shampoo):
    v1 = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    v2 = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    assert devolver(como_admin, v1, caja, [pieza(v2, 0, 1)]).status_code == 404


# --- Dinero ------------------------------------------------------------------------

def test_reembolso_de_pago_mixto_va_primero_a_tarjeta(como_admin, caja, shampoo, db):
    v = vender(como_admin, caja, [r(shampoo, 3)], tarjeta="200", efectivo="148").json()  # 348
    d1 = devolver(como_admin, v, caja, [pieza(v, 0, 1)]).json()
    assert (d1["tarjeta"], d1["efectivo"]) == ("116.00", "0.00")
    d2 = devolver(como_admin, v, caja, [pieza(v, 0, 1)]).json()
    assert (d2["tarjeta"], d2["efectivo"]) == ("84.00", "32.00")  # se acabó lo de tarjeta
    c = corte(como_admin, db, caja)
    assert (c["tarjeta_esperado"], c["efectivo_esperado"]) == ("0.00", "616.00")  # 500 + 148 - 32


def test_reembolso_de_venta_con_tarjeta(como_admin, caja, shampoo):
    v = vender(como_admin, caja, [r(shampoo, 1)], tarjeta="116").json()
    d = cancelar(como_admin, v, caja).json()
    assert (d["tarjeta"], d["efectivo"]) == ("116.00", "0.00")


# --- Reglas y permisos -----------------------------------------------------------

def test_solo_admin(como_mostrador, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    assert cancelar(como_mostrador, v, caja).status_code == 403
    assert devolver(como_mostrador, v, caja, [pieza(v, 0, 1)]).status_code == 403


@pytest.mark.parametrize("motivo", ["", "   "])
def test_motivo_obligatorio(como_admin, caja, shampoo, motivo):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    assert cancelar(como_admin, v, caja, motivo=motivo).status_code in (409, 422)


def test_caja_sin_turno_abierto(como_admin, caja, shampoo, db):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    turno = db.query(Turno).filter_by(caja_id=caja.id).one()
    como_admin.post(f"/turnos/{turno.id}/cerrar", json={"efectivo_contado": "616", "tarjeta_contado": "0"})
    res = cancelar(como_admin, v, caja)
    assert res.status_code == 409
    assert "no tiene turno abierto" in res.json()["detail"]


def test_venta_de_otro_negocio(como_admin, caja, shampoo, cliente_de, crear_usuario, otro_negocio, db):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    ajeno = cliente_de(crear_usuario(otro_negocio))
    assert cancelar(ajeno, v, caja).status_code == 404
