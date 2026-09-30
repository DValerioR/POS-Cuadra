import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Regímenes fiscales del SAT que pueden aplicar a una farmacia.
REGIMENES = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios",
    "606": "Arrendamiento",
    "612": "Personas Físicas con Actividades Empresariales y Profesionales",
    "621": "Incorporación Fiscal",
    "625": "Actividades Empresariales con ingresos a través de Plataformas Tecnológicas",
    "626": "Régimen Simplificado de Confianza",
}


class NegocioUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    redondeo_precio_venta: Decimal | None = Field(default=None, gt=0)
    ticket_encabezado: str | None = Field(default=None, max_length=500)
    ticket_pie: str | None = Field(default=None, max_length=300)
    razon_social: str | None = Field(default=None, max_length=200)
    rfc: str | None = None
    regimen_fiscal: str | None = None
    codigo_postal: str | None = None

    @field_validator("nombre", "razon_social")
    @classmethod
    def _limpiar(cls, v):
        return " ".join(v.split()) if v is not None else v

    @field_validator("rfc")
    @classmethod
    def _rfc(cls, v):
        if not v:
            return None
        v = v.strip().upper()
        if not re.fullmatch(r"[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}", v):
            raise ValueError("El RFC no tiene el formato correcto (12 o 13 caracteres)")
        return v

    @field_validator("regimen_fiscal")
    @classmethod
    def _regimen(cls, v):
        if not v:
            return None
        if v not in REGIMENES:
            raise ValueError("Régimen fiscal no reconocido")
        return v

    @field_validator("codigo_postal")
    @classmethod
    def _cp(cls, v):
        if not v:
            return None
        v = v.strip()
        if not re.fullmatch(r"\d{5}", v):
            raise ValueError("El código postal son 5 números")
        return v


class NegocioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    logo_url: str | None
    redondeo_precio_venta: Decimal | None
    ticket_encabezado: str | None
    ticket_pie: str | None
    razon_social: str | None = None
    rfc: str | None = None
    regimen_fiscal: str | None = None
    codigo_postal: str | None = None
    created_at: datetime
