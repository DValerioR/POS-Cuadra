"""Buscador tolerante: nombres mal escritos o que suenan parecido, sustancia
activa y lectura de fotos (con la IA simulada)."""

import json
from decimal import Decimal as D

import pytest

from app.models import Producto
from app.services import buscador

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


@pytest.mark.parametrize("mal, bien", [
    ("parasetamol", "PARACETAMOL"), ("ivuprofeno", "IBUPROFENO"), ("amosisilina", "AMOXICILINA"),
    ("lozartan", "LOSARTÁN"), ("omeprasol", "OMEPRAZOL"), ("idroclorotiasida", "HIDROCLOROTIAZIDA"),
])
def test_suenan_igual(mal, bien):
    assert buscador.sonido(mal) == buscador.sonido(bien)


@pytest.fixture
def catalogo(db, negocio):
    buscador.olvidar_catalogo()
    nombres = ["ADOPREN 400 MG TABLETAS C/10 (IBUPROFENO)", "ADOPREN 800 MG TABLETAS C/10 (IBUPROFENO)",
               "TYLENOL 500MG C/20 TABS", "ASPIRINA PROTECT 100MG C/28", "SUERO PEDIALYTE CEREZA 500ML",
               "SH CAPRICE CONTROL CASPA 200 ML", "SITAGLIPTINA TABS 100 MG C/28"]
    productos = {n: Producto(negocio_id=negocio.id, nombre=n, precio_venta=D(50)) for n in nombres}
    db.add_all(productos.values())
    db.commit()
    yield productos
    buscador.olvidar_catalogo()


@pytest.mark.parametrize("buscado, primero", [
    ("ivuprofeno 400", "ADOPREN 400 MG TABLETAS C/10 (IBUPROFENO)"),  # sustancia mal escrita + concentración
    ("aspirna", "ASPIRINA PROTECT 100MG C/28"),  # letra de menos
    ("pedialite", "SUERO PEDIALYTE CEREZA 500ML"),
    ("shampoo capris", "SH CAPRICE CONTROL CASPA 200 ML"),  # abreviatura del catálogo + suena parecido
    ("sitaglitina", "SITAGLIPTINA TABS 100 MG C/28"),
])
def test_parecidos(como_mostrador, catalogo, buscado, primero):
    r = como_mostrador.get("/productos/parecidos", params={"q": buscado})
    assert r.status_code == 200
    assert r.json()[0]["nombre"] == primero


def test_nada_parecido_no_inventa(como_mostrador, catalogo):
    assert como_mostrador.get("/productos/parecidos", params={"q": "zzz qwerty"}).json() == []


def _lectura(tipo, medicamentos, nota=None):
    return lambda datos, tipo_imagen: json.dumps({"tipo": tipo, "medicamentos": medicamentos, "nota": nota})


def test_foto_de_caja(como_mostrador, catalogo, monkeypatch):
    monkeypatch.setattr(buscador, "_llamar_foto", _lectura("caja_o_frasco", [
        {"nombre_comercial": "Adopren", "sustancia_activa": "Ibuprofeno", "concentracion": "400 mg",
         "presentacion": "tabletas c/10", "laboratorio": None}]))
    r = como_mostrador.post("/productos/identificar-foto", content=PNG)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["candidatos"][0]["nombre"] == "ADOPREN 400 MG TABLETAS C/10 (IBUPROFENO)"
    assert d["mensaje"] is None


def test_pastilla_suelta_no_se_identifica(como_mostrador, catalogo, monkeypatch):
    monkeypatch.setattr(buscador, "_llamar_foto", _lectura("pastilla_suelta", []))
    d = como_mostrador.post("/productos/identificar-foto", content=PNG).json()
    assert d["candidatos"] == [] and "forma o color" in d["mensaje"]


def test_foto_no_valida(como_mostrador):
    r = como_mostrador.post("/productos/identificar-foto", content=b"%PDF-1.4 no es foto")
    assert r.status_code == 409 and "foto" in r.json()["detail"]
