from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.models.solicitud import EstadoSolicitud
from app.models.devolucion import TipoDevolucion
from app.schemas.venta import PiezaDevueltaIn


class SolicitudIn(BaseModel):
    caja_id: int  # caja que la pide; de su turno sale el dinero
    tipo: Literal["devolucion", "cancelacion"]
    motivo: str = Field(min_length=1)
    piezas: list[PiezaDevueltaIn] = []  # solo en devoluciones


class RechazoIn(BaseModel):
    respuesta: str | None = Field(default=None, max_length=200)


class PiezaSolicitadaOut(BaseModel):
    renglon_id: int
    nombre: str
    cantidad: Decimal
    importe: Decimal


class SolicitudOut(BaseModel):
    id: int
    venta_id: int
    folio: int
    fecha_venta: datetime
    total_venta: Decimal
    caja_id: int
    caja: str
    solicitada_por: str
    tipo: TipoDevolucion
    motivo: str
    piezas: list[PiezaSolicitadaOut]
    total: Decimal
    efectivo: Decimal
    tarjeta: Decimal
    estado: EstadoSolicitud
    resuelta_por: str | None
    resuelta_en: datetime | None
    respuesta: str | None
    vista: bool
    created_at: datetime
