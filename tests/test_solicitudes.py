"""Solicitudes de devolución y cancelación: el cajero las pide, un
administrador las autoriza (o rechaza) desde el centro de notificaciones, y
al autorizarse el dinero sale del turno de la caja que la pidió."""

from decimal import Decimal as D

from app.models import Turno
from tests.test_devoluciones import corte, pieza
from tests.test_ventas import amoxicilina, caja, existencias, r, shampoo, vender  # noqa: F401  (fixtures)


def pedir(cliente, venta, caja, tipo="devolucion", piezas=None, motivo="producto equivocado"):
    return cliente.post(f"/ventas/{venta['id']}/solicitudes", json={
        "caja_id": caja.id, "tipo": tipo, "motivo": motivo, "piezas": piezas or [],
    })


def autorizar(cliente, solicitud):
    return cliente.post(f"/solicitudes/{solicitud['id']}/autorizar")


def test_cajero_pide_devolucion_y_no_se_mueve_nada(como_mostrador, mostrador, caja, shampoo, db):
    v = vender(como_mostrador, caja, [r(shampoo, 3)], efectivo="348").json()
    res = pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 2)])
    assert res.status_code == 201
    s = res.json()
    assert (s["estado"], s["tipo"], s["folio"], s["total"], s["efectivo"], s["tarjeta"]) == (
        "pendiente", "devolucion", v["folio"], "232.00", "232.00", "0.00")
    assert s["piezas"] == [{"renglon_id": v["renglones"][0]["id"], "nombre": "SHAMPOO 400ML", "cantidad": "2", "importe": "232.00"}]
    assert s["solicitada_por"] == mostrador.nombre_completo
    # Nada regresó todavía: ni piezas ni dinero.
    assert existencias(db, shampoo)[(None, None)] == D(17)
    assert D(corte(como_mostrador, db, caja)["reembolsos_efectivo"]) == 0


def test_admin_autoriza_y_se_hace_en_la_caja_que_la_pidio(como_mostrador, como_admin, admin, caja, shampoo, db):
    v = vender(como_mostrador, caja, [r(shampoo, 3)], efectivo="348").json()
    s = pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 2)]).json()
    assert como_admin.get("/solicitudes/pendientes").json() == {"pendientes": 1}

    res = autorizar(como_admin, s)
    assert res.status_code == 200
    s = res.json()
    assert (s["estado"], s["resuelta_por"], s["efectivo"]) == ("autorizada", admin.nombre_completo, "232.00")
    assert existencias(db, shampoo)[(None, None)] == D(19)
    assert corte(como_mostrador, db, caja)["reembolsos_efectivo"] == "232.00"
    assert como_admin.get("/solicitudes/pendientes").json() == {"pendientes": 0}
    # La devolución queda registrada como hecha por el administrador que autorizó.
    devolucion = como_admin.get(f"/ventas/{v['id']}").json()["devoluciones"][0]
    assert devolucion["usuario_id"] == admin.id


def test_cancelacion_por_solicitud(como_mostrador, como_admin, caja, shampoo, db):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], tarjeta="116").json()
    s = pedir(como_mostrador, v, caja, tipo="cancelacion", piezas=[pieza(v, 0, 1)]).json()
    assert (s["total"], s["tarjeta"], s["piezas"]) == ("116.00", "116.00", [])  # en cancelación no van piezas
    autorizar(como_admin, s)
    assert como_admin.get(f"/ventas/{v['id']}").json()["estado"] == "cancelada"


def test_rechazar(como_mostrador, como_admin, caja, shampoo, db):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    s = pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 1)]).json()
    res = como_admin.post(f"/solicitudes/{s['id']}/rechazar", json={"respuesta": "  la caja viene abierta "})
    assert (res.json()["estado"], res.json()["respuesta"]) == ("rechazada", "la caja viene abierta")
    assert existencias(db, shampoo)[(None, None)] == D(19)
    # Ya respondida: no se puede autorizar ni rechazar otra vez.
    assert autorizar(como_admin, s).status_code == 409
    assert "ya la rechazó" in autorizar(como_admin, s).json()["detail"]


def test_solo_admin_responde_y_ve_el_centro(como_mostrador, como_bodega, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    s = pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 1)]).json()
    for cliente in (como_mostrador, como_bodega):
        assert autorizar(cliente, s).status_code == 403
        assert cliente.post(f"/solicitudes/{s['id']}/rechazar", json={}).status_code == 403
        assert cliente.get("/solicitudes").status_code == 403
        assert cliente.get("/solicitudes/pendientes").status_code == 403
    assert pedir(como_bodega, v, caja, piezas=[pieza(v, 0, 1)]).status_code == 403


def test_una_sola_pendiente_por_venta(como_mostrador, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 2)], efectivo="232").json()
    assert pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 1)]).status_code == 201
    res = pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 1)])
    assert res.status_code == 409
    assert "Ya hay una solicitud pendiente" in res.json()["detail"]


def test_se_valida_al_pedir(como_mostrador, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    assert pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 5)]).status_code == 409  # más de lo vendido
    assert pedir(como_mostrador, v, caja, piezas=[]).status_code == 409  # sin piezas
    assert pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 1)], motivo="").status_code == 422
    assert pedir(como_mostrador, v, caja, tipo="cambio", piezas=[pieza(v, 0, 1)]).status_code == 422


def test_si_ya_no_se_puede_la_solicitud_sigue_pendiente(como_mostrador, como_admin, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    s = pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 1)]).json()
    # Mientras tanto un administrador cancela la venta en la caja.
    como_admin.post(f"/ventas/{v['id']}/cancelar", json={"caja_id": caja.id, "motivo": "x"})
    res = autorizar(como_admin, s)
    assert res.status_code == 409
    assert como_admin.get("/solicitudes", params={"estado": "pendiente"}).json()[0]["id"] == s["id"]


def test_el_cajero_ve_la_respuesta_hasta_marcarla(como_mostrador, como_admin, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    s = pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 1)]).json()
    de_caja = lambda: como_mostrador.get(f"/solicitudes/caja/{caja.id}").json()  # noqa: E731
    assert [x["estado"] for x in de_caja()] == ["pendiente"]
    assert como_mostrador.post(f"/solicitudes/{s['id']}/vista").status_code == 409  # sin respuesta aún
    autorizar(como_admin, s)
    assert [x["estado"] for x in de_caja()] == ["autorizada"]
    assert como_mostrador.post(f"/solicitudes/{s['id']}/vista").status_code == 200
    assert de_caja() == []


def test_no_hay_corte_con_solicitudes_pendientes(como_mostrador, como_admin, caja, shampoo, db):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    s = pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 1)]).json()
    turno = db.query(Turno).filter_by(caja_id=caja.id, cerrado_en=None).one()
    cerrar = lambda: como_mostrador.post(  # noqa: E731
        f"/turnos/{turno.id}/cerrar", json={"efectivo_contado": "500", "tarjeta_contado": "0"})
    res = cerrar()
    assert res.status_code == 409
    assert "esperando respuesta del administrador" in res.json()["detail"]
    autorizar(como_admin, s)
    assert cerrar().status_code == 200


def test_otro_negocio_no_ve_ni_responde(como_mostrador, caja, shampoo, otro_negocio, crear_usuario, cliente_de):
    from app.models import RolUsuario
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    s = pedir(como_mostrador, v, caja, piezas=[pieza(v, 0, 1)]).json()
    ajeno = cliente_de(crear_usuario(otro_negocio, RolUsuario.ADMIN))
    assert ajeno.get("/solicitudes").json() == []
    assert autorizar(ajeno, s).status_code == 404


def test_mostrador_busca_ventas_por_folio_y_las_de_hoy(como_mostrador, como_bodega, caja, shampoo):
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    assert [x["id"] for x in como_mostrador.get("/ventas", params={"folio": v["folio"]}).json()] == [v["id"]]
    assert [x["id"] for x in como_mostrador.get("/ventas").json()] == [v["id"]]
    assert [x["id"] for x in como_mostrador.get("/ventas", params={"desde": "2000-01-01"}).json()] == [v["id"]]
    assert como_bodega.get("/ventas").status_code == 403
