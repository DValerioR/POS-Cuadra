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


# --- Cambio de producto ------------------------------------------------------------

def cambiar(cliente, venta, caja, devueltas, nuevos, tarjeta="0", efectivo="0", motivo="se equivocó de medicamento"):
    return cliente.post(f"/ventas/{venta['id']}/cambio", json={
        "caja_id": caja.id, "motivo": motivo, "devueltas": devueltas, "nuevos": nuevos,
        "tarjeta": tarjeta, "efectivo_recibido": efectivo,
    })


def test_cambio_cliente_paga_la_diferencia(como_admin, caja, shampoo, amoxicilina, db):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    res = cambiar(como_admin, v, caja, [pieza(v, 0, 1)], [r(amoxicilina, 2)], efectivo="100")  # 171 - 116 = 55
    assert res.status_code == 201, res.text
    c = res.json()
    assert (c["valor_devuelto"], c["total_nuevo"], c["paga_cliente"], c["se_le_regresa"]) == ("116.00", "171.00", "55.00", "0.00")
    assert [(p["metodo"], p["monto"], p["cambio"]) for p in c["venta"]["pagos"]] == [
        ("saldo_a_favor", "116.00", None), ("efectivo", "55.00", "45.00"),
    ]
    assert existencias(db, shampoo)[(None, None)] == D(20)  # el shampoo regresó
    assert existencias(db, amoxicilina)[("A", date(2027, 1, 31))] == D(0)  # salió por FEFO
    k = corte(como_admin, db, caja)
    # En caja entró 116 (venta) + 55 (diferencia); el saldo no es dinero.
    assert (k["ventas_efectivo"], k["reembolsos_efectivo"], k["efectivo_esperado"]) == ("171.00", "0.00", "671.00")


def test_cambio_se_le_regresa_la_diferencia_en_efectivo(como_admin, caja, shampoo, amoxicilina, db):
    v = vender(como_admin, caja, [r(amoxicilina, 2)], tarjeta="171").json()  # pagó con tarjeta
    c = cambiar(como_admin, v, caja, [pieza(v, 0, 2)], [r(shampoo, 1)]).json()  # 171 - 116 = 55 a favor
    assert (c["paga_cliente"], c["se_le_regresa"]) == ("0.00", "55.00")
    assert (c["devolucion"]["efectivo"], c["devolucion"]["tarjeta"]) == ("55.00", "0.00")  # siempre efectivo
    k = corte(como_admin, db, caja)
    assert (k["tarjeta_esperado"], k["efectivo_esperado"]) == ("171.00", "445.00")  # 500 - 55


def test_cambio_por_el_mismo_valor(como_admin, caja, shampoo, db, negocio):
    from tests.test_ventas import producto
    otro = producto(db, negocio, "SHAMPOO ANTICASPA", "116.00", [(5, None, None)], iva=16)
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    c = cambiar(como_admin, v, caja, [pieza(v, 0, 1)], [r(otro, 1)]).json()
    assert (c["paga_cliente"], c["se_le_regresa"]) == ("0.00", "0.00")
    assert [p["metodo"] for p in c["venta"]["pagos"]] == ["saldo_a_favor"]


def test_cambio_con_pago_insuficiente_no_guarda_nada(como_admin, caja, shampoo, amoxicilina, db):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    res = cambiar(como_admin, v, caja, [pieza(v, 0, 1)], [r(amoxicilina, 2)], efectivo="10")
    assert res.status_code == 409
    assert "Faltan 45.00" in res.json()["detail"]
    assert existencias(db, shampoo)[(None, None)] == D(19)  # no regresó
    assert como_admin.get(f"/ventas/{v['id']}").json()["devoluciones"] == []


def test_cambio_por_otro_lote_del_mismo_producto(como_admin, caja, amoxicilina, db):
    """Regresa una caja del lote A y se lleva una del lote B."""
    lote_b = db.query(Lote).filter_by(producto_id=amoxicilina.id, numero_lote="B").one()
    v = vender(como_admin, caja, [r(amoxicilina, 1)], efectivo="85.50").json()  # sale del A
    c = cambiar(como_admin, v, caja, [pieza(v, 0, 1)], [r(amoxicilina, 1, lote_id=lote_b.id)]).json()
    assert c["se_le_regresa"] == "0.00"
    ex = existencias(db, amoxicilina)
    assert (ex[("A", date(2027, 1, 31))], ex[("B", date(2027, 6, 30))]) == (D(2), D(4))


def test_cancelar_despues_de_un_cambio_no_regresa_dos_veces(como_admin, caja, shampoo, amoxicilina):
    v = vender(como_admin, caja, [r(shampoo, 2)], efectivo="232").json()
    cambiar(como_admin, v, caja, [pieza(v, 0, 1)], [r(amoxicilina, 1)], efectivo="0")  # 116 cubre 85.50
    d = cancelar(como_admin, v, caja).json()
    assert d["total"] == "116.00"  # solo el shampoo que no se cambió


def test_cambio_sin_productos_nuevos(como_admin, caja, shampoo):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    assert cambiar(como_admin, v, caja, [pieza(v, 0, 1)], []).status_code == 422


def test_cambio_solo_admin(como_mostrador, caja, shampoo, amoxicilina):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    assert cambiar(como_mostrador, v, caja, [pieza(v, 0, 1)], [r(amoxicilina, 1)]).status_code == 403


def test_ticket_del_cambio(como_admin, caja, shampoo, amoxicilina):
    v = vender(como_admin, caja, [r(amoxicilina, 2)], efectivo="171").json()
    c = cambiar(como_admin, v, caja, [pieza(v, 0, 2)], [r(shampoo, 1)]).json()
    texto = como_admin.get(f"/ventas/{c['venta']['id']}/ticket").text
    assert f"CAMBIO DE PRODUCTO (folio {v['folio']})" in texto
    assert "Saldo por producto devuelto" in texto and "$116.00" in texto
    assert "Diferencia a su favor" in texto and "$55.00" in texto
