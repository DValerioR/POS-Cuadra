from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class NegocioUpdate(BaseModel):
    nombre: str | None = None
    logo_url: str | None = None
    redondeo_precio_venta: Decimal | None = Field(default=None, gt=0)


class NegocioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    logo_url: str | None
    redondeo_precio_venta: Decimal | None
    created_at: datetime
