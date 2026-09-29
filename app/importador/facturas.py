"""Lo que se leyó de una factura (del XML o con IA), antes de revisarlo.

Nunca entra así al inventario: con esto se arma la pantalla de revisión,
donde el usuario relaciona cada renglón con un producto, corrige y confirma.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class RenglonLeido:
    descripcion: str
    cantidad: Decimal | None
    costo_unitario: Decimal | None  # por unidad de la factura, sin impuestos
    clave: str | None = None  # código del proveedor o de barras
    unidad: str | None = None
    importe: Decimal | None = None
    iva: Decimal | None = None  # % de IVA que trae la factura (0, 16)
    ieps: Decimal | None = None
    numero_lote: str | None = None
    caducidad: date | None = None
    dudoso: bool = False  # la IA no lo leyó con seguridad
    nota: str | None = None  # qué es lo dudoso


@dataclass
class FacturaLeida:
    origen: str  # "xml" | "ia"
    proveedor_nombre: str | None = None
    proveedor_rfc: str | None = None
    folio: str | None = None
    fecha: date | None = None
    subtotal: Decimal | None = None  # sin impuestos, ya con descuentos
    total: Decimal | None = None
    renglones: list[RenglonLeido] = field(default_factory=list)
    dudas: list[str] = field(default_factory=list)  # avisos generales de la lectura
