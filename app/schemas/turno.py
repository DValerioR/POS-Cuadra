from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.caja import ModoImpresora
from app.models.turno import TipoTurno


class CajaIn(BaseModel):
    nombre: str = Field(min_length=1)


class CajaUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1)
    activa: bool | None = None
    impresora_modo: ModoImpresora | None = None
    impresora_direccion: str | None = None
    impresora_token: str | None = None
    impresora_columnas: int | None = Field(default=None, ge=24, le=64)


class CajaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    activa: bool
    impresora_modo: ModoImpresora
    impresora_direccion: str | None
    impresora_columnas: int
    # El token no se regresa nunca; solo si ya hay uno.
    impresora_tiene_token: bool = False
    # Terminal Mercado Pago Point de la caja (se asigna en /terminal/caja).
    terminal_mp: str | None = None
    # Solo en la lista: quién tiene abierto un turno en esta caja y desde cuándo.
    turno_abierto_por: str | None = None
    turno_abierto_desde: datetime | None = None

    @classmethod
    def de(cls, caja) -> "CajaOut":
        return cls.model_validate(caja).model_copy(update={"impresora_tiene_token": bool(caja.impresora_token)})


class PruebaImpresionIn(BaseModel):
    abrir_cajon: bool = False


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
