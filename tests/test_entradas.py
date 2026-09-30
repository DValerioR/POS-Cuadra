"""Entradas de mercancía: lectura del CFDI, proveedores, reconocimiento de
productos (código de barras y equivalencias), lotes, costos y precios."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.importador.cfdi import XmlInvalido, leer_cfdi
from app.services import entradas as entradas_servicio
from app.models import Categoria, Lote, PrecioHistorial, Producto, Proveedor, ProveedorEquivalencia

CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0" Serie="FA" Folio="12345"
    Fecha="2026-09-28T10:15:00" SubTotal="1100.00" Descuento="100.00" Total="1116.00" TipoDeComprobante="I">
  <cfdi:Emisor Rfc="DIS010101AB1" Nombre="DISTRIBUIDORA DE PRUEBA SA DE CV" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XAXX010101000" Nombre="FARMACIA LA FE"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="51101500" NoIdentificacion="7501000000017" Cantidad="10" ClaveUnidad="H87" Unidad="PZA"
        Descripcion="AMOXICILINA 500MG C/12 LOTE: A123 CAD: 05/2027" ValorUnitario="50.00" Importe="500.00" Descuento="100.00">
      <cfdi:Impuestos><cfdi:Traslados>
        <cfdi:Traslado Base="400.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.000000" Importe="0.00"/>
      </cfdi:Traslados></cfdi:Impuestos>
    </cfdi:Concepto>
    <cfdi:Concepto ClaveProdServ="53131600" NoIdentificacion="PROV-99" Cantidad="2" ClaveUnidad="XBX" Unidad="CAJA"
        Descripcion="SHAMPOO   400ML  CAJA C/6" ValorUnitario="300.00" Importe="600.00">
      <cfdi:Impuestos><cfdi:Traslados>
        <cfdi:Traslado Base="600.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="96.00"/>
      </cfdi:Traslados></cfdi:Impuestos>
    </cfdi:Concepto>
  </cfdi:Conceptos>
</cfdi:Comprobante>""".encode("utf-8")


@pytest.fixture
def catalogo(db, negocio):
    negocio.redondeo_precio_venta = D(1)
    patente = Categoria(negocio_id=negocio.id, nombre="Patente", margen_porcentaje=D(20))
    perfumeria = Categoria(negocio_id=negocio.id, nombre="Perfumería", margen_porcentaje=D(20), controla_lote=False)
    db.add_all([patente, perfumeria])
    db.flush()
    amox = Producto(negocio_id=negocio.id, nombre="AMOXICILINA 500MG C/12", clave="7501000000017",
                    categoria_id=patente.id, costo=D(35), precio_venta=D(60))
    shampoo = Producto(negocio_id=negocio.id, nombre="SHAMPOO 400ML", clave="7501000000024",
                       categoria_id=perfumeria.id, iva_porcentaje=D(16), precio_venta=D(70))
    sin_margen = Producto(negocio_id=negocio.id, nombre="GASAS", clave="7501000000031")
    db.add_all([amox, shampoo, sin_margen])
    db.commit()
    return {"amox": amox, "shampoo": shampoo, "gasas": sin_margen}


@pytest.fixture
def proveedor(db, negocio):
    p = Proveedor(negocio_id=negocio.id, nombre="Distribuidora de prueba", rfc="DIS010101AB1")
    db.add(p)
    db.commit()
    return p


def leer_xml(cliente, datos=CFDI, nombre="factura.xml"):
    return cliente.post("/entradas/leer-xml", content=datos, headers={"Content-Type": "application/xml", "X-Nombre-Archivo": nombre})


def entrada(cliente, proveedor, renglones, folio="FA-1", **extra):
    return cliente.post("/entradas", json={
        "proveedor_id": proveedor.id, "folio": folio, "fecha_recepcion": "2026-09-29", "renglones": renglones, **extra,
    })


def lotes(db, p):
    db.expire_all()
    return {(l.numero_lote, l.caducidad): l.cantidad for l in db.query(Lote).filter_by(producto_id=p.id)}


# --- CFDI ---------------------------------------------------------------------------

def test_leer_cfdi():
    f = leer_cfdi(CFDI)
    assert (f.proveedor_rfc, f.proveedor_nombre, f.folio, f.fecha) == (
        "DIS010101AB1", "DISTRIBUIDORA DE PRUEBA SA DE CV", "FA-12345", date(2026, 9, 28))
    assert (f.subtotal, f.total) == (D("1000.00"), D("1116.00"))
    amox, shampoo = f.renglones
    assert (amox.clave, amox.cantidad, amox.costo_unitario, amox.iva) == ("7501000000017", D(10), D("40.0000"), D(0))
    assert (amox.numero_lote, amox.caducidad) == ("A123", date(2027, 5, 31))
    assert (shampoo.descripcion, shampoo.unidad, shampoo.costo_unitario, shampoo.iva) == (
        "SHAMPOO 400ML CAJA C/6", "CAJA", D("300.0000"), D(16))
    assert (shampoo.numero_lote, shampoo.caducidad) == (None, None)


@pytest.mark.parametrize("datos", [b"no es xml", b"<?xml version='1.0'?><otra/>",
                                   b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><x>&a;</x>'])
def test_cfdi_invalido(datos):
    with pytest.raises(XmlInvalido):
        leer_cfdi(datos)


# --- Proveedores --------------------------------------------------------------------

def test_proveedores(como_bodega, como_mostrador):
    r = como_bodega.post("/proveedores", json={"nombre": "  Nadro  ", "rfc": "nad620101ab1"})
    assert r.status_code == 201
    assert (r.json()["nombre"], r.json()["rfc"]) == ("Nadro", "NAD620101AB1")
    assert como_bodega.post("/proveedores", json={"nombre": "Nadro"}).status_code == 409
    assert como_bodega.post("/proveedores", json={"nombre": "Otro", "rfc": "MAL"}).status_code == 409
    assert como_mostrador.post("/proveedores", json={"nombre": "X"}).status_code == 403
    assert [p["nombre"] for p in como_bodega.get("/proveedores").json()] == ["Nadro"]


# --- Leer XML -> borrador -------------------------------------------------------------

def test_borrador_del_xml(como_bodega, catalogo, proveedor):
    r = leer_xml(como_bodega)
    assert r.status_code == 200
    b = r.json()
    assert (b["proveedor_id"], b["folio"], b["origen"], b["archivo_nombre"]) == (proveedor.id, "FA-12345", "xml", "factura.xml")
    amox, shampoo = b["renglones"]
    assert (amox["producto"]["id"], amox["reconocido"]) == (catalogo["amox"].id, "codigo")
    assert amox["producto"]["margen"] == "20.00"
    assert shampoo["producto"] is None  # la clave del proveedor no es código de barras
    # ...pero se propone el de nombre parecido, para elegirlo con un clic.
    assert [x["id"] for x in shampoo["sugerencias"]] == [catalogo["shampoo"].id]
    assert amox["sugerencias"] == []  # ya reconocido: no hace falta
    assert como_bodega.get(f"/entradas/archivos/{b['archivo_id']}").content == CFDI


def test_parecidos_respetan_tamanos(db, negocio):
    from app.services import parecidos
    nombres = ["PASTA DENTAL COLGATE TRIPLE ACCION 50ML", "PASTA DENTAL COLGATE TRIPLE ACCION 75ML",
               "SH CAPRICE CONTROL CASPA 200 ML", "SH SEDAL CERAMIDAS 200ML", "GASAS"]
    db.add_all([Producto(negocio_id=negocio.id, nombre=n) for n in nombres])
    db.commit()
    (colgate,), (caprice, *_), nada = [
        [s["nombre"] for s in lista] for lista in parecidos.sugerir(
            db, negocio.id, ["PASTA COLGATE TRIPLE ACCION 75ML", "SHAMPOO CAPRICE CONTROL CASPA 200GRS", "KOLA LOKA 2GRS C/10"],
            limite=1)
    ]
    assert parecidos.sugerir(db, negocio.id, ["PASTA COLGATE 90ML"]) == [[]]  # solo hay de 50 y 75 ml
    assert colgate == "PASTA DENTAL COLGATE TRIPLE ACCION 75ML"  # no la de 50 ml
    assert caprice == "SH CAPRICE CONTROL CASPA 200 ML"  # "SH" = shampoo, "GRS" = g
    assert nada == []  # nada parecido: no se inventa


def test_borrador_proveedor_desconocido(como_bodega, catalogo):
    b = leer_xml(como_bodega).json()
    assert (b["proveedor_id"], b["proveedor_rfc"], b["proveedor_nombre"]) == (None, "DIS010101AB1", "DISTRIBUIDORA DE PRUEBA SA DE CV")


def test_xml_equivocado(como_bodega):
    assert leer_xml(como_bodega, b"%PDF-1.4 ...", "f.pdf").status_code == 409
    assert leer_xml(como_bodega, b"<?xml version='1.0'?><nada/>").status_code == 409
    assert leer_xml(como_bodega, b"").status_code == 409


# --- Registrar ------------------------------------------------------------------------

def test_registrar_crea_lotes_y_actualiza_costo(como_bodega, catalogo, proveedor, db):
    r = entrada(como_bodega, proveedor, [
        {"producto_id": catalogo["amox"].id, "cantidad": "10", "costo_unitario": "40", "numero_lote": " a123 ",
         "caducidad": "2027-05-31", "descripcion_proveedor": "AMOXICILINA 500MG C/12 LOTE: A123"},
        {"producto_id": catalogo["shampoo"].id, "cantidad": "2", "factor": "6", "costo_unitario": "300",
         "descripcion_proveedor": "SHAMPOO 400ML CAJA C/6", "clave_proveedor": "PROV-99"},
    ], total_factura="1116")
    assert r.status_code == 201
    e = r.json()
    assert (e["productos"], e["piezas"], e["subtotal"], e["precios_cambiados"]) == (2, "22.00", "1000.00", 0)
    assert lotes(db, catalogo["amox"]) == {("A123", date(2027, 5, 31)): D(10)}
    assert lotes(db, catalogo["shampoo"]) == {(None, None): D(12)}
    db.expire_all()
    assert db.get(Producto, catalogo["amox"].id).costo == D(40)
    assert db.get(Producto, catalogo["shampoo"].id).costo == D(50)  # 300 / 6 piezas
    assert db.get(Producto, catalogo["amox"].id).precio_venta == D(60)  # no se pidió cambiar precio


def test_solo_factura_no_mueve_inventario(como_bodega, catalogo, proveedor, db):
    """Facturas cuya mercancía ya estaba en el inventario: se guarda el costo y
    cómo llama el proveedor a cada producto, pero no se suman piezas."""
    antes = lotes(db, catalogo["shampoo"])
    r = entrada(como_bodega, proveedor, [{"producto_id": catalogo["shampoo"].id, "cantidad": "2", "factor": "6",
                                          "costo_unitario": "300", "descripcion_proveedor": "SHAMPOO 400ML CAJA C/6"}],
                afecta_inventario=False)
    assert r.status_code == 201, r.text
    assert r.json()["afecta_inventario"] is False
    assert lotes(db, catalogo["shampoo"]) == antes
    db.expire_all()
    assert db.get(Producto, catalogo["shampoo"].id).costo == D(50)
    # La equivalencia sí quedó: la próxima factura lo reconoce sola.
    _, shampoo = leer_xml(como_bodega).json()["renglones"]
    assert shampoo["producto"]["id"] == catalogo["shampoo"].id
    assert como_bodega.get("/entradas").json()[0]["afecta_inventario"] is False


def test_la_siguiente_vez_se_reconoce_solo(como_bodega, catalogo, proveedor):
    entrada(como_bodega, proveedor, [{"producto_id": catalogo["shampoo"].id, "cantidad": "2", "factor": "6",
                                      "costo_unitario": "300", "descripcion_proveedor": "SHAMPOO   400ML  CAJA C/6",
                                      "clave_proveedor": "PROV-99"}])
    _, shampoo = leer_xml(como_bodega).json()["renglones"]
    assert (shampoo["producto"]["id"], shampoo["factor"], shampoo["reconocido"]) == (catalogo["shampoo"].id, "6.000", "equivalencia")


def test_suma_al_lote_existente_y_cubre_el_negativo(como_bodega, catalogo, proveedor, db, negocio):
    db.add(Lote(negocio_id=negocio.id, producto_id=catalogo["gasas"].id, cantidad=D(-3)))  # vendidas sin existencia
    db.commit()
    entrada(como_bodega, proveedor, [{"producto_id": catalogo["gasas"].id, "cantidad": "10", "costo_unitario": "5"}], folio="A")
    assert lotes(db, catalogo["gasas"]) == {(None, None): D(7)}


def test_aplicar_precio_sugerido(como_admin, admin, catalogo, proveedor, db):
    r = entrada(como_admin, proveedor, [
        {"producto_id": catalogo["amox"].id, "cantidad": "1", "costo_unitario": "50", "aplicar_precio": True},
        {"producto_id": catalogo["shampoo"].id, "cantidad": "1", "costo_unitario": "100", "aplicar_precio": True},
    ])
    assert r.json()["precios_cambiados"] == 2
    db.expire_all()
    assert db.get(Producto, catalogo["amox"].id).precio_venta == D(60)  # 50 × 1.20 = 60, sin IVA
    assert db.get(Producto, catalogo["shampoo"].id).precio_venta == D(140)  # 100 × 1.20 × 1.16 = 139.20 -> 140
    [h] = db.query(PrecioHistorial).filter_by(producto_id=catalogo["shampoo"].id).all()
    assert (h.precio_anterior, h.precio_nuevo, h.usuario_id) == (D(70), D(140), admin.id)
    assert "FA-1" in h.origen


def test_precio_sin_margen_o_por_bodega(como_admin, como_bodega, catalogo, proveedor):
    r = entrada(como_admin, proveedor, [{"producto_id": catalogo["gasas"].id, "cantidad": "1", "costo_unitario": "5", "aplicar_precio": True}])
    assert r.status_code == 409
    assert "no tiene margen" in r.json()["detail"]
    r = entrada(como_bodega, proveedor, [{"producto_id": catalogo["amox"].id, "cantidad": "1", "costo_unitario": "5", "aplicar_precio": True}], folio="B")
    assert r.status_code == 403


def test_folio_repetido_y_archivo(como_bodega, catalogo, proveedor):
    archivo_id = leer_xml(como_bodega).json()["archivo_id"]
    r = entrada(como_bodega, proveedor, [{"producto_id": catalogo["amox"].id, "cantidad": "1", "costo_unitario": "5"}],
                folio="fa-12345", origen="xml", archivo_id=archivo_id)
    assert r.json()["archivo_id"] == archivo_id
    r = entrada(como_bodega, proveedor, [{"producto_id": catalogo["amox"].id, "cantidad": "1", "costo_unitario": "5"}], folio="FA-12345")
    assert r.status_code == 409
    assert "ya se registró" in r.json()["detail"]


def test_lista_detalle_y_permisos(como_bodega, como_mostrador, catalogo, proveedor):
    entrada(como_bodega, proveedor, [{"producto_id": catalogo["amox"].id, "cantidad": "3", "costo_unitario": "40",
                                     "caducidad": "2027-01-31"}])
    [e] = como_bodega.get("/entradas").json()
    assert (e["proveedor"], e["folio"], e["piezas"]) == ("Distribuidora de prueba", "FA-1", "3.00")
    d = como_bodega.get(f"/entradas/{e['id']}").json()
    assert (d["renglones"][0]["producto"], d["renglones"][0]["costo_anterior"]) == ("AMOXICILINA 500MG C/12", "35.0000")
    assert como_mostrador.get("/entradas").status_code == 403
    assert entrada(como_mostrador, proveedor, [{"producto_id": catalogo["amox"].id, "cantidad": "1", "costo_unitario": "1"}]).status_code == 403


def test_validaciones(como_bodega, catalogo, proveedor, otro_negocio, db):
    base = {"producto_id": catalogo["amox"].id, "cantidad": "1", "costo_unitario": "1"}
    assert entrada(como_bodega, proveedor, [{**base, "cantidad": "0"}]).status_code == 422
    assert entrada(como_bodega, proveedor, [{**base, "producto_id": 99999}]).status_code == 404
    assert entrada(como_bodega, proveedor, [base], folio="   ").status_code == 409
    ajeno = Proveedor(negocio_id=otro_negocio.id, nombre="Ajeno")
    db.add(ajeno)
    db.commit()
    assert entrada(como_bodega, ajeno, [base]).status_code == 404
    assert db.query(ProveedorEquivalencia).count() == 0


def test_iva_desconocido_si_el_cfdi_no_lo_dice():
    sin_impuestos = CFDI.replace(b"""
      <cfdi:Impuestos><cfdi:Traslados>
        <cfdi:Traslado Base="600.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="96.00"/>
      </cfdi:Traslados></cfdi:Impuestos>
""", b"")
    no_objeto = sin_impuestos.replace(b'NoIdentificacion="PROV-99"', b'NoIdentificacion="PROV-99" ObjetoImp="01"')
    assert leer_cfdi(sin_impuestos).renglones[1].iva is None
    assert leer_cfdi(no_objeto).renglones[1].iva == D(0)


def test_codigo_walmart_sin_digito_verificador(db, negocio, catalogo):
    # Walmart manda "000" + el código sin su último dígito.
    assert entradas_servicio.digito_verificador("750105530208") == "6"  # 7501055302086 (Coca-Cola)
    db.add(Producto(negocio_id=negocio.id, nombre="REFRESCO COCA 500ML", clave="7501055302086"))
    db.commit()
    producto, _, como = entradas_servicio.reconocer(db, negocio.id, None, "000750105530208", "COCA 500")
    assert (producto.nombre, como) == ("REFRESCO COCA 500ML", "codigo")
    assert entradas_servicio.reconocer(db, negocio.id, None, "000750105530209", None)[0] is None
