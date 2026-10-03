"""Lectura de la exportación completa de catálogos de PVWin (los zip con
archivos DBF que deja PVWin en su carpeta de exportación).

Solo lee y decide; no toca la base de datos (eso lo hace
app/scripts/importar_catalogo_pvwin.py). Reglas en CONTEXTO.md, sección
"Importación desde PVWin".

Archivos que se usan, unidos por la columna ARTICULO (vienen en el mismo
orden, un renglón por artículo):
- art001.zip / exp_art.dbf: descripción, IVA, IEPS, grupo, depto, mínimo y máximo.
- pre001.zip / exp_pre.dbf: costo (PCIO_COM) y precio de venta sin impuestos (PCIO_VTA a PCIO_VTA4).
- sat001.zip / exp_sat.dbf: clave de producto del SAT.
- loc001.zip / exp_loc.dbf: "localización" (en realidad el laboratorio).
No traen existencias. cnf001.zip (configuración de PVWin, con la contraseña
del CSD) no se abre.
"""

import re
import struct
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.importador.pvwin import CORRECCIONES_IVA, OMITIR, FormatoInvalido, _comparable, _laboratorio, _texto

# PVWin escribe los DBF en la codificación de Windows (la Ñ es 0xD1).
CODIFICACION = "cp1252"
IVAS_VALIDOS = {Decimal(0), Decimal(16)}

ARCHIVOS = {
    "art": ("art001.zip", "exp_art.dbf", {"ARTICULO", "DESCRIP", "IVA", "IEPS", "GRUPO", "DEPTO", "MINIMO", "MAXIMO"}),
    "pre": ("pre001.zip", "exp_pre.dbf", {"ARTICULO", "DOLARES", "PCIO_COM", "PCIO_VTA", "PCIO_VTA2", "PCIO_VTA3", "PCIO_VTA4"}),
    "sat": ("sat001.zip", "exp_sat.dbf", {"ARTICULO", "PRODSERV"}),
    "loc": ("loc001.zip", "exp_loc.dbf", {"ARTICULO", "LOCALIZA"}),
}


def leer_dbf(datos: bytes) -> list[dict[str, str]]:
    """Renglones de un DBF (dBase III) como texto sin espacios de relleno.
    Se saltan los renglones borrados."""
    if len(datos) < 32:
        raise FormatoInvalido("el archivo DBF está vacío o cortado")
    total, largo_encabezado, largo_renglon = struct.unpack("<IHH", datos[4:12])
    campos: list[tuple[str, int]] = []
    i = 32
    while i < largo_encabezado and datos[i] != 0x0D:
        nombre = datos[i:i + 11].split(b"\0")[0].decode("ascii")
        campos.append((nombre, datos[i + 16]))
        i += 32
    renglones = []
    for n in range(total):
        inicio = largo_encabezado + n * largo_renglon
        if datos[inicio:inicio + 1] == b"*":
            continue
        posicion = inicio + 1
        renglon = {}
        for nombre, largo in campos:
            renglon[nombre] = datos[posicion:posicion + largo].decode(CODIFICACION).strip()
            posicion += largo
        renglones.append(renglon)
    return renglones


def _leer_zip(carpeta: Path, clave: str) -> list[dict[str, str]]:
    nombre_zip, nombre_dbf, columnas = ARCHIVOS[clave]
    ruta = carpeta / nombre_zip
    if not ruta.exists():
        raise FormatoInvalido(f"falta {nombre_zip} en {carpeta}")
    with zipfile.ZipFile(ruta) as z:
        try:
            datos = z.read(nombre_dbf)
        except KeyError:
            raise FormatoInvalido(f"{nombre_zip} no trae {nombre_dbf}")
    renglones = leer_dbf(datos)
    if renglones and (faltan := columnas - renglones[0].keys()):
        raise FormatoInvalido(f"{nombre_dbf}: faltan las columnas {', '.join(sorted(faltan))}")
    return renglones


def _decimal(texto: str) -> Decimal:
    try:
        return Decimal(texto) if texto else Decimal(0)
    except InvalidOperation:
        raise FormatoInvalido(f"número inválido: '{texto}'")


def _depto(texto: str) -> int | None:
    """'1', '15' -> número. '04', '010' (otros departamentos de PVWin, ej. '04'
    es JMP y '4' es MARZAM GENÉRICOS) y '_DND' (sin depto) -> None, igual que
    llegaban del Excel."""
    return int(texto) if re.fullmatch(r"[1-9]\d*", texto) else None


@dataclass
class ArticuloPVWin:
    clave: str | None
    nombre: str
    clave_sat: str | None
    laboratorio: str | None
    grupo: int | None
    depto: int | None
    costo: Decimal | None  # sin impuestos; None si viene en cero
    precio: Decimal  # "Precio Venta 1", sin impuestos
    otros_precios: list[Decimal]  # Precio Venta 2 a 4 que no vengan en cero
    iva: Decimal | None  # None = IVA raro en PVWin (no es 0 ni 16): no se toca
    ieps: Decimal
    minimo: Decimal | None
    maximo: Decimal | None
    revision: list[str] = field(default_factory=list)

    @property
    def comparable(self) -> str:
        return _comparable(self.nombre)


@dataclass
class Incidencia:
    clave: str | None
    nombre: str
    detalle: str


@dataclass
class CatalogoPVWin:
    articulos: list[ArticuloPVWin]
    omitidos: list[Incidencia]
    repetidos: list[Incidencia]
    corregidos: list[Incidencia]
    renglones: int


def leer_catalogo(carpeta: Path) -> CatalogoPVWin:
    art = _leer_zip(carpeta, "art")
    pre, sat, loc = (_leer_zip(carpeta, c) for c in ("pre", "sat", "loc"))
    for nombre, otros in (("exp_pre", pre), ("exp_sat", sat), ("exp_loc", loc)):
        if [r["ARTICULO"] for r in otros] != [r["ARTICULO"] for r in art]:
            raise FormatoInvalido(f"{nombre}.dbf no trae los mismos artículos que exp_art.dbf (¿exportaciones de días distintos?)")

    articulos: list[ArticuloPVWin] = []
    vistos: set[tuple[str | None, str]] = set()
    omitidos: list[Incidencia] = []
    repetidos: list[Incidencia] = []
    corregidos: list[Incidencia] = []
    for a, p, s, l in zip(art, pre, sat, loc):
        clave, nombre = _texto(a["ARTICULO"]) or None, _texto(a["DESCRIP"])
        if not nombre:
            continue
        if nombre in OMITIR:
            omitidos.append(Incidencia(clave, nombre, "producto de prueba"))
            continue
        if (clave, _comparable(nombre)) in vistos:
            repetidos.append(Incidencia(clave, nombre, "renglón repetido en PVWin; se usó el primero"))
            continue
        vistos.add((clave, _comparable(nombre)))

        revision = []
        iva = _decimal(a["IVA"])
        if iva in CORRECCIONES_IVA:
            corregidos.append(Incidencia(clave, nombre, f"IVA {iva}% corregido a {CORRECCIONES_IVA[iva]}%"))
            iva = CORRECCIONES_IVA[iva]
        elif iva not in IVAS_VALIDOS:
            revision.append(f"IVA de {iva.normalize():f}% en PVWin; revisar si es 0% o 16%")
            iva = None
        grupo = int(a["GRUPO"]) if a["GRUPO"].isdigit() else None
        if grupo is None:
            revision.append("sin grupo en PVWin; revisar categoría")
        costo = _decimal(p["PCIO_COM"]) or None
        if costo is None:
            revision.append("precio de compra en cero en PVWin")
        if p["DOLARES"] == "S":
            revision.append("PVWin lo tiene en dólares; revisar costo y precio")
        otros = [_decimal(p[k]) for k in ("PCIO_VTA2", "PCIO_VTA3", "PCIO_VTA4")]
        articulos.append(ArticuloPVWin(
            clave=clave,
            nombre=nombre,
            clave_sat=s["PRODSERV"] or None,
            laboratorio=_laboratorio(l["LOCALIZA"]),
            grupo=grupo,
            depto=_depto(a["DEPTO"]),
            costo=costo,
            precio=_decimal(p["PCIO_VTA"]),
            otros_precios=[o for o in otros if o],
            iva=iva,
            ieps=_decimal(a["IEPS"]),
            minimo=_decimal(a["MINIMO"]),
            maximo=_decimal(a["MAXIMO"]),
            revision=revision,
        ))
    return CatalogoPVWin(articulos, omitidos, repetidos, corregidos, renglones=len(art))
