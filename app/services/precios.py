from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal


def redondear_precio_venta(
    precio: Decimal, paso: Decimal | None, precio_maximo: Decimal | None = None
) -> Decimal:
    """Redondea un precio de venta al múltiplo de `paso` (ej. 1.00 = pesos
    enteros, 0.50 = medios pesos). Si `paso` es None no se redondea.

    Se redondea hacia arriba para no perder margen. Si al subir se pasa del
    precio máximo al público (y el precio original no lo pasaba), se redondea
    hacia abajo para respetar el máximo.

    Solo es para precios de venta: los costos conservan sus centavos.
    """
    if paso is None:
        return precio
    arriba = (precio / paso).to_integral_value(rounding=ROUND_CEILING) * paso
    if precio_maximo is not None and precio <= precio_maximo < arriba:
        return (precio / paso).to_integral_value(rounding=ROUND_FLOOR) * paso
    return arriba
