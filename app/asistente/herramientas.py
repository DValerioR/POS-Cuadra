"""Herramientas del asistente: la descripción y el esquema de cada consulta de
consultas.py. `strict` garantiza que los parámetros cumplan el esquema."""

_FECHA = {"type": "string", "description": "Fecha AAAA-MM-DD"}
_NULO = {"type": "null"}


def _opcional(tipo: dict) -> dict:
    return {"anyOf": [tipo, _NULO]}


def _herramienta(nombre: str, descripcion: str, propiedades: dict) -> dict:
    return {
        "name": nombre,
        "description": descripcion,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": propiedades,
            "required": list(propiedades),
            "additionalProperties": False,
        },
    }


_PERIODO = {"desde": _FECHA, "hasta": _opcional({**_FECHA, "description": "Fecha AAAA-MM-DD; null = el mismo día que desde"})}

HERRAMIENTAS = [
    _herramienta(
        "resumen_ventas",
        "Totales de ventas de un día o periodo: número de ventas, vendido con impuestos, cobrado en efectivo y "
        "con tarjeta, lo regresado en devoluciones y el neto cobrado. Opcionalmente agrupado por día, caja, "
        "cajero u hora del día.",
        {**_PERIODO, "agrupar_por": _opcional({"type": "string", "enum": ["dia", "caja", "cajero", "hora"]})},
    ),
    _herramienta(
        "productos_mas_vendidos",
        "Productos más vendidos en un periodo, por piezas o por importe (sin ventas canceladas).",
        {**_PERIODO, "orden": {"type": "string", "enum": ["piezas", "importe"]},
         "limite": _opcional({"type": "integer", "description": "Cuántos (máximo 50)"})},
    ),
    _herramienta(
        "productos_sin_movimiento",
        "Productos con existencia que no se han vendido en los últimos N días, ordenados por el dinero que "
        "tienen detenido al costo.",
        {"dias": {"type": "integer", "description": "Entre 7 y 730"},
         "limite": _opcional({"type": "integer", "description": "Cuántos (máximo 50)"})},
    ),
    _herramienta(
        "buscar_productos",
        "Busca productos por nombre (cada palabra en cualquier parte, sin acentos) o por código de barras. "
        "Regresa precio de venta, costo sin impuestos, IVA, IEPS, categoría y su margen, existencia y si está "
        "marcado para revisar. Úsala antes de existencia_producto para obtener el producto_id.",
        {"texto": {"type": "string"}, "limite": _opcional({"type": "integer", "description": "Cuántos (máximo 50)"})},
    ),
    _herramienta(
        "existencia_producto",
        "Existencia de un producto por lote, con caducidad.",
        {"producto_id": {"type": "integer"}},
    ),
    _herramienta(
        "por_caducar",
        "Lotes con piezas ya caducados o que caducan en los próximos N meses, el más próximo primero.",
        {"meses": {"type": "integer", "description": "Entre 0 y 24"}},
    ),
    _herramienta(
        "estado_del_catalogo",
        "Cuántos productos activos hay, cuántos sin precio, sin costo, sin categoría, marcados para revisar y "
        "con IVA, y las categorías con su margen y número de productos.",
        {},
    ),
    _herramienta(
        "cortes_de_caja",
        "Turnos de caja abiertos en un periodo: quién abrió, cuándo se cerró, efectivo esperado y contado y "
        "las diferencias del corte.",
        _PERIODO,
    ),
    _herramienta(
        "devoluciones",
        "Devoluciones, cancelaciones y cambios de producto de un periodo, con motivo, dinero regresado y "
        "quién la hizo o autorizó.",
        _PERIODO,
    ),
    _herramienta(
        "entradas_de_mercancia",
        "Entradas de mercancía recibidas en un periodo, por proveedor y factura.",
        _PERIODO,
    ),
    _herramienta(
        "pendientes",
        "Lo que está pendiente ahora: devoluciones por autorizar, ventas sin existencia por revisar, ventas "
        "guardadas en espera, turnos abiertos y lotes caducados con existencia.",
        {},
    ),
]
