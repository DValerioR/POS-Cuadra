"""Pantalla de catálogo y precios: filtros y conteo, historial de precios y
cambios en grupo."""

from decimal import Decimal as D

import pytest

from app.models import Categoria, PrecioHistorial, Producto


@pytest.fixture
def datos(db, negocio):
    negocio.redondeo_precio_venta = D(1)
    cat = Categoria(negocio_id=negocio.id, nombre="Perfumería", margen_porcentaje=D(30))
    db.add(cat)
    db.flush()
    productos = [
        Producto(negocio_id=negocio.id, nombre="SHAMPOO", clave="1", categoria_id=cat.id, precio_venta=D(116), iva_porcentaje=D(16)),
        Producto(negocio_id=negocio.id, nombre="CREMA", clave="2", precio_venta=D(100), requiere_revision=True, motivo_revision="sin costo"),
        Producto(negocio_id=negocio.id, nombre="SIN PRECIO", clave="3", requiere_revision=True, motivo_revision="precio en cero"),
        Producto(negocio_id=negocio.id, nombre="VIEJO", clave="4", precio_venta=D(10), activo=False),
    ]
    db.add_all(productos)
    db.commit()
    return cat, {p.nombre: p for p in productos}


def nombres(cliente, **params):
    return [p["nombre"] for p in cliente.get("/productos", params=params).json()]


def test_filtros_y_conteo(como_admin, datos):
    cat, _ = datos
    assert nombres(como_admin, solo_revision=True) == ["CREMA", "SIN PRECIO"]
    assert nombres(como_admin, sin_precio=True) == ["SIN PRECIO"]
    assert nombres(como_admin, sin_categoria=True, solo_activos=True) == ["CREMA", "SIN PRECIO"]
    assert nombres(como_admin, solo_inactivos=True) == ["VIEJO"]
    assert nombres(como_admin, categoria_id=cat.id) == ["SHAMPOO"]
    assert como_admin.get("/productos/contar", params={"solo_revision": True}).json() == {"total": 2}
    assert como_admin.get("/productos/contar").json() == {"total": 4}


def test_categorias_con_conteo(como_admin, datos):
    [c] = como_admin.get("/categorias").json()
    assert (c["nombre"], c["productos"]) == ("Perfumería", 1)


def test_historial_al_cambiar_precio(como_admin, admin, datos, db):
    _, p = datos
    como_admin.put(f"/productos/{p['CREMA'].id}", json={"precio_venta": "120.40"})  # se redondea a 121
    como_admin.put(f"/productos/{p['CREMA'].id}", json={"nombre": "CREMA 2"})  # sin cambio de precio: no se anota
    h = como_admin.get(f"/productos/{p['CREMA'].id}/precios").json()
    assert [(x["precio_anterior"], x["precio_nuevo"], x["origen"], x["usuario"]) for x in h] == [
        ("100.00", "121.00", "Catálogo", admin.nombre_completo),
    ]


def test_historial_al_crear(como_admin):
    r = como_admin.post("/productos", json={"nombre": "NUEVO", "precio_venta": "50"}).json()
    [h] = como_admin.get(f"/productos/{r['id']}/precios").json()
    assert (h["precio_anterior"], h["precio_nuevo"]) == (None, "50.00")


def test_historial_solo_admin(como_bodega, datos):
    _, p = datos
    assert como_bodega.get(f"/productos/{p['CREMA'].id}/precios").status_code == 403


def test_grupo_categoria_y_revisado(como_admin, datos, db):
    cat, p = datos
    ids = [p["CREMA"].id, p["SIN PRECIO"].id]
    r = como_admin.post("/productos/en-grupo", json={"ids": ids, "categoria_id": cat.id, "revisado": True})
    assert r.json() == {"productos": 2}
    db.expire_all()
    for nombre in ("CREMA", "SIN PRECIO"):
        x = db.get(Producto, p[nombre].id)
        assert (x.categoria_id, x.requiere_revision, x.motivo_revision) == (cat.id, False, None)


def test_grupo_iva_dejando_el_precio_al_publico(como_admin, datos, db):
    _, p = datos
    como_admin.post("/productos/en-grupo", json={"ids": [p["CREMA"].id], "iva_porcentaje": "16"})
    db.expire_all()
    x = db.get(Producto, p["CREMA"].id)
    assert (x.iva_porcentaje, x.precio_venta) == (D(16), D(100))
    assert db.query(PrecioHistorial).count() == 0


def test_grupo_iva_ajustando_el_precio(como_admin, datos, db):
    _, p = datos
    como_admin.post("/productos/en-grupo", json={
        "ids": [p["CREMA"].id, p["SHAMPOO"].id, p["SIN PRECIO"].id], "iva_porcentaje": "16", "ajustar_precio": True,
    })
    db.expire_all()
    assert db.get(Producto, p["CREMA"].id).precio_venta == D(116)  # 100 sin IVA -> 116
    assert db.get(Producto, p["SHAMPOO"].id).precio_venta == D(116)  # ya tenía 16%: no cambia
    assert db.get(Producto, p["SIN PRECIO"].id).precio_venta is None
    [h] = db.query(PrecioHistorial).all()
    assert (h.precio_anterior, h.precio_nuevo) == (D(100), D(116))
    assert "IVA 0% → 16%" in h.origen
    # Y de regreso: 116 con 16% -> 100 sin IVA.
    como_admin.post("/productos/en-grupo", json={"ids": [p["CREMA"].id], "iva_porcentaje": "0", "ajustar_precio": True})
    db.expire_all()
    assert db.get(Producto, p["CREMA"].id).precio_venta == D(100)


def test_grupo_validaciones(como_admin, como_bodega, datos, otro_negocio, db):
    _, p = datos
    ids = [p["CREMA"].id]
    assert como_admin.post("/productos/en-grupo", json={"ids": ids}).status_code == 409  # nada que cambiar
    assert como_admin.post("/productos/en-grupo", json={"ids": ids, "iva_porcentaje": "8"}).status_code == 409
    assert como_admin.post("/productos/en-grupo", json={"ids": ids, "categoria_id": 9999}).status_code == 404
    assert como_admin.post("/productos/en-grupo", json={"ids": [], "revisado": True}).status_code == 422
    assert como_bodega.post("/productos/en-grupo", json={"ids": ids, "revisado": True}).status_code == 403
    ajeno = Producto(negocio_id=otro_negocio.id, nombre="AJENO")
    db.add(ajeno)
    db.commit()
    assert como_admin.post("/productos/en-grupo", json={"ids": [ajeno.id], "revisado": True}).status_code == 404


def test_importador_de_precios_anota_historial(db, negocio, tmp_path):
    from app.scripts.importar_precios_pvwin import aplicar_precios
    from app.importador.pvwin import PrecioPVWin
    negocio.redondeo_precio_venta = None
    p = Producto(negocio_id=negocio.id, nombre="ASPIRINA", clave="9")
    db.add(p)
    db.commit()
    aplicar_precios(db, negocio, [PrecioPVWin("9", "ASPIRINA", D(20), [])], {})
    [h] = db.query(PrecioHistorial).all()
    assert (h.precio_anterior, h.precio_nuevo, h.usuario_id, h.origen) == (None, D(20), None, "Lista de precios de PVWin")
