"""Reglas para asignar productos a las categorías con margen."""

import pytest

from app.scripts.clasificar_categorias import clasificar


@pytest.mark.parametrize("nombre, laboratorio, depto, categoria", [
    ("PAÑAL HUGGIES SUPREME ET 4 C/36", None, 5, "Pañales"),
    ("LECHE ENFAMIL PREMIUM 900 G", None, 1, "Leches"),
    ("NUTRILION PEPTI LECHE POLVO 400G", None, 1, "Leches"),
    ("TIRALECHE DE CRISTAL LE ROY", None, 6, "Perfumería"),  # no es leche
    ("METFORMINA 850MG C/30TABS (AMSA)", None, 1, "Similares y genéricos"),
    ("LOSARTAN 50MG TAB C/90", "SCHOEN", 7, "Similares y genéricos"),
    ("ADH COREGA ULTRA SIN SABOR 70G", None, 1, "Patente"),  # "ULTRA" sin paréntesis no es el laboratorio
    ("ZYLOPRIM TABS 300MG C/60", None, 1, "Patente"),
    ("TREZETE 20MG/10MG 30TABS", None, None, "Patente"),
    ("DES NIVEA AEROSOL MEN", None, 6, "Perfumería"),
    ("JABON DOVE BARRA 135G", None, None, "Perfumería"),
    ("SABRITAS RUFFLES QUESO 48 G", None, 13, None),
    ("ORTIZ RODILLERA 155 GRIS", None, 15, None),
    ("QUITAESMALTE JALOMA 60ML", None, 3, None),
])
def test_reglas(nombre, laboratorio, depto, categoria):
    assert clasificar(nombre, laboratorio, depto).categoria == categoria
