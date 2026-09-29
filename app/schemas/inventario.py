from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.ajuste_inventario import TipoAjuste


class LoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero_lote: str | None
    caducidad: date | None
    cantidad: Decimal
    costo_unitario: Decimal | None


class ExistenciaOut(BaseModel):
    producto_id: int
    clave: str | None
    nombre: str
    controla_lote: bool
    existencia: Decimal
    sin_caducidad: Decimal
    lotes: list[LoteOut]  # en orden FEFO


class CapturaCaducidadIn(BaseModel):
    negocio_id: int
    usuario_id: int
    producto_id: int
    caducidad: date
    cantidad: Decimal = Field(gt=0)
    numero_lote: str | None = None


class AjusteIn(BaseModel):
    negocio_id: int
    usuario_id: int
    producto_id: int
    tipo: Literal["ajuste", "merma"]
    cantidad: Decimal  # con signo: + suma piezas, - las quita
    motivo: str = Field(min_length=1)
    lote_id: int | None = None  # sin lote = el lote sin caducidad del producto


class AjusteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_id: int
    lote_id: int
    usuario_id: int
    tipo: TipoAjuste
    cantidad: Decimal
    motivo: str
    created_at: datetime


class PendienteCaducidad(BaseModel):
    producto_id: int
    clave: str | None
    nombre: str
    piezas_sin_caducidad: Decimal


class AvanceCaducidadesOut(BaseModel):
    piezas_total: Decimal
    piezas_sin_caducidad: Decimal
    porcentaje_capturado: Decimal
    productos_pendientes: int
    productos: list[PendienteCaducidad]
