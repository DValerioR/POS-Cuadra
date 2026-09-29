"""Avisos de ventas sin existencia registrada: el administrador cuenta lo que
hay en anaquel y la existencia se ajusta a ese número."""

from datetime import date
from decimal import Decimal as D

from app.models import AjusteInventario, TipoAjuste
from tests.test_devoluciones import devolver, pieza
from tests.test_ventas import amoxicilina, caja, existencias, producto, r, vender  # noqa: F401  (fixtures)


def avisos(cliente, **params):
    return cliente.get("/avisos-inventario", params=params).json()


def test_el_admin_ve_el_aviso(como_mostrador, como_admin, mostrador, caja, db, negocio):
    p = producto(db, negocio, "AGOTADO", "10", [(1, None, None)])
    v = vender(como_mostrador, caja, [r(p, 3)], efectivo="30").json()
    [a] = avisos(como_admin, estado="pendiente")
    assert (a["producto"], a["folio"], a["caja"], a["vendio"]) == ("AGOTADO", v["folio"], "Mostrador 1", mostrador.nombre_completo)
    assert (a["vendidas"], a["faltantes"], a["existencia_actual"]) == ("3.00", "2.00", "-2.00")
    assert como_admin.get("/notificaciones/pendientes").json() == {"solicitudes": 0, "inventario": 1, "total": 1}


def test_conteo_ajusta_la_existencia_y_cierra_los_avisos_del_producto(como_mostrador, como_admin, admin, caja, db, negocio):
    p = producto(db, negocio, "AGOTADO", "10", [(1, None, None)])
    vender(como_mostrador, caja, [r(p, 2)], efectivo="20")
    vender(como_mostrador, caja, [r(p, 1)], efectivo="10")
    pendientes = avisos(como_admin, estado="pendiente")
    assert len(pendientes) == 2

    res = como_admin.post(f"/avisos-inventario/{pendientes[0]['id']}/conteo", json={"conteo": "5"})
    assert res.status_code == 200
    assert [a["estado"] for a in res.json()] == ["revisado", "revisado"]
    assert res.json()[0]["conteo"] == "5.00"
    assert existencias(db, p) == {(None, None): D(5)}
    ajuste = db.query(AjusteInventario).filter_by(producto_id=p.id, tipo=TipoAjuste.AJUSTE).one()
    assert (ajuste.cantidad, ajuste.usuario_id) == (D(7), admin.id)  # de -2 a 5
    assert "venta sin existencia" in ajuste.motivo
    assert avisos(como_admin, estado="pendiente") == []


def test_conteo_menor_que_los_lotes_quita_primero_lo_que_caduca_antes(como_mostrador, como_admin, caja, db, negocio):
    p = producto(db, negocio, "DOS LOTES", "10", [(3, date(2027, 1, 31), "A"), (4, date(2027, 6, 30), "B"), (0, None, None)])
    sin_caducidad = next(l for l in p_lotes(db, p) if l.caducidad is None)
    # El vendedor dice que entregó piezas "sin caducidad" que el sistema no tenía.
    vender(como_mostrador, caja, [r(p, 2, lote_id=sin_caducidad.id)], efectivo="20")
    [a] = avisos(como_admin, estado="pendiente")
    como_admin.post(f"/avisos-inventario/{a['id']}/conteo", json={"conteo": "5"})
    assert existencias(db, p) == {("A", date(2027, 1, 31)): D(1), ("B", date(2027, 6, 30)): D(4), (None, None): D(0)}


def p_lotes(db, p):
    from app.models import Lote
    return db.query(Lote).filter_by(producto_id=p.id).all()


def test_conteo_mayor_que_los_lotes_va_al_sin_caducidad(como_admin, db, negocio, como_mostrador, caja):
    p = producto(db, negocio, "CON LOTE", "10", [(2, date(2027, 5, 31), "X")])
    vender(como_mostrador, caja, [r(p, 3)], efectivo="30")  # X queda en 0, sin caducidad en -1
    [a] = avisos(como_admin, estado="pendiente")
    como_admin.post(f"/avisos-inventario/{a['id']}/conteo", json={"conteo": "6"})
    assert existencias(db, p) == {("X", date(2027, 5, 31)): D(0), (None, None): D(6)}


def test_marcar_revisado_sin_contar(como_mostrador, como_admin, caja, db, negocio):
    p = producto(db, negocio, "AGOTADO", "10")
    vender(como_mostrador, caja, [r(p, 1)], efectivo="10")
    [a] = avisos(como_admin, estado="pendiente")
    res = como_admin.post(f"/avisos-inventario/{a['id']}/revisado")
    assert (res.json()[0]["estado"], res.json()[0]["conteo"]) == ("revisado", None)
    assert existencias(db, p) == {(None, None): D(-1)}  # no se tocó
    assert como_admin.post(f"/avisos-inventario/{a['id']}/revisado").status_code == 409


def test_solo_admin(como_mostrador, como_bodega, caja, db, negocio):
    p = producto(db, negocio, "AGOTADO", "10")
    vender(como_mostrador, caja, [r(p, 1)], efectivo="10")
    for cliente in (como_mostrador, como_bodega):
        assert cliente.get("/avisos-inventario").status_code == 403
        assert cliente.get("/notificaciones/pendientes").status_code == 403
        assert cliente.post("/avisos-inventario/1/conteo", json={"conteo": "1"}).status_code == 403


def test_conteo_negativo_no(como_mostrador, como_admin, caja, db, negocio):
    p = producto(db, negocio, "AGOTADO", "10")
    vender(como_mostrador, caja, [r(p, 1)], efectivo="10")
    [a] = avisos(como_admin, estado="pendiente")
    assert como_admin.post(f"/avisos-inventario/{a['id']}/conteo", json={"conteo": "-1"}).status_code == 422


def test_devolucion_de_venta_sin_existencia_regresa_al_mismo_lote(como_admin, caja, db, negocio):
    p = producto(db, negocio, "AGOTADO", "10")
    v = vender(como_admin, caja, [r(p, 2)], efectivo="20").json()
    assert devolver(como_admin, v, caja, [pieza(v, 0, 2)]).status_code == 201
    assert existencias(db, p) == {(None, None): D(0)}
