import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.horario import DIAS

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


class Turno(BaseModel):
    abre: str
    cierra: str

    @field_validator("abre", "cierra")
    @classmethod
    def _hora(cls, v):
        v = v.strip()
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d|24:00", v):
            raise ValueError("La hora va como 09:00 (24 horas)")
        return v


def _revisar_turnos(turnos: list[Turno], cuando: str) -> list[Turno]:
    if len(turnos) > 2:
        raise ValueError(f"{cuando}: máximo dos horarios por día")
    for t in turnos:
        if t.abre >= t.cierra:
            raise ValueError(f"{cuando}: la hora de cerrar ({t.cierra}) debe ser después de la de abrir ({t.abre})")
    if len(turnos) == 2:
        primero, segundo = sorted(turnos, key=lambda t: t.abre)
        if segundo.abre < primero.cierra:
            raise ValueError(f"{cuando}: los dos horarios se enciman")
        turnos = [primero, segundo]
    return turnos


class DiaEspecial(BaseModel):
    fecha: date
    turnos: list[Turno] = []  # [] = cerrado ese día
    nota: str | None = Field(default=None, max_length=80)


class Horario(BaseModel):
    semana: dict[str, list[Turno]]
    especiales: list[DiaEspecial] = []

    @field_validator("semana")
    @classmethod
    def _semana(cls, v):
        extras = set(v) - set(DIAS)
        if extras:
            raise ValueError(f"Día no reconocido: {', '.join(sorted(extras))}")
        return {d: _revisar_turnos(v.get(d, []), d.capitalize()) for d in DIAS}

    @field_validator("especiales")
    @classmethod
    def _especiales(cls, v):
        fechas = [e.fecha for e in v]
        if len(fechas) != len(set(fechas)):
            raise ValueError("Hay un día especial repetido")
        for e in v:
            e.turnos = _revisar_turnos(e.turnos, e.fecha.strftime("%d/%m/%Y"))
        return sorted(v, key=lambda e: e.fecha)


class NegocioUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    redondeo_precio_venta: Decimal | None = Field(default=None, gt=0)
    ticket_encabezado: str | None = Field(default=None, max_length=500)
    ticket_pie: str | None = Field(default=None, max_length=300)
    ticket_logo: bool | None = None
    razon_social: str | None = Field(default=None, max_length=200)
    rfc: str | None = None
    regimen_fiscal: str | None = None
    codigo_postal: str | None = None
    horario: Horario | None = None

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
    marca_url: str | None = None
    redondeo_precio_venta: Decimal | None
    ticket_encabezado: str | None
    ticket_pie: str | None
    ticket_logo: bool = False
    razon_social: str | None = None
    rfc: str | None = None
    regimen_fiscal: str | None = None
    codigo_postal: str | None = None
    horario: dict | None = None
    created_at: datetime
