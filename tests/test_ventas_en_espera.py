"""Ventas en espera: guardar una venta a medias (máximo 5 por caja),
retomarla, borrarla, y que no se pueda hacer el corte mientras haya alguna."""

from decimal import Decimal as D

import pytest

from app.models import Caja, Lote, Producto, TipoTurno, Turno


@pytest.fixture
def caja(db, negocio, admin) -> Caja:
    c = Caja(negocio_id=negocio.id, nombre="Mostrador 1")
    db.add(c)
    db.commit()
    db.add(Turno(negocio_id=negocio.id, caja_id=c.id, tipo=TipoTurno.MANANA, fondo_inicial=D(500), abierto_por_id=admin.id))
    db.commit()
    return c


@pytest.fixture
def shampoo(db, negocio) -> Producto:
    p = Producto(negocio_id=negocio.id, nombre="SHAMPOO 400ML", precio_venta=D("116.00"))
    db.add(p)
    db.commit()
    db.add(Lote(negocio_id=negocio.id, producto_id=p.id, cantidad=D(20)))
    db.commit()
    return p


def guardar(cliente, caja, producto, cantidad="2", nota=None, **extra):
    return cliente.post("/ventas-en-espera", json={
        "caja_id": caja.id, "nota": nota,
        "renglones": [{"producto_id": producto.id, "cantidad": cantidad, **extra}],
    })


def lista(cliente, caja):
    return cliente.get("/ventas-en-espera", params={"caja_id": caja.id}).json()


def test_guardar_y_listar(como_mostrador, mostrador, caja, shampoo):
    r = guardar(como_mostrador, caja, shampoo, "2", "señora de lentes", caducidad_mes="2027-03", numero_lote=" A1 ")
    assert r.status_code == 201
    v = r.json()
    assert (v["total"], v["articulos"], v["nota"], v["usuario_id"]) == ("232.00", "2.00", "señora de lentes", mostrador.id)
    assert v["renglones"] == [{"producto_id": shampoo.id, "cantidad": "2", "lote_id": None,
                               "caducidad_mes": "2027-03", "numero_lote": "A1"}]
    assert [x["id"] for x in lista(como_mostrador, caja)] == [v["id"]]


def test_no_aparta_existencia(como_mostrador, caja, shampoo, db):
    guardar(como_mostrador, caja, shampoo, "5")
    db.expire_all()
    assert db.query(Lote).filter_by(producto_id=shampoo.id).one().cantidad == 20


def test_maximo_5_por_caja(como_mostrador, caja, shampoo, db, negocio):
    for _ in range(5):
        assert guardar(como_mostrador, caja, shampoo).status_code == 201
    r = guardar(como_mostrador, caja, shampoo)
    assert r.status_code == 409
    assert "Ya hay 5 ventas guardadas" in r.json()["detail"]
    # Otra caja tiene su propio límite.
    otra = Caja(negocio_id=negocio.id, nombre="Mostrador 2")
    db.add(otra)
    db.commit()
    assert guardar(como_mostrador, otra, shampoo).status_code == 201


def test_retomar_la_saca_de_la_lista(como_mostrador, caja, shampoo):
    v = guardar(como_mostrador, caja, shampoo).json()
    r = como_mostrador.post(f"/ventas-en-espera/{v['id']}/retomar")
    assert r.status_code == 200
    assert r.json()["renglones"][0]["producto_id"] == shampoo.id
    assert lista(como_mostrador, caja) == []
    # Si dos computadoras la retoman a la vez, solo una se la lleva.
    assert como_mostrador.post(f"/ventas-en-espera/{v['id']}/retomar").status_code == 404


def test_borrar(como_mostrador, caja, shampoo):
    v = guardar(como_mostrador, caja, shampoo).json()
    assert como_mostrador.delete(f"/ventas-en-espera/{v['id']}").status_code == 204
    assert lista(como_mostrador, caja) == []
    assert como_mostrador.delete(f"/ventas-en-espera/{v['id']}").status_code == 404


def test_no_hay_corte_con_ventas_guardadas(como_mostrador, caja, shampoo, db):
    turno = db.query(Turno).filter_by(caja_id=caja.id).one()
    v = guardar(como_mostrador, caja, shampoo).json()
    r = como_mostrador.post(f"/turnos/{turno.id}/cerrar", json={"efectivo_contado": "500", "tarjeta_contado": "0"})
    assert r.status_code == 409
    assert "Hay 1 venta guardada" in r.json()["detail"]
    como_mostrador.delete(f"/ventas-en-espera/{v['id']}")
    r = como_mostrador.post(f"/turnos/{turno.id}/cerrar", json={"efectivo_contado": "500", "tarjeta_contado": "0"})
    assert r.status_code == 200


def test_bodega_no_guarda_ventas(como_bodega, caja, shampoo):
    assert guardar(como_bodega, caja, shampoo).status_code == 403


@pytest.mark.parametrize("renglones", [[], [{"producto_id": 1, "cantidad": "0"}], [{"producto_id": 1, "cantidad": "1", "caducidad_mes": "03/2027"}]])
def test_datos_invalidos(como_mostrador, caja, renglones):
    r = como_mostrador.post("/ventas-en-espera", json={"caja_id": caja.id, "renglones": renglones})
    assert r.status_code == 422


def test_otro_negocio_no_ve_ni_toca(como_mostrador, caja, shampoo, otro_negocio, crear_usuario, cliente_de):
    v = guardar(como_mostrador, caja, shampoo).json()
    ajeno = cliente_de(crear_usuario(otro_negocio))
    assert ajeno.get("/ventas-en-espera", params={"caja_id": caja.id}).status_code == 404
    assert ajeno.post(f"/ventas-en-espera/{v['id']}/retomar").status_code == 404
    assert ajeno.delete(f"/ventas-en-espera/{v['id']}").status_code == 404
    # Ni guardar productos de otro negocio en su caja.
    assert guardar(ajeno, caja, shampoo).status_code == 404
