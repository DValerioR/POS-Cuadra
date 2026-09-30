"""Buscador tolerante: encuentra el producto aunque el nombre venga mal
escrito, suene parecido o solo se diga la sustancia activa, y lee fotos de
cajas, frascos o recetas con la IA.

Lo usan el POS ("¿Quiso decir…?" en Vender y Consultar precio, "Identificar
por foto") y el bot de WhatsApp. Siempre SUGIERE: una persona (o el cliente,
en el bot) confirma cuál es.

Cómo compara (`parecidos`):
- Cada palabra se pasa a una "clave de sonido" del español: la c/z/s suenan
  igual, la b/v también, la h no suena, ll/y, qu/k, x/ks/cs -> s, ge/je...,
  letras dobles de más. Así "parasetamol" = "paracetamol", "ivuprofeno" =
  "ibuprofeno", "amosisilina" = "amoxicilina", "lozartan" = "losartán".
- Se compara con rapidfuzz contra el nombre de cada producto (que en el
  catálogo suele traer la sustancia: "ADOPREN 400 MG (IBUPROFENO)"), tanto lo
  escrito como su sonido, para aguantar también letras cambiadas o de menos.

Fotos (`identificar_foto`): la IA lee lo que dice la caja, el frasco o la
receta (nombre, sustancia, concentración, presentación) y con eso se busca en
el catálogo. No identifica pastillas sueltas por su forma o color: eso no es
confiable; pide una foto de la caja o de la receta.
"""

import base64
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field

import anthropic
from rapidfuzz import fuzz, process
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Producto
from app.services import configuracion_ia
from app.services.errores import OperacionInvalida

MINIMO = 78  # parecido mínimo (0-100) para sugerir
IMAGEN_MAXIMA = 5 * 1024 * 1024
# Palabras que no ayudan a distinguir un producto (presentaciones, unidades).
VACIAS = {"TAB", "TABS", "TABLETAS", "TABLETA", "CAP", "CAPS", "CAPSULAS", "C", "CON", "DE", "LA", "EL", "PARA",
          "MG", "ML", "G", "GR", "GRS", "MCG", "UI", "SOL", "SUSP", "JBE", "JARABE", "INY", "AMP", "GOTAS", "GTS",
          "CREMA", "CRA", "UNG", "PIEZA", "PZA", "Y", "EN", "X", "LP"}


def _sin_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().upper()


# Abreviaturas del catálogo (de PVWin) -> palabra completa, para que "shampoo" encuentre "SH ...".
ABREVIATURAS = {"SH": "SHAMPOO", "AC": "ACONDICIONADOR", "ACOND": "ACONDICIONADOR", "TRAT": "TRATAMIENTO",
                "DES": "DESODORANTE", "BLOQ": "BLOQUEADOR", "PVO": "POLVO", "PAST": "PASTA", "CEP": "CEPILLO",
                "BEB": "BEBE", "INF": "INFANTIL", "PED": "PEDIATRICO"}


def palabras(texto: str) -> list[str]:
    return [ABREVIATURAS.get(w, w) for w in re.findall(r"[A-Z]+|\d+(?:\.\d+)?", _sin_acentos(texto))]


def sonido(palabra: str) -> str:
    """Clave de sonido de una palabra en español (ver el docstring del módulo)."""
    p = _sin_acentos(palabra)
    if not p.isalpha():
        return p
    reglas = [
        ("PH", "F"), ("TH", "T"), ("CH", "%"), ("LL", "Y"), ("QU", "K"), ("GUE", "GE"), ("GUI", "GI"),
        ("CS", "S"), ("KS", "S"), ("X", "S"), ("CE", "SE"), ("CI", "SI"), ("C", "K"), ("Z", "S"),
        ("GE", "JE"), ("GI", "JI"), ("V", "B"), ("W", "U"), ("H", ""),
    ]
    for de, a in reglas:
        p = p.replace(de, a)
    p = re.sub(r"(.)\1+", r"\1", p)  # letras dobles
    p = re.sub(r"Y$", "I", p)
    return p.replace("%", "CH")


# --- Índice del catálogo (se renueva si cambian los productos o cada 5 minutos) ----------


@dataclass
class _Indice:
    nombres: dict[int, str]
    # palabra (escrita o su sonido) -> productos que la tienen
    por_texto: dict[str, set[int]]
    por_sonido: dict[str, set[int]]


_cache: dict[int, tuple[tuple, float, _Indice]] = {}


def _indice(db: Session, negocio_id: int) -> _Indice:
    firma = tuple(db.execute(select(func.count(Producto.id), func.max(Producto.id)).where(
        Producto.negocio_id == negocio_id, Producto.activo.is_(True))).one())
    guardado = _cache.get(negocio_id)
    if guardado and guardado[0] == firma and time.monotonic() - guardado[1] < 300:
        return guardado[2]
    indice = _Indice({}, {}, {})
    for pid, nombre in db.execute(select(Producto.id, Producto.nombre).where(
            Producto.negocio_id == negocio_id, Producto.activo.is_(True))):
        indice.nombres[pid] = nombre
        for w in palabras(nombre):
            if w in VACIAS:
                continue
            indice.por_texto.setdefault(w, set()).add(pid)
            indice.por_sonido.setdefault(sonido(w), set()).add(pid)
    _cache[negocio_id] = (firma, time.monotonic(), indice)
    return indice


def olvidar_catalogo() -> None:
    _cache.clear()


@dataclass
class Parecido:
    producto_id: int
    nombre: str
    parecido: int  # 0-100
    por: str  # "escrito" | "sonido"


def parecidos(db: Session, negocio_id: int, texto: str, limite: int = 5) -> list[Parecido]:
    """Productos cuyo nombre se escribe o suena parecido a `texto`, del más al
    menos parecido. Compara palabra por palabra: cada palabra buscada contra
    las palabras del catálogo (escritas y por su sonido); un producto vale el
    promedio de lo bien que coincidió cada palabra buscada. Los números
    ("500") cuentan la mitad y solo si coinciden exactos."""
    buscadas = [w for w in palabras(texto) if w not in VACIAS]
    letras = [w for w in buscadas if w.isalpha() and len(w) >= 3]
    if not letras:
        return []
    numeros = [w for w in buscadas if not w.isalpha()]
    indice = _indice(db, negocio_id)
    puntos: dict[int, float] = {}
    por_sonido: dict[int, bool] = {}
    for w in letras:
        mejor: dict[int, tuple[float, bool]] = {}
        for vocabulario, clave, es_sonido in ((indice.por_texto, w, False), (indice.por_sonido, sonido(w), True)):
            for palabra, puntaje, _ in process.extract(clave, list(vocabulario), scorer=fuzz.ratio, score_cutoff=MINIMO,
                                                       limit=40):
                for pid in vocabulario[palabra]:
                    if pid not in mejor or puntaje > mejor[pid][0]:
                        mejor[pid] = (puntaje, es_sonido and puntaje > fuzz.ratio(w, palabra))
        for pid, (puntaje, fue_sonido) in mejor.items():
            puntos[pid] = puntos.get(pid, 0) + puntaje
            por_sonido[pid] = por_sonido.get(pid, False) or fue_sonido
    peso = len(letras) + 0.5 * len(numeros)
    resultado = []
    for pid, suma in puntos.items():
        en_nombre = set(palabras(indice.nombres[pid]))
        suma += sum(50 for n in numeros if n in en_nombre)
        valor = suma / peso
        if valor >= MINIMO:
            resultado.append(Parecido(pid, indice.nombres[pid], round(valor), "sonido" if por_sonido[pid] else "escrito"))
    return sorted(resultado, key=lambda p: (-p.parecido, p.nombre))[:limite]


# --- Fotos ----------------------------------------------------------------------------------

_TEXTO = {"anyOf": [{"type": "string"}, {"type": "null"}]}
ESQUEMA_FOTO = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": ["caja_o_frasco", "receta", "pastilla_suelta", "otra_cosa", "ilegible"]},
        "medicamentos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nombre_comercial": _TEXTO,
                    "sustancia_activa": _TEXTO,
                    "concentracion": _TEXTO,
                    "presentacion": _TEXTO,
                    "laboratorio": _TEXTO,
                },
                "required": ["nombre_comercial", "sustancia_activa", "concentracion", "presentacion", "laboratorio"],
                "additionalProperties": False,
            },
        },
        "nota": _TEXTO,
    },
    "required": ["tipo", "medicamentos", "nota"],
    "additionalProperties": False,
}

SISTEMA_FOTO = """Eres el asistente de una farmacia en México. Te mandan una foto de un medicamento o producto \
(caja, frasco, blíster con nombre impreso) o de una receta. Tu trabajo es SOLO leer lo que está escrito para \
buscarlo en el catálogo:
- Escribe el nombre comercial, la sustancia activa, la concentración (ej. "400 mg"), la presentación \
(ej. "tabletas c/10") y el laboratorio tal como aparecen. Si algo no se lee, déjalo en null; no lo inventes.
- En una receta, anota cada medicamento recetado (lo que se alcance a leer con seguridad).
- Si es una pastilla o cápsula suelta sin nombre impreso, tipo "pastilla_suelta" y ningún medicamento: no se \
identifica un medicamento por su forma o color.
- Si la foto no deja leer nada, tipo "ilegible". Si no es un medicamento ni una receta, "otra_cosa".
- En "nota", una frase corta si hay algo que la persona deba saber (ej. "la concentración no se alcanza a leer").
No des consejos médicos ni dosis."""


@dataclass
class Lectura:
    tipo: str
    medicamentos: list[dict] = field(default_factory=list)
    nota: str | None = None


def _llamar_foto(datos: bytes, tipo: str) -> str:
    """Pide la lectura de la foto a Claude y regresa el JSON (en el demo se reemplaza por uno simulado)."""
    fuente = {"type": "base64", "media_type": tipo, "data": base64.standard_b64encode(datos).decode("ascii")}
    respuesta = configuracion_ia.cliente().messages.create(
        model=settings.modelo_ia,
        max_tokens=2000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ESQUEMA_FOTO}},
        system=SISTEMA_FOTO,
        messages=[{"role": "user", "content": [{"type": "image", "source": fuente},
                                               {"type": "text", "text": "¿Qué medicamento es?"}]}],
    )
    if respuesta.stop_reason == "refusal":
        raise OperacionInvalida("La IA no quiso leer esta foto")
    texto = next((b.text for b in respuesta.content if b.type == "text"), None)
    if not texto:
        raise OperacionInvalida("La IA no regresó datos; intenta otra vez")
    return texto


def leer_foto(datos: bytes, tipo: str | None) -> Lectura:
    if tipo not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise OperacionInvalida("Sube una foto (JPG, PNG o WEBP)")
    if len(datos) > IMAGEN_MAXIMA:
        raise OperacionInvalida("La foto pesa más de 5 MB; tómala con menos resolución")
    try:
        texto = _llamar_foto(datos, tipo)
    except anthropic.AuthenticationError:
        raise OperacionInvalida("La clave de la API de Claude no es válida; revísala en Configuración → Asistente de IA")
    except anthropic.APIConnectionError:
        raise OperacionInvalida("No hay conexión con la API de Claude; revisa el internet del servidor")
    except anthropic.APIStatusError as e:
        raise OperacionInvalida(f"La API de Claude respondió con un error ({e.status_code}); intenta más tarde")
    try:
        d = json.loads(texto)
    except json.JSONDecodeError:
        raise OperacionInvalida("La respuesta de la IA no se pudo leer; intenta otra vez")
    return Lectura(d.get("tipo") or "ilegible", [m for m in d.get("medicamentos") or [] if any(m.values())], d.get("nota"))


def buscar_lectura(db: Session, negocio_id: int, lectura: Lectura, limite: int = 5) -> list[Parecido]:
    """Productos del catálogo que corresponden a lo que se leyó en la foto."""
    mejores: dict[int, Parecido] = {}
    for m in lectura.medicamentos:
        fuerza = " ".join(filter(None, [m.get("concentracion")]))
        consultas = [" ".join(filter(None, [m.get("nombre_comercial"), fuerza])),
                     " ".join(filter(None, [m.get("sustancia_activa"), fuerza]))]
        for consulta in consultas:
            if not consulta.strip():
                continue
            for p in parecidos(db, negocio_id, consulta, limite):
                if p.producto_id not in mejores or p.parecido > mejores[p.producto_id].parecido:
                    mejores[p.producto_id] = p
    return sorted(mejores.values(), key=lambda p: (-p.parecido, p.nombre))[:limite]
