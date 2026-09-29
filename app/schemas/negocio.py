from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class NegocioUpdate(BaseModel):
    nombre: str | None = None
    redondeo_precio_venta: Decimal | None = Field(default=None, gt=0)
    ticket_encabezado: str | None = None
    ticket_pie: str | None = None


class NegocioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    logo_url: str | None
    redondeo_precio_venta: Decimal | None
    ticket_encabezado: str | None
    ticket_pie: str | None
    created_at: datetime
