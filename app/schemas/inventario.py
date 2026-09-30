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
    no_caduca: bool  # marcado a mano; controla_lote ya lo toma en cuenta
    existencia: Decimal  # piezas en lotes con existencia
    # Lo que dice el sistema contando el lote sin caducidad aunque esté en
    # negativo (se vendieron piezas que no estaban registradas).
    existencia_registrada: Decimal
    sin_caducidad: Decimal
    lotes: list[LoteOut]  # en orden FEFO


class NoCaducaIn(BaseModel):
    no_caduca: bool


class CapturaCaducidadIn(BaseModel):
    producto_id: int
    caducidad: date
    cantidad: Decimal = Field(gt=0)
    numero_lote: str | None = None


class AjusteIn(BaseModel):
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


class ConteoIn(BaseModel):
    producto_id: int
    conteo: Decimal = Field(ge=0)  # piezas que hay en anaquel, en total
    motivo: str = "Conteo físico"


class MovimientoOut(BaseModel):
    id: int
    tipo: TipoAjuste
    cantidad: Decimal
    motivo: str
    created_at: datetime
    usuario: str
    numero_lote: str | None
    caducidad: date | None


class PorCaducarOut(BaseModel):
    lote_id: int
    producto_id: int
    clave: str | None
    nombre: str
    numero_lote: str | None
    caducidad: date
    cantidad: Decimal
    dias: int  # negativos = ya caducó


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
