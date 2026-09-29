"""Inventario por lote: FEFO, captura de caducidades, ajustes, mermas,
permisos, bitácora y avance de la migración."""

from decimal import Decimal as D

import pytest

from app.models import AjusteInventario, Categoria, Lote, Producto


@pytest.fixture
def medicamento(db, negocio) -> Producto:
    """Producto con 10 piezas heredadas (lote sin caducidad)."""
    p = Producto(negocio_id=negocio.id, nombre="AMOXICILINA 500MG", clave="111", costo=D("10.5"))
    db.add(p)
    db.commit()
    db.add(Lote(negocio_id=negocio.id, producto_id=p.id, cantidad=D(10), costo_unitario=D("10.5")))
    db.commit()
    return p


@pytest.fixture
def dulce(db, negocio) -> Producto:
    """Producto de una categoría que no controla lote."""
    cat = Categoria(negocio_id=negocio.id, nombre="Dulces", controla_lote=False)
    db.add(cat)
    db.commit()
    p = Producto(negocio_id=negocio.id, nombre="CHICLE", clave="222", categoria_id=cat.id)
    db.add(p)
    db.commit()
    db.add(Lote(negocio_id=negocio.id, producto_id=p.id, cantidad=D(50)))
    db.commit()
    return p


def capturar(cliente, producto, caducidad, cantidad, numero_lote=None):
    return cliente.post("/inventario/captura-caducidad", json={
        "producto_id": producto.id, "caducidad": caducidad, "cantidad": str(cantidad), "numero_lote": numero_lote,
    })


def ajustar(cliente, producto, tipo, cantidad, motivo="conteo físico", lote_id=None):
    return cliente.post("/inventario/ajustes", json={
        "producto_id": producto.id, "tipo": tipo, "cantidad": str(cantidad), "motivo": motivo, "lote_id": lote_id,
    })


def existencia(cliente, producto):
    return cliente.get(f"/inventario/productos/{producto.id}").json()


# --- Captura de caducidades ---------------------------------------------

def test_captura_mueve_piezas_y_ordena_fefo(como_mostrador, medicamento):
    assert capturar(como_mostrador, medicamento, "2027-03-31", 3, "A").status_code == 201
    assert capturar(como_mostrador, medicamento, "2027-01-31", 2).status_code == 201

    e = existencia(como_mostrador, medicamento)
    assert e["existencia"] == "10.00"  # capturar no cambia el total
    assert e["sin_caducidad"] == "5.00"
    # FEFO: primero el que caduca antes; sin caducidad al final.
    assert [(l["caducidad"], l["cantidad"]) for l in e["lotes"]] == [
        ("2027-01-31", "2.00"), ("2027-03-31", "3.00"), (None, "5.00"),
    ]


def test_misma_caducidad_y_lote_se_suman(como_mostrador, medicamento):
    capturar(como_mostrador, medicamento, "2027-03-31", 3, "A")
    r = capturar(como_mostrador, medicamento, "2027-03-31", 1, " A ")  # espacios se ignoran
    assert r.json()["cantidad"] == "4.00"
    assert len(existencia(como_mostrador, medicamento)["lotes"]) == 2


def test_lote_capturado_hereda_el_costo(como_mostrador, medicamento):
    assert capturar(como_mostrador, medicamento, "2027-03-31", 1).json()["costo_unitario"] == "10.5000"


def test_no_se_captura_mas_de_lo_que_hay(como_mostrador, medicamento):
    r = capturar(como_mostrador, medicamento, "2027-03-31", 11)
    assert r.status_code == 409
    assert "Solo hay 10.00" in r.json()["detail"]


def test_captura_genera_dos_ajustes_a_nombre_del_usuario(como_mostrador, mostrador, medicamento, db):
    capturar(como_mostrador, medicamento, "2027-03-31", 3)
    ajustes = db.query(AjusteInventario).filter_by(producto_id=medicamento.id).all()
    assert sorted(a.cantidad for a in ajustes) == [D(-3), D(3)]
    assert {a.usuario_id for a in ajustes} == {mostrador.id}


def test_categoria_sin_control_de_lote_no_acepta_caducidad(como_admin, dulce):
    r = capturar(como_admin, dulce, "2027-01-01", 1)
    assert r.status_code == 409
    assert existencia(como_admin, dulce)["controla_lote"] is False


def test_cantidad_cero_o_negativa_en_captura(como_admin, medicamento):
    assert capturar(como_admin, medicamento, "2027-01-01", 0).status_code == 422
    assert capturar(como_admin, medicamento, "2027-01-01", -1).status_code == 422


# --- Ajustes y mermas ----------------------------------------------------

def test_merma_de_un_lote(como_bodega, medicamento):
    lote = capturar(como_bodega, medicamento, "2027-01-31", 2).json()
    r = ajustar(como_bodega, medicamento, "merma", -1, "caja dañada", lote["id"])
    assert r.status_code == 201
    assert r.json()["tipo"] == "merma"
    assert existencia(como_bodega, medicamento)["existencia"] == "9.00"


def test_merma_positiva_se_rechaza(como_bodega, medicamento):
    assert ajustar(como_bodega, medicamento, "merma", 1).status_code == 409


def test_ningun_lote_queda_negativo(como_bodega, medicamento):
    r = ajustar(como_bodega, medicamento, "ajuste", -11)
    assert r.status_code == 409
    assert existencia(como_bodega, medicamento)["existencia"] == "10.00"


def test_conteo_fisico_de_producto_sin_existencia(como_admin, db, negocio):
    """Los negativos de PVWin entran en cero y sin lote; el conteo crea el lote."""
    p = Producto(negocio_id=negocio.id, nombre="ERA NEGATIVO")
    db.add(p)
    db.commit()
    assert ajustar(como_admin, p, "ajuste", 7).status_code == 201
    e = existencia(como_admin, p)
    assert e["existencia"] == "7.00"
    assert e["sin_caducidad"] == "7.00"


def test_quitar_sin_lote_a_producto_sin_existencia(como_admin, db, negocio):
    p = Producto(negocio_id=negocio.id, nombre="VACIO")
    db.add(p)
    db.commit()
    assert ajustar(como_admin, p, "ajuste", -1).status_code == 409


@pytest.mark.parametrize("motivo", ["", "   "])
def test_motivo_obligatorio(como_admin, medicamento, motivo):
    assert ajustar(como_admin, medicamento, "ajuste", 1, motivo).status_code in (409, 422)


def test_cantidad_cero_en_ajuste(como_admin, medicamento):
    assert ajustar(como_admin, medicamento, "ajuste", 0).status_code == 409


def test_tipo_no_permitido(como_admin, medicamento):
    assert ajustar(como_admin, medicamento, "importacion", 1).status_code == 422


def test_lote_de_otro_producto(como_admin, medicamento, dulce, db):
    lote_dulce = db.query(Lote).filter_by(producto_id=dulce.id).one()
    assert ajustar(como_admin, medicamento, "ajuste", -1, lote_id=lote_dulce.id).status_code == 404


def test_mostrador_no_hace_ajustes(como_mostrador, medicamento):
    assert ajustar(como_mostrador, medicamento, "ajuste", 1).status_code == 403
    assert ajustar(como_mostrador, medicamento, "merma", -1).status_code == 403


# --- Consultas -----------------------------------------------------------

def test_bitacora_filtra_y_ordena(como_admin, medicamento):
    capturar(como_admin, medicamento, "2027-01-31", 2)
    ajustar(como_admin, medicamento, "merma", -1, "rota")
    todos = como_admin.get("/inventario/ajustes", params={"producto_id": medicamento.id}).json()
    assert [a["tipo"] for a in todos] == ["merma", "captura_caducidad", "captura_caducidad"]
    mermas = como_admin.get("/inventario/ajustes", params={"tipo": "merma"}).json()
    assert [a["motivo"] for a in mermas] == ["rota"]


def test_avance_de_caducidades(como_admin, medicamento, dulce):
    capturar(como_admin, medicamento, "2027-01-31", 4)
    a = como_admin.get("/inventario/avance-caducidades").json()
    # El dulce no cuenta: su categoría no controla lote.
    assert a["piezas_total"] == "10.00"
    assert a["piezas_sin_caducidad"] == "6.00"
    assert a["porcentaje_capturado"] == "40.0"
    assert a["productos_pendientes"] == 1
    assert [p["nombre"] for p in a["productos"]] == ["AMOXICILINA 500MG"]


def test_avance_sin_inventario(como_admin):
    a = como_admin.get("/inventario/avance-caducidades").json()
    assert a["piezas_total"] == "0"
    assert a["porcentaje_capturado"] == "100"


def test_inventario_de_otro_negocio_es_invisible(como_admin, db, otro_negocio):
    ajeno = Producto(negocio_id=otro_negocio.id, nombre="AJENO")
    db.add(ajeno)
    db.commit()
    db.add(Lote(negocio_id=otro_negocio.id, producto_id=ajeno.id, cantidad=D(5)))
    db.commit()
    assert como_admin.get(f"/inventario/productos/{ajeno.id}").status_code == 404
    assert capturar(como_admin, ajeno, "2027-01-01", 1).status_code == 404
    assert ajustar(como_admin, ajeno, "ajuste", 1).status_code == 404
    assert como_admin.get("/inventario/avance-caducidades").json()["piezas_total"] == "0"


# --- Pantalla de inventario: conteo total, movimientos, por caducar ----------

def test_conteo_total_del_producto(como_admin, admin, medicamento):
    capturar(como_admin, medicamento, "2027-03-31", 4, "A")  # A=4, sin caducidad=6
    r = como_admin.post("/inventario/conteo", json={"producto_id": medicamento.id, "conteo": "7"})
    assert r.status_code == 200
    e = r.json()
    assert (e["existencia"], e["existencia_registrada"], e["sin_caducidad"]) == ("7.00", "7.00", "3.00")
    [m] = [m for m in como_admin.get(f"/inventario/productos/{medicamento.id}/movimientos").json() if m["tipo"] == "ajuste"]
    assert (m["cantidad"], m["motivo"], m["usuario"]) == ("-3.00", "Conteo físico", admin.nombre_completo)


def test_conteo_solo_admin_y_bodega(como_mostrador, como_bodega, medicamento):
    assert como_mostrador.post("/inventario/conteo", json={"producto_id": medicamento.id, "conteo": "1"}).status_code == 403
    assert como_bodega.post("/inventario/conteo", json={"producto_id": medicamento.id, "conteo": "1"}).status_code == 200
    assert como_bodega.post("/inventario/conteo", json={"producto_id": medicamento.id, "conteo": "-1"}).status_code == 422


def test_movimientos_con_lote_y_usuario(como_admin, medicamento):
    capturar(como_admin, medicamento, "2027-03-31", 2, "A")
    movs = como_admin.get(f"/inventario/productos/{medicamento.id}/movimientos").json()
    assert [(m["tipo"], m["cantidad"], m["numero_lote"]) for m in movs] == [
        ("captura_caducidad", "2.00", "A"), ("captura_caducidad", "-2.00", None),
    ]


def test_por_caducar(como_admin, db, negocio, medicamento):
    from datetime import date, timedelta
    hoy = date.today()
    for dias, num in ((-10, "VENCIDO"), (30, "PRONTO"), (400, "LEJOS")):
        db.add(Lote(negocio_id=negocio.id, producto_id=medicamento.id, cantidad=D(2),
                    caducidad=hoy + timedelta(days=dias), numero_lote=num))
    db.add(Lote(negocio_id=negocio.id, producto_id=medicamento.id, cantidad=D(0),
                caducidad=hoy + timedelta(days=5), numero_lote="VACIO"))
    db.commit()
    lista = como_admin.get("/inventario/por-caducar", params={"meses": 6}).json()
    assert [(l["numero_lote"], l["dias"] < 0) for l in lista] == [("VENCIDO", True), ("PRONTO", False)]
    assert lista[1]["nombre"] == "AMOXICILINA 500MG"
