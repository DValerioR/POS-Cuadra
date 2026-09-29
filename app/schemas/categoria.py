from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CategoriaBase(BaseModel):
    nombre: str
    margen_porcentaje: Decimal | None = None
    controla_lote: bool = True


class CategoriaCreate(CategoriaBase):
    pass


class CategoriaUpdate(BaseModel):
    nombre: str | None = None
    margen_porcentaje: Decimal | None = None
    controla_lote: bool | None = None


class CategoriaOut(CategoriaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    negocio_id: int
    created_at: datetime
