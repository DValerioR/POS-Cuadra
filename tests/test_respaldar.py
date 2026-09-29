"""Nombre de la carpeta de respaldos de cada negocio."""

import pytest

from app.scripts.respaldar import carpeta_de


@pytest.mark.parametrize("nombre, carpeta", [
    ("Farmacia La Fe", "FarmaciaLaFe"),
    ("Farmacia Ñandú & Hijos", "FarmaciaNanduHijos"),
    ("abarrotes el güero", "AbarrotesElGuero"),
    ("  ", "Negocio"),
])
def test_carpeta_por_negocio(nombre, carpeta):
    assert carpeta_de(nombre) == carpeta
