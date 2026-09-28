from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ProductoBase(BaseModel):
    nombre: str
    codigo_barras: str | None = None
    categoria_id: int | None = None
    requiere_receta: bool = False
    precio_venta: Decimal
    costo: Decimal | None = None
    precio_maximo_publico: Decimal | None = None


class ProductoCreate(ProductoBase):
    negocio_id: int


class ProductoUpdate(BaseModel):
    nombre: str | None = None
    codigo_barras: str | None = None
    categoria_id: int | None = None
    requiere_receta: bool | None = None
    precio_venta: Decimal | None = None
    costo: Decimal | None = None
    precio_maximo_publico: Decimal | None = None
    activo: bool | None = None


class ProductoOut(ProductoBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    negocio_id: int
    activo: bool
    created_at: datetime
