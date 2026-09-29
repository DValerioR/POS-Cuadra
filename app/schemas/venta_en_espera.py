from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RenglonEnEsperaIn(BaseModel):
    producto_id: int
    cantidad: Decimal = Field(gt=0)
    lote_id: int | None = None
    caducidad_mes: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    numero_lote: str | None = None


class VentaEnEsperaIn(BaseModel):
    caja_id: int
    nota: str | None = Field(default=None, max_length=80)
    renglones: list[RenglonEnEsperaIn] = Field(min_length=1)


class VentaEnEsperaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    caja_id: int
    usuario_id: int
    nota: str | None
    renglones: list[dict]
    articulos: Decimal
    total: Decimal
    created_at: datetime
