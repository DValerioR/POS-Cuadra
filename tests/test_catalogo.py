"""Negocio, categorías y productos: permisos, aislamiento entre negocios,
redondeo de precio, búsqueda y validaciones."""

import pytest

from app.models import Categoria, Producto


@pytest.fixture
def producto(db, negocio) -> Producto:
    p = Producto(negocio_id=negocio.id, nombre="PARACETAMOL 500MG", clave="7501000000017")
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def producto_ajeno(db, otro_negocio) -> Producto:
    p = Producto(negocio_id=otro_negocio.id, nombre="AJENO", clave="7501000000017")
    db.add(p)
    db.commit()
    return p


# --- Negocio ---------------------------------------------------------------

def test_ver_y_configurar_negocio(como_admin, negocio):
    assert como_admin.get("/negocio").json()["id"] == negocio.id
    r = como_admin.put("/negocio", json={"redondeo_precio_venta": "1"})
    assert r.json()["redondeo_precio_venta"] == "1.00"


def test_redondeo_en_cero_se_rechaza(como_admin):
    assert como_admin.put("/negocio", json={"redondeo_precio_venta": "0"}).status_code == 422


def test_solo_admin_configura_negocio(como_mostrador, como_bodega):
    assert como_mostrador.put("/negocio", json={"nombre": "x"}).status_code == 403
    assert como_bodega.put("/negocio", json={"nombre": "x"}).status_code == 403


# --- Categorías ------------------------------------------------------------

def test_crear_categoria_sin_control_de_lote(como_admin, negocio):
    r = como_admin.post("/categorias", json={"nombre": "Dulces", "controla_lote": False})
    assert r.status_code == 201
    assert r.json()["negocio_id"] == negocio.id
    assert r.json()["controla_lote"] is False


def test_categoria_repetida_da_409(como_admin):
    como_admin.post("/categorias", json={"nombre": "Patente"})
    assert como_admin.post("/categorias", json={"nombre": "Patente"}).status_code == 409


def test_no_se_borra_categoria_con_productos(como_admin, db, negocio, producto):
    cat = como_admin.post("/categorias", json={"nombre": "Genéricos"}).json()
    como_admin.put(f"/productos/{producto.id}", json={"categoria_id": cat["id"]})
    assert como_admin.delete(f"/categorias/{cat['id']}").status_code == 409


def test_solo_admin_crea_categorias(como_bodega):
    assert como_bodega.post("/categorias", json={"nombre": "x"}).status_code == 403


def test_categoria_de_otro_negocio_es_invisible(como_admin, db, otro_negocio):
    ajena = Categoria(negocio_id=otro_negocio.id, nombre="Ajena")
    db.add(ajena)
    db.commit()
    assert como_admin.get(f"/categorias/{ajena.id}").status_code == 404
    assert como_admin.put(f"/categorias/{ajena.id}", json={"nombre": "x"}).status_code == 404
    assert "Ajena" not in [c["nombre"] for c in como_admin.get("/categorias").json()]


# --- Productos -------------------------------------------------------------

def test_crear_producto_a_granel_sin_precio(como_admin, negocio):
    r = como_admin.post("/productos", json={
        "nombre": "AGRANEL ADVIL 200 MG C/2", "clave": "ADVIL2", "factor_conversion": "24",
    })
    assert r.status_code == 201
    assert r.json()["negocio_id"] == negocio.id
    assert r.json()["precio_venta"] is None
    assert r.json()["factor_conversion"] == "24.000"


def test_factor_cero_se_rechaza(como_admin):
    assert como_admin.post("/productos", json={"nombre": "x", "factor_conversion": "0"}).status_code == 422


def test_clave_repetida_da_409(como_admin, producto):
    assert como_admin.post("/productos", json={"nombre": "otro", "clave": producto.clave}).status_code == 409


def test_misma_clave_en_otro_negocio_si_se_permite(como_admin, producto_ajeno):
    assert como_admin.post("/productos", json={"nombre": "mío", "clave": producto_ajeno.clave}).status_code == 201


def test_precio_de_venta_se_redondea_y_costo_no(como_admin):
    como_admin.put("/negocio", json={"redondeo_precio_venta": "1"})
    p = como_admin.post("/productos", json={"nombre": "X", "precio_venta": "47.30", "costo": "31.8765"}).json()
    assert p["precio_venta"] == "48.00"
    assert p["costo"] == "31.8765"
    editado = como_admin.put(f"/productos/{p['id']}", json={"precio_venta": "52.10"}).json()
    assert editado["precio_venta"] == "53.00"


def test_redondeo_respeta_precio_maximo(como_admin):
    como_admin.put("/negocio", json={"redondeo_precio_venta": "1"})
    p = como_admin.post("/productos", json={
        "nombre": "PATENTE", "precio_venta": "47.30", "precio_maximo_publico": "47.50",
    }).json()
    assert p["precio_venta"] == "47.00"


def test_sin_redondeo_se_guarda_tal_cual(como_admin):
    p = como_admin.post("/productos", json={"nombre": "X", "precio_venta": "47.30"}).json()
    assert p["precio_venta"] == "47.30"


def test_buscar_por_nombre_parcial_sin_importar_mayusculas(como_admin, producto):
    assert [p["id"] for p in como_admin.get("/productos", params={"q": "paracet"}).json()] == [producto.id]


def test_buscar_por_clave_ignora_ceros_a_la_izquierda(como_admin, db, negocio):
    # Excel se comió el 0 inicial al exportar de PVWin.
    p = Producto(negocio_id=negocio.id, nombre="PAÑAL AFECTIVE", clave="13117000894")
    db.add(p)
    db.commit()
    for escaneado in ("013117000894", "0013117000894", "13117000894"):
        assert [x["id"] for x in como_admin.get("/productos", params={"q": escaneado}).json()] == [p.id]



def test_buscar_solo_por_codigo_no_mezcla_nombres(como_admin, db, negocio):
    # El lector de código de barras no debe traer productos cuyo nombre
    # contenga el número (ej. "CLAVE 750 ML").
    p = Producto(negocio_id=negocio.id, nombre="PAÑAL AFECTIVE", clave="13117000894")
    otro = Producto(negocio_id=negocio.id, nombre="JABON 13117000894", clave="999")
    db.add_all([p, otro])
    db.commit()
    for escaneado in ("013117000894", "13117000894"):
        assert [x["id"] for x in como_admin.get("/productos", params={"clave": escaneado}).json()] == [p.id]
    assert como_admin.get("/productos", params={"clave": "PAÑAL"}).json() == []

def test_listado_paginado_y_filtro_de_revision(como_admin, db, negocio):
    for i in range(5):
        db.add(Producto(negocio_id=negocio.id, nombre=f"P{i}", requiere_revision=(i == 3)))
    db.commit()
    assert len(como_admin.get("/productos", params={"limite": 2}).json()) == 2
    assert [p["nombre"] for p in como_admin.get("/productos", params={"limite": 2, "desplazamiento": 4}).json()] == ["P4"]
    assert [p["nombre"] for p in como_admin.get("/productos", params={"solo_revision": True}).json()] == ["P3"]


def test_eliminar_solo_desactiva(como_admin, producto):
    r = como_admin.delete(f"/productos/{producto.id}")
    assert r.json()["activo"] is False
    assert como_admin.get(f"/productos/{producto.id}").status_code == 200


def test_permisos_de_productos(como_mostrador, como_bodega, producto):
    assert como_mostrador.get("/productos").status_code == 200
    assert como_mostrador.post("/productos", json={"nombre": "x"}).status_code == 403
    assert como_mostrador.put(f"/productos/{producto.id}", json={"precio_venta": "1"}).status_code == 403
    assert como_bodega.put(f"/productos/{producto.id}", json={"precio_venta": "1"}).status_code == 403
    assert como_mostrador.delete(f"/productos/{producto.id}").status_code == 403


def test_producto_de_otro_negocio_es_invisible(como_admin, producto, producto_ajeno):
    assert como_admin.get(f"/productos/{producto_ajeno.id}").status_code == 404
    assert como_admin.put(f"/productos/{producto_ajeno.id}", json={"nombre": "x"}).status_code == 404
    assert [p["id"] for p in como_admin.get("/productos").json()] == [producto.id]


def test_no_se_asigna_categoria_de_otro_negocio(como_admin, db, producto, otro_negocio):
    ajena = Categoria(negocio_id=otro_negocio.id, nombre="Ajena")
    db.add(ajena)
    db.commit()
    assert como_admin.put(f"/productos/{producto.id}", json={"categoria_id": ajena.id}).status_code == 404


def test_busqueda_sin_acentos_y_por_palabras(como_admin, db, negocio):
    p = Producto(negocio_id=negocio.id, nombre="ÁCIDO FÓLICO 5MG C/20")
    db.add(p)
    db.commit()
    for q in ("acido folico", "ACIDO", "folico 5mg", "ácido c/20"):
        assert [x["id"] for x in como_admin.get("/productos", params={"q": q}).json()] == [p.id], q
    assert como_admin.get("/productos", params={"q": "acido 10mg"}).json() == []


def test_solo_activos(como_admin, db, negocio):
    db.add_all([Producto(negocio_id=negocio.id, nombre="ACTIVO"), Producto(negocio_id=negocio.id, nombre="VIEJO", activo=False)])
    db.commit()
    assert [p["nombre"] for p in como_admin.get("/productos", params={"solo_activos": True}).json()] == ["ACTIVO"]
