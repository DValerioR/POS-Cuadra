"""Encargos: productos "solo por encargo" (sin mínimo ni máximo, fuera de
faltantes) y encargos de clientes (por pedir -> pedido -> llegó ->
entregado), que pasan solos a "pedido" al enviar el pedido al proveedor."""

from decimal import Decimal as D

import pytest

from app.models import Encargo, EstadoEncargo, Producto, Proveedor
from app.whatsapp import cliente as whatsapp


def _producto(db, negocio, nombre, **extra):
    p = Producto(negocio_id=negocio.id, nombre=nombre, precio_venta=D(100), **extra)
    db.add(p)
    db.commit()
    return p


def test_producto_encargo_sin_minimo_ni_maximo(como_admin, db, negocio):
    p = _producto(db, negocio, "HUMIRA PLUMA 40MG", minimo=D(1), maximo=D(3))
    r = como_admin.put(f"/productos/{p.id}", json={"encargo": True})
    assert r.status_code == 200
    assert (r.json()["encargo"], r.json()["minimo"], r.json()["maximo"]) == (True, None, None)
    # Aunque manden mínimo y máximo, por encargo no se guardan.
    r = como_admin.put(f"/productos/{p.id}", json={"minimo": "1", "maximo": "5"})
    assert (r.json()["minimo"], r.json()["maximo"]) == (None, None)
    lista = como_admin.get("/productos?solo_encargo=true").json()
    assert [x["id"] for x in lista] == [p.id]


def test_encargo_no_sale_en_faltantes(como_admin, db, negocio):
    prov = Proveedor(negocio_id=negocio.id, nombre="Nadro")
    db.add(prov)
    normal = _producto(db, negocio, "PARACETAMOL", minimo=D(2), maximo=D(10))
    especial = _producto(db, negocio, "INSULINA RARA", minimo=D(1), maximo=D(2))
    especial.encargo = True  # marcado directo en la base, sin pasar por el API
    db.commit()
    r = como_admin.get(f"/reportes/faltantes?proveedor_id={prov.id}").json()
    nombres = {x["nombre"] for x in r["sin_proveedor"] + r["del_proveedor"]}
    assert "PARACETAMOL" in nombres and "INSULINA RARA" not in nombres
    assert normal  # (usado arriba)


def test_flujo_del_encargo(como_admin, como_mostrador, como_bodega, db, negocio):
    p = _producto(db, negocio, "HUMIRA PLUMA 40MG", encargo=True)
    r = como_mostrador.post("/encargos", json={"cliente": "  Ana   López ", "telefono": "386 111 2233", "producto_id": p.id,
                                               "cantidad": "2"})
    assert r.status_code == 201, r.text
    e = r.json()
    assert (e["cliente"], e["descripcion"], e["estado"], e["producto_encargo"]) == ("Ana López", "HUMIRA PLUMA 40MG", "por_pedir", True)
    # Sin producto del catálogo: solo lo que pidió el cliente.
    libre = como_mostrador.post("/encargos", json={"cliente": "Luis", "descripcion": "Crema que no tenemos"}).json()
    assert libre["producto_id"] is None
    assert como_mostrador.post("/encargos", json={"cliente": "Luis"}).status_code == 409  # ¿qué producto?
    assert como_admin.get("/notificaciones/pendientes").json()["encargos"] == 2

    # Pedido -> hay que avisar al cliente.
    r = como_bodega.put(f"/encargos/{e['id']}/estado", json={"estado": "pedido"})
    assert r.json()["falta_avisar"] is True
    assert como_mostrador.post(f"/encargos/{e['id']}/avisado").json()["falta_avisar"] is False
    r = como_mostrador.put(f"/encargos/{e['id']}/estado", json={"estado": "llego"})
    assert r.json()["falta_avisar"] is True  # ahora hay que avisarle que ya llegó
    assert como_mostrador.put(f"/encargos/{e['id']}/estado", json={"estado": "por_pedir"}).status_code == 409
    assert como_mostrador.put(f"/encargos/{e['id']}/estado", json={"estado": "entregado"}).status_code == 200
    abiertos = {x["id"] for x in como_mostrador.get("/encargos/lista").json()}
    assert abiertos == {libre["id"]}
    assert e["id"] in {x["id"] for x in como_mostrador.get("/encargos/lista?todos=true").json()}


def test_al_enviar_el_pedido_se_marcan(como_admin, db, negocio, admin):
    from app.services import encargos
    prov = Proveedor(negocio_id=negocio.id, nombre="Nadro")
    db.add(prov)
    p = _producto(db, negocio, "HUMIRA PLUMA 40MG", encargo=True)
    otro = _producto(db, negocio, "OTRO ENCARGO", encargo=True)
    e1 = encargos.crear(db, negocio.id, None, "Ana", p.id, canal="whatsapp")  # levantado por el bot
    e2 = encargos.crear(db, negocio.id, admin, "Luis", otro.id)
    db.commit()
    prep = como_admin.get(f"/compras/pedidos/preparar?proveedor_id={prov.id}").json()
    assert {x["nombre"]: x["clientes"] for x in prep["encargos"]} == {"HUMIRA PLUMA 40MG": ["Ana"], "OTRO ENCARGO": ["Luis"]}
    pedido = como_admin.post("/compras/pedidos", json={"proveedor_id": prov.id,
                                                       "renglones": [{"producto_id": p.id, "cantidad": "1"}]}).json()
    assert como_admin.post(f"/compras/pedidos/{pedido['id']}/enviar").status_code == 200
    db.expire_all()
    assert (db.get(Encargo, e1.id).estado, db.get(Encargo, e1.id).pedido_id) == (EstadoEncargo.PEDIDO, pedido["id"])
    assert db.get(Encargo, e2.id).estado == EstadoEncargo.POR_PEDIR  # no iba en el pedido
    lista = {x["id"]: x for x in como_admin.get("/encargos/lista").json()}
    assert lista[e1.id]["creado_por"] == "Bot de WhatsApp"


@pytest.fixture
def wa():
    simulado = whatsapp.activar_simulado()
    yield simulado
    whatsapp.desactivar_simulado()


def test_numero_de_whatsapp():
    assert whatsapp.numero("386 111 2233") == "523861112233"
    assert whatsapp.numero("+52 1 386 111 2233") == "523861112233"
    assert whatsapp.numero("12345") is None


def test_el_bot_avisa_al_cambiar_de_estado(como_mostrador, db, negocio, wa):
    p = _producto(db, negocio, "HUMIRA PLUMA 40MG", encargo=True)
    e = como_mostrador.post("/encargos", json={"cliente": "Ana López", "telefono": "386 111 2233", "producto_id": p.id,
                                               "cantidad": "2"}).json()
    r = como_mostrador.put(f"/encargos/{e['id']}/estado", json={"estado": "pedido"}).json()
    assert (r["falta_avisar"], r["avisado_por"], r["aviso_error"]) == (False, "whatsapp", None)
    assert r["aviso_texto"].startswith("Estimado(a) Ana López, le informamos que su encargo de 2 HUMIRA PLUMA 40MG ya fue solicitado")
    assert wa.enviados[-1] == {"telefono": "523861112233", "plantilla": "encargo_pedido",
                               "parametros": ["Ana López", "2 HUMIRA PLUMA 40MG", negocio.nombre]}
    r = como_mostrador.put(f"/encargos/{e['id']}/estado", json={"estado": "llego"}).json()
    assert wa.enviados[-1]["plantilla"] == "encargo_disponible" and not r["falta_avisar"]


def test_no_se_pudo_encargar(como_mostrador, db, negocio, wa):
    p = _producto(db, negocio, "HUMIRA PLUMA 40MG", encargo=True)
    e = como_mostrador.post("/encargos", json={"cliente": "Ana", "telefono": "3861112233", "producto_id": p.id}).json()
    r = como_mostrador.put(f"/encargos/{e['id']}/estado", json={"estado": "no_disponible"}).json()
    assert (r["estado"], r["estado_texto"], r["falta_avisar"]) == ("no_disponible", "No se pudo encargar", False)
    assert wa.enviados[-1]["plantilla"] == "encargo_no_disponible"
    assert "no cuenta con existencias" in r["aviso_texto"]
    assert e["id"] in {x["id"] for x in como_mostrador.get("/encargos/lista").json()}  # sigue a la vista
    # Se puede volver a intentar más adelante.
    assert como_mostrador.put(f"/encargos/{e['id']}/estado", json={"estado": "por_pedir"}).json()["estado"] == "por_pedir"


def test_si_no_se_puede_avisar_lo_hace_el_personal(como_mostrador, db, negocio, wa):
    p = _producto(db, negocio, "HUMIRA PLUMA 40MG", encargo=True)
    sin_tel = como_mostrador.post("/encargos", json={"cliente": "Luis", "producto_id": p.id}).json()
    r = como_mostrador.put(f"/encargos/{sin_tel['id']}/estado", json={"estado": "pedido"}).json()
    assert r["falta_avisar"] and "teléfono" in r["aviso_error"]
    con_tel = como_mostrador.post("/encargos", json={"cliente": "Ana", "telefono": "3861112233", "producto_id": p.id}).json()
    wa.falla = "No hay conexión con WhatsApp. ¿Hay internet?"
    r = como_mostrador.put(f"/encargos/{con_tel['id']}/estado", json={"estado": "pedido"}).json()
    assert r["falta_avisar"] and "internet" in r["aviso_error"]
    r = como_mostrador.post(f"/encargos/{con_tel['id']}/avisado").json()
    assert (r["falta_avisar"], r["avisado_por"], r["aviso_error"]) == (False, "personal", None)


def test_al_enviar_el_pedido_el_bot_avisa(como_admin, db, negocio, wa):
    from app.services import encargos
    prov = Proveedor(negocio_id=negocio.id, nombre="Nadro")
    db.add(prov)
    p = _producto(db, negocio, "HUMIRA PLUMA 40MG", encargo=True)
    e = encargos.crear(db, negocio.id, None, "Ana", p.id, telefono="3861112233", canal="whatsapp")
    db.commit()
    pedido = como_admin.post("/compras/pedidos", json={"proveedor_id": prov.id,
                                                       "renglones": [{"producto_id": p.id, "cantidad": "1"}]}).json()
    como_admin.post(f"/compras/pedidos/{pedido['id']}/enviar")
    assert [m["plantilla"] for m in wa.enviados] == ["encargo_pedido"]
    db.expire_all()
    assert db.get(Encargo, e.id).avisado_por == "whatsapp"
