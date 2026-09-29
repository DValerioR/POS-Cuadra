from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.turno import TipoTurno


class CajaIn(BaseModel):
    nombre: str = Field(min_length=1)


class CajaUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1)
    activa: bool | None = None


class CajaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    activa: bool


class AbrirTurnoIn(BaseModel):
    caja_id: int
    tipo: TipoTurno
    fondo_inicial: Decimal = Field(ge=0)


class CerrarTurnoIn(BaseModel):
    efectivo_contado: Decimal = Field(ge=0)
    tarjeta_contado: Decimal = Field(ge=0)
    notas: str | None = None


class TurnoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    caja_id: int
    tipo: TipoTurno
    fondo_inicial: Decimal
    abierto_por_id: int
    abierto_en: datetime
    cerrado_por_id: int | None
    cerrado_en: datetime | None
    efectivo_esperado: Decimal | None
    tarjeta_esperado: Decimal | None
    efectivo_contado: Decimal | None
    tarjeta_contado: Decimal | None
    diferencia_efectivo: Decimal | None
    diferencia_tarjeta: Decimal | None
    notas_cierre: str | None


class CorteOut(BaseModel):
    """Lo que el sistema espera en caja en este momento (antes de cerrar)."""

    turno_id: int
    fondo_inicial: Decimal
    ventas_efectivo: Decimal
    ventas_tarjeta: Decimal
    reembolsos_efectivo: Decimal
    reembolsos_tarjeta: Decimal
    efectivo_esperado: Decimal
    tarjeta_esperado: Decimal
