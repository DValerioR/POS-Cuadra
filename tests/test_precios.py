from decimal import Decimal as D

import pytest

from app.services.precios import redondear_precio_venta


@pytest.mark.parametrize(
    ("precio", "paso", "maximo", "esperado"),
    [
        (D("47.30"), None, None, D("47.30")),  # sin redondeo configurado
        (D("47.30"), D("1"), None, D("48")),  # siempre hacia arriba
        (D("47.01"), D("1"), None, D("48")),
        (D("47.00"), D("1"), None, D("47")),  # ya entero: no cambia
        (D("47.30"), D("0.5"), None, D("47.5")),  # medios pesos
        (D("47.60"), D("0.5"), None, D("48.0")),
        (D("47.30"), D("1"), D("47.50"), D("47")),  # subir pasaría el máximo: baja
        (D("47.30"), D("1"), D("48"), D("48")),  # llega justo al máximo: se permite
        (D("50.00"), D("1"), D("45"), D("50")),  # ya pasaba el máximo: el redondeo no lo decide
    ],
)
def test_redondear_precio_venta(precio, paso, maximo, esperado):
    assert redondear_precio_venta(precio, paso, maximo) == esperado
