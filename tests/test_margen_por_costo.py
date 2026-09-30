"""Margen por rango de costo en las categorías (ej. "Otros": 50% hasta $150
de costo, 20% si pasa de $150)."""

from decimal import Decimal as D

from app.models import Categoria, Producto
from app.services.catalogo import precio_sugerido


def otros(db, negocio):
    c = Categoria(negocio_id=negocio.id, nombre="Otros", margen_porcentaje=D(50), limite_costo=D(150),
                  margen_arriba_limite=D(20))
    db.add(c)
    db.commit()
    return c


def test_margen_para():
    c = Categoria(nombre="Otros", margen_porcentaje=D(50), limite_costo=D(150), margen_arriba_limite=D(20))
    assert (c.margen_para(D(100)), c.margen_para(D(150)), c.margen_para(D("150.01")), c.margen_para(None)) == (50, 50, 20, 50)
    assert c.texto_margen() == "50% (20% si el costo pasa de $150.00)"
    sencilla = Categoria(nombre="Patente", margen_porcentaje=D(20))
    assert sencilla.margen_para(D(500)) == 20 and sencilla.texto_margen() == "20%"


def test_precio_sugerido_por_rango(db, negocio):
    c = otros(db, negocio)
    barato = Producto(negocio_id=negocio.id, nombre="BARATO", categoria_id=c.id)
    caro = Producto(negocio_id=negocio.id, nombre="CARO", categoria_id=c.id, iva_porcentaje=D(16))
    db.add_all([barato, caro])
    db.commit()
    assert precio_sugerido(db, barato, D(100)) == D(150)  # 100 × 1.5
    assert precio_sugerido(db, caro, D(200)) == D("278.40")  # 200 × 1.2 × 1.16 (el negocio de prueba no redondea)


def test_api_guarda_el_rango(como_admin, db, negocio):
    c = otros(db, negocio)
    r = como_admin.put(f"/categorias/{c.id}", json={"limite_costo": "300", "margen_arriba_limite": "25"})
    assert r.status_code == 200, r.text
    assert (r.json()["limite_costo"], r.json()["margen_arriba_limite"]) == ("300.00", "25.00")
