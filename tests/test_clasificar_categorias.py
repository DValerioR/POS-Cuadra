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
    ("SABRITAS RUFFLES QUESO 48 G", None, 13, "Botanas y dulces"),
    ("ORTIZ RODILLERA 155 GRIS", None, 15, "Ortopedia"),
    ("COLLAR CERVIFOAM 20B BEIGE BAJO MEDIANO", None, 15, "Ortopedia"),
    ("CO103 COLLAR PERLAS DIJE MARIPOSA", None, 4, "Bisutería, juguetes y regalos"),
    ("ORTIZ OXIMETRO ANALOGO ACCURATE MOD FS10A", None, 15, "Equipo médico"),
    ("SUERO ELECTROLIT 625 ML PIÑA", None, 21, "Sueros orales y bebidas"),
    ("BEBIDA POWERADE MORAS 500ML", None, None, "Sueros orales y bebidas"),
    ("LECHE DE ALMENDRAS SILK 946ML", None, None, "Sueros orales y bebidas"),
    ("SUERO FACIAL HIALURONICO 30ML", None, 6, "Perfumería"),
    ("LECHE GOOD START 2 6-12M 800G", None, None, "Leches"),
    ("LECHE DE MAGNESIA PHILLIPS 120ML", None, 1, "Patente"),
    ("TENA PANTS NOCTURNO GDE C/10", None, 21, "Higiene femenina e incontinencia"),
    ("P.P SABA DIARIOS PROSKIN CARE REG C/40", None, 6, "Higiene femenina e incontinencia"),
    ("JERINGA SENSIMEDICAL 10 ML 20GX38MM", None, 7, "Material de curación"),
    ("ENJ LISTERINE ANTICARIES ZERO ALCOHOL 500ML", None, 21, "Perfumería"),  # "ALCOHOL" no al inicio
    ("LYSOL DESINFECTANTE AER 475G", None, 21, "Limpieza del hogar"),
    ("ISDIN FOTOULTRA ACTIVE UNIFY 50+FPS 50ML", None, 6, "Dermocosméticos"),
    ("ACEITE DE ARNICA ORGANIK\"S 150 ML (NATURAL\"U)", None, None, "Naturistas y suplementos"),
    ("CREMA CON ARNICA PONDS 100G", None, 6, "Perfumería"),
    ("CAFE VERDE CAPS C/60 SUPLEM/ALIMENTICIO", None, 15, "Naturistas y suplementos"),
    ("TOBRAMICINA SOL OFT 15ML", None, 7, "Patente"),
    ("QUITAESMALTE JALOMA 60ML", None, 3, "Perfumería"),
    ("PILA RAYOVAC AA X 6", None, None, None),
    ("OXOLVAN SOL 120ML (AMBROXOL)", None, 3, "Patente"),
    ("TOPIFORT CREMA 0.05% 30G", None, None, "Patente"),
    ("DIOCAPS CAPSC/30 (C)", None, None, "Patente"),
    ("PROTEC SOLAR HAWAIIAN TROPIC OZONO SPRAY 180ML", None, None, "Perfumería"),
    ("G-0205 CITY COLOR LIP TRANSFORMERS", None, 4, "Perfumería"),
    ("LECHE NOVAMIL 1 POLVO 800 GRS", None, None, "Leches"),
    ("TIC TAC PASTILLAS TUTTI -FRUTTI", None, None, "Botanas y dulces"),
])
def test_reglas(nombre, laboratorio, depto, categoria):
    assert clasificar(nombre, laboratorio, depto).categoria == categoria
