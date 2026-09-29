from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductoBase(BaseModel):
    nombre: str
    clave: str | None = None
    categoria_id: int | None = None
    clave_sat: str | None = None
    laboratorio: str | None = None
    requiere_receta: bool = False
    precio_venta: Decimal | None = None
    costo: Decimal | None = None
    precio_maximo_publico: Decimal | None = None
    factor_conversion: Decimal = Field(default=Decimal(1), gt=0)
    iva_porcentaje: Decimal = Decimal(0)
    ieps_porcentaje: Decimal = Decimal(0)
    minimo: Decimal | None = None
    maximo: Decimal | None = None
    requiere_revision: bool = False
    motivo_revision: str | None = None


class ProductoCreate(ProductoBase):
    pass


class ProductoUpdate(BaseModel):
    nombre: str | None = None
    clave: str | None = None
    categoria_id: int | None = None
    clave_sat: str | None = None
    laboratorio: str | None = None
    requiere_receta: bool | None = None
    precio_venta: Decimal | None = None
    costo: Decimal | None = None
    precio_maximo_publico: Decimal | None = None
    factor_conversion: Decimal | None = Field(default=None, gt=0)
    iva_porcentaje: Decimal | None = None
    ieps_porcentaje: Decimal | None = None
    minimo: Decimal | None = None
    maximo: Decimal | None = None
    requiere_revision: bool | None = None
    motivo_revision: str | None = None
    activo: bool | None = None


class ProductoOut(ProductoBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    negocio_id: int
    activo: bool
    created_at: datetime
