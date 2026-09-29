"""Cajas, apertura y cierre de turno, corte de caja."""

import pytest

from app.models import Caja


@pytest.fixture
def caja(db, negocio) -> Caja:
    c = Caja(negocio_id=negocio.id, nombre="Mostrador 1")
    db.add(c)
    db.commit()
    return c


def abrir(cliente, caja, fondo="500", tipo="manana"):
    return cliente.post("/turnos", json={"caja_id": caja.id, "tipo": tipo, "fondo_inicial": fondo})


def cerrar(cliente, turno_id, efectivo, tarjeta="0", notas=None):
    return cliente.post(f"/turnos/{turno_id}/cerrar", json={
        "efectivo_contado": efectivo, "tarjeta_contado": tarjeta, "notas": notas,
    })


# --- Cajas -----------------------------------------------------------------

def test_admin_crea_cajas(como_admin):
    r = como_admin.post("/cajas", json={"nombre": "Mostrador 2"})
    assert r.status_code == 201
    assert como_admin.post("/cajas", json={"nombre": "Mostrador 2"}).status_code == 409


def test_solo_admin_crea_cajas(como_mostrador):
    assert como_mostrador.post("/cajas", json={"nombre": "x"}).status_code == 403


def test_caja_de_otro_negocio_es_invisible(como_mostrador, db, otro_negocio):
    ajena = Caja(negocio_id=otro_negocio.id, nombre="Ajena")
    db.add(ajena)
    db.commit()
    assert como_mostrador.get("/cajas").json() == []
    assert abrir(como_mostrador, ajena).status_code == 404


# --- Abrir -----------------------------------------------------------------

def test_abrir_turno(como_mostrador, mostrador, caja):
    r = abrir(como_mostrador, caja, "500")
    assert r.status_code == 201
    t = r.json()
    assert (t["fondo_inicial"], t["abierto_por_id"], t["cerrado_en"]) == ("500.00", mostrador.id, None)
    assert como_mostrador.get("/turnos/abierto", params={"caja_id": caja.id}).json()["id"] == t["id"]


def test_sin_turno_abierto_regresa_null(como_mostrador, caja):
    assert como_mostrador.get("/turnos/abierto", params={"caja_id": caja.id}).json() is None


def test_un_solo_turno_abierto_por_caja(como_mostrador, como_admin, caja):
    assert abrir(como_mostrador, caja).status_code == 201
    r = abrir(como_admin, caja)
    assert r.status_code == 409
    assert "ya tiene un turno abierto" in r.json()["detail"]


def test_cada_caja_tiene_su_turno(como_mostrador, db, negocio, caja):
    otra = Caja(negocio_id=negocio.id, nombre="Mostrador 2")
    db.add(otra)
    db.commit()
    assert abrir(como_mostrador, caja).status_code == 201
    assert abrir(como_mostrador, otra).status_code == 201


def test_bodega_no_abre_turno(como_bodega, caja):
    assert abrir(como_bodega, caja).status_code == 403


def test_fondo_negativo(como_mostrador, caja):
    assert abrir(como_mostrador, caja, "-1").status_code == 422


def test_caja_desactivada(como_admin, caja):
    como_admin.put(f"/cajas/{caja.id}", json={"activa": False})
    assert abrir(como_admin, caja).status_code == 409


# --- Corte y cierre --------------------------------------------------------

def test_corte_muestra_lo_esperado(como_mostrador, caja):
    t = abrir(como_mostrador, caja, "500").json()
    c = como_mostrador.get(f"/turnos/{t['id']}/corte").json()
    assert (c["efectivo_esperado"], c["tarjeta_esperado"]) == ("500.00", "0")


def test_cerrar_con_faltante(como_mostrador, mostrador, caja):
    t = abrir(como_mostrador, caja, "500").json()
    r = cerrar(como_mostrador, t["id"], "480", notas="  faltó un billete  ")
    assert r.status_code == 200
    c = r.json()
    assert c["efectivo_esperado"] == "500.00"
    assert c["efectivo_contado"] == "480.00"
    assert c["diferencia_efectivo"] == "-20.00"  # negativo = faltante
    assert c["cerrado_por_id"] == mostrador.id
    assert c["notas_cierre"] == "faltó un billete"


def test_cerrar_con_sobrante(como_mostrador, caja):
    t = abrir(como_mostrador, caja, "500").json()
    assert cerrar(como_mostrador, t["id"], "510").json()["diferencia_efectivo"] == "10.00"


def test_otro_cajero_puede_cerrar(como_mostrador, como_admin, admin, caja):
    t = abrir(como_mostrador, caja).json()
    assert cerrar(como_admin, t["id"], "500").json()["cerrado_por_id"] == admin.id


def test_no_se_cierra_dos_veces(como_mostrador, caja):
    t = abrir(como_mostrador, caja).json()
    cerrar(como_mostrador, t["id"], "500")
    assert cerrar(como_mostrador, t["id"], "500").status_code == 409


def test_tras_cerrar_se_puede_abrir_otro(como_mostrador, caja):
    t = abrir(como_mostrador, caja, tipo="manana").json()
    cerrar(como_mostrador, t["id"], "500")
    assert abrir(como_mostrador, caja, tipo="tarde").status_code == 201


def test_contado_negativo(como_mostrador, caja):
    t = abrir(como_mostrador, caja).json()
    assert cerrar(como_mostrador, t["id"], "-5").status_code == 422


def test_bodega_no_cierra_turno(como_mostrador, como_bodega, caja):
    t = abrir(como_mostrador, caja).json()
    assert cerrar(como_bodega, t["id"], "500").status_code == 403


def test_historial_solo_admin(como_mostrador, como_admin, caja):
    t = abrir(como_mostrador, caja).json()
    cerrar(como_mostrador, t["id"], "500")
    assert como_mostrador.get("/turnos").status_code == 403
    assert [x["id"] for x in como_admin.get("/turnos").json()] == [t["id"]]


def test_turno_de_otro_negocio(como_admin, cliente_de, crear_usuario, otro_negocio, db):
    caja_ajena = Caja(negocio_id=otro_negocio.id, nombre="Ajena")
    db.add(caja_ajena)
    db.commit()
    ajeno = cliente_de(crear_usuario(otro_negocio))
    t = abrir(ajeno, caja_ajena).json()
    assert como_admin.get(f"/turnos/{t['id']}/corte").status_code == 404
    assert cerrar(como_admin, t["id"], "0").status_code == 404
