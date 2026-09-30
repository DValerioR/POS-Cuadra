"""Productos del catálogo parecidos a como los llama un proveedor.

Cuando un renglón de una factura no se reconoce (ni por equivalencia ni por
código), se proponen los productos con el nombre más parecido para elegirlo
con un clic. Solo sugiere: la persona decide.

Se compara con rapidfuzz (token_set_ratio: no importa el orden de las
palabras) después de normalizar abreviaturas comunes ("SH" = shampoo, "GRS" =
g...). Los números importan: "PASTA COLGATE 50ML" no debe proponer una de
75 ml, así que si el producto dice otro tamaño se descarta; los demás números
que no coinciden (piezas por caja, etc.) solo bajan el puntaje. Además debe compartir al menos una palabra distintiva (una marca,
por ejemplo): "TREDA C/20 TAB" no debe proponer "THRECHOP TABLETAS C/20".
"""

import re
import unicodedata

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Producto

ABREVIATURAS = {
    "SH": "SHAMPOO", "AC": "ACONDICIONADOR", "TRAT": "TRATAMIENTO", "CRA": "CREMA", "PVO": "POLVO",
    "GRS": "G", "GR": "G", "GRAMOS": "G", "TABS": "TAB", "TABLETAS": "TAB", "CAPS": "CAP", "CAPSULAS": "CAP",
    "L": "LT", "LTS": "LT", "LITRO": "LT", "PZA": "PZ", "PZAS": "PZ", "PIEZAS": "PZ",
}
# Números que casi siempre son parte de la presentación ("2 EN 1", "C/1") y no distinguen productos.
NUMEROS_COMUNES = {"1", "2", "3"}
# Palabras que dicen qué tipo de producto es, no cuál: no bastan para sugerirlo.
GENERICAS = {
    "SHAMPOO", "ACONDICIONADOR", "TRATAMIENTO", "CREMA", "POLVO", "PASTA", "DENTAL", "TINTE", "LECHE", "TAB", "CAP",
    "SPRAY", "TALCO", "MOUSSE", "SOLUCION", "SUSP", "JARABE", "GOTAS", "GTS", "INY", "EXH", "PACK", "PZ", "CON",
    "PARA", "DEL", "LAS", "LOS", "SIN", "CARGO", "PROMOCION", "ORIGINAL", "CAJA", "NO", "DE", "ML", "MG", "MCG", "KG", "LT",
}
PENALIZACION_NUMERO = 12
MINIMO = 70


def normalizar(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().upper()
    t = re.sub(r"(\d)(ML|G|GR|GRS|KG|MG|MCG|L|LT)\b", r"\1 \2", t)
    return " ".join(ABREVIATURAS.get(x, x) for x in re.findall(r"[A-Z]+|\d+(?:\.\d+)?", t))


def _distintivas(texto: str) -> set[str]:
    return {x for x in texto.split() if len(x) >= 3 and x.isalpha() and x not in GENERICAS}


def _numeros(texto: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", texto)) - NUMEROS_COMUNES


def _medidas(texto: str) -> set[str]:
    """Números de tamaño ("75" de "75 ML"): esos sí distinguen un producto de otro. Se
    compara solo el número porque el proveedor y el catálogo a veces usan otra
    unidad para lo mismo (shampoo "200GRS" y "200 ML")."""
    return set(re.findall(r"(\d+(?:\.\d+)?) (?:ML|G|MG|MCG|KG|LT)(?![A-Z])", texto))


def sugerir(db: Session, negocio_id: int, descripciones: list[str | None], limite: int = 3) -> list[list[dict]]:
    """Para cada descripción, hasta `limite` productos activos parecidos:
    [{"id", "nombre", "clave", "parecido"}] del más al menos parecido."""
    if not any(descripciones):
        return [[] for _ in descripciones]
    productos = {pid: (nombre, clave) for pid, nombre, clave in db.execute(
        select(Producto.id, Producto.nombre, Producto.clave).where(
            Producto.negocio_id == negocio_id, Producto.activo.is_(True)))}
    catalogo = {pid: normalizar(nombre) for pid, (nombre, _) in productos.items()}
    resultado = []
    for descripcion in descripciones:
        buscado = normalizar(descripcion)
        if not buscado:
            resultado.append([])
            continue
        numeros, medidas, palabras = _numeros(buscado), _medidas(buscado), _distintivas(buscado)
        candidatos = []
        for texto, puntaje, pid in process.extract(buscado, catalogo, scorer=fuzz.token_set_ratio, limit=25):
            suyas = _distintivas(texto)
            if palabras and suyas and not palabras & suyas:
                continue
            suyas = _medidas(texto)
            if medidas - suyas and suyas:
                continue  # es de otro tamaño (75 ml contra 50 ml)
            ajustado = puntaje - PENALIZACION_NUMERO * len(numeros - _numeros(texto))
            if ajustado >= MINIMO:
                candidatos.append((ajustado, pid))
        candidatos.sort(key=lambda c: (-c[0], productos[c[1]][0]))
        resultado.append([{"id": pid, "nombre": productos[pid][0], "clave": productos[pid][1], "parecido": round(p)}
                          for p, pid in candidatos[:limite]])
    return resultado
