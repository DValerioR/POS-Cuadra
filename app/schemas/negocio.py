import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


HORA = r"([01]\d|2[0-3]):[0-5]\d|24:00"


def _hora(v: str | None, opcional: bool = False) -> str | None:
    if v is None or (opcional and not v.strip()):
        if opcional:
            return None
        raise ValueError("Falta una hora")
    v = v.strip()
    if not re.fullmatch(HORA, v):
        raise ValueError("La hora va como 09:00 (24 horas)")
    return v


class Turno(BaseModel):
    nombre: str = Field(default="", max_length=30)
    abre: str
    cierra: str

    @field_validator("abre", "cierra")
    @classmethod
    def _horas(cls, v):
        return _hora(v)

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, v):
        return " ".join(v.split())


class DiaEspecial(BaseModel):
    """Reglas de un día especial: entrar más tarde, salir más temprano o cerrar."""
    fecha: date
    abre: str | None = None  # entramos más tarde: a esta hora
    cierra: str | None = None  # salimos más temprano: a esta hora
    cerrado: bool = False
    nota: str | None = Field(default=None, max_length=80)

    @field_validator("abre", "cierra")
    @classmethod
    def _horas(cls, v):
        return _hora(v, opcional=True)


class Horario(BaseModel):
    modo: Literal["corrido", "turnos"] = "corrido"
    turnos: list[str] = []
    semana: dict[str, list[Turno]]
    especiales: list[DiaEspecial] = []

    @model_validator(mode="after")
    def _revisar(self):
        extras = set(self.semana) - set(DIAS)
        if extras:
            raise ValueError(f"Día no reconocido: {', '.join(sorted(extras))}")
        if self.modo == "turnos":
            self.turnos = [" ".join(n.split()) for n in self.turnos]
            if not self.turnos or any(not n for n in self.turnos):
                raise ValueError("Cada turno necesita un nombre")
            if len(self.turnos) > 4:
                raise ValueError("Máximo cuatro turnos")
            if len({n.lower() for n in self.turnos}) != len(self.turnos):
                raise ValueError("Hay dos turnos con el mismo nombre")
        else:
            self.turnos = []
        semana = {}
        for dia in DIAS:
            lista = self.semana.get(dia, [])
            nombre_dia = dia.capitalize()
            if self.modo == "corrido":
                if len(lista) > 1:
                    raise ValueError(f"{nombre_dia}: en horario corrido va un solo horario")
                for t in lista:
                    t.nombre = ""
            else:
                for t in lista:
                    if t.nombre not in self.turnos:
                        raise ValueError(f"{nombre_dia}: el turno «{t.nombre}» no existe")
                if len({t.nombre for t in lista}) != len(lista):
                    raise ValueError(f"{nombre_dia}: un turno está repetido")
                lista = sorted(lista, key=lambda t: self.turnos.index(t.nombre))
            for t in lista:
                if t.abre >= t.cierra:
                    que = f"el turno {t.nombre}" if t.nombre else "el horario"
                    raise ValueError(f"{nombre_dia}, {que}: la hora de cerrar ({t.cierra}) debe ser después de la de abrir ({t.abre})")
            semana[dia] = lista
        self.semana = semana

        fechas = [e.fecha for e in self.especiales]
        if len(fechas) != len(set(fechas)):
            raise ValueError("Hay un día especial repetido")
        for e in self.especiales:
            cuando = e.fecha.strftime("%d/%m/%Y")
            if e.cerrado:
                e.abre = e.cierra = None
            elif not e.abre and not e.cierra:
                raise ValueError(f"Día especial {cuando}: indica a qué hora entran o salen, o márcalo cerrado")
            elif e.abre and e.cierra and e.abre >= e.cierra:
                raise ValueError(f"Día especial {cuando}: la salida debe ser después de la entrada")
        self.especiales = sorted(self.especiales, key=lambda e: e.fecha)
        return self


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
    direccion: str | None = Field(default=None, max_length=300)
    ubicacion_url: str | None = Field(default=None, max_length=500)
    telefono: str | None = Field(default=None, max_length=40)
    formas_pago: list[str] | None = Field(default=None, max_length=10)

    @field_validator("direccion", "telefono")
    @classmethod
    def _texto(cls, v):
        return " ".join(v.split()) or None if v is not None else v

    @field_validator("ubicacion_url")
    @classmethod
    def _url(cls, v):
        v = (v or "").strip()
        if not v:
            return None
        if not re.match(r"https?://\S+$", v):
            raise ValueError("La liga de ubicación debe empezar con https:// (cópiala de Google Maps → Compartir)")
        return v

    @field_validator("formas_pago")
    @classmethod
    def _formas(cls, v):
        if v is None:
            return None
        limpias = [" ".join(f.split())[:60] for f in v if f and f.strip()]
        return limpias or None

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
    direccion: str | None = None
    ubicacion_url: str | None = None
    telefono: str | None = None
    formas_pago: list[str] | None = None
    created_at: datetime
