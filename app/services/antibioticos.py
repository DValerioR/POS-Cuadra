"""Qué productos son antibióticos (para el libro de control de Salubridad).

Se reconoce por el nombre del producto: el nombre genérico (muchas veces va
entre paréntesis, "BRUBIOL TABS 500 MG (CIPROFLOXACINO)") o una marca
conocida. Se buscan raíces largas y completas para no confundir parecidos:
ERITROMICINA sí, ERITROPOYETINA no; TRIMETOPRIMA sí, TRIMETILFLOROGLUCINOL no.

La marca la pone el sistema solo, al crear un producto o cambiarle el nombre
(ver los eventos en models/producto.py). Si una persona marca o desmarca un producto a mano
(`antibiotico_manual`), el sistema ya no lo cambia. Al marcarse como
antibiótico, el producto también queda como "requiere receta".
"""

import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Producto

# Raíces de nombres genéricos (sin acentos, en mayúsculas). Basta con que
# aparezcan en cualquier parte del nombre.
GENERICOS = [
    # Penicilinas e inhibidores de betalactamasas
    "AMOXICILIN", "AMPICILIN", "DICLOXACILIN", "PENICILIN", "PIPERACILIN", "OXACILIN", "BACAMPICILIN",
    "PIVAMPICILIN", "CLAVULAN", "SULBACTAM", "TAZOBACTAM",
    # Cefalosporinas
    "CEFALEXIN", "CEFADROXIL", "CEFACLOR", "CEFUROXIM", "CEFPROZIL", "CEFIXIM", "CEFTIBUTEN", "CEFDITOREN",
    "CEFOTAXIM", "CEFTRIAXON", "CEFTAZIDIM", "CEFEPIM", "CEFALOTIN", "CEFAZOLIN", "CEFOXITIN", "CEFPODOXIM",
    "CEFTAROLIN", "CEFRADIN",
    # Carbapenémicos y otros betalactámicos
    "MEROPENEM", "IMIPENEM", "ERTAPENEM", "AZTREONAM",
    # Macrólidos y lincosamidas
    "AZITROMICIN", "CLARITROMICIN", "ERITROMICIN", "ROXITROMICIN", "JOSAMICIN", "ESPIRAMICIN", "TELITROMICIN",
    "CLINDAMICIN", "LINCOMICIN",
    # Tetraciclinas
    "TETRACICLIN", "DOXICICLIN", "MINOCICLIN", "LIMECICLIN", "TIGECICLIN",
    # Quinolonas
    "CIPROFLOXACIN", "LEVOFLOXACIN", "MOXIFLOXACIN", "NORFLOXACIN", "OFLOXACIN", "GATIFLOXACIN", "BESIFLOXACIN",
    "GEMIFLOXACIN", "PRULIFLOXACIN", "NALIDIXIC", "PIPEMIDIC",
    # Aminoglucósidos
    "GENTAMICIN", "AMIKACIN", "TOBRAMICIN", "NEOMICIN", "ESTREPTOMICIN", "KANAMICIN", "NETILMICIN",
    # Sulfas y antisépticos urinarios
    "SULFAMETOX", "SULFADIAZIN", "SULFACETAMID", "TRIMETOPRIM", "TRIMETROPRIM", "NITROFURANTOIN", "FOSFOMICIN",
    # Nitroimidazoles y nitrofuranos
    "METRONIDAZOL", "TINIDAZOL", "SECNIDAZOL", "ORNIDAZOL", "NIFUROXAZID", "FURAZOLIDON",
    # Glucopéptidos, oxazolidinonas y otros
    "VANCOMICIN", "TEICOPLANIN", "LINEZOLID", "DAPTOMICIN", "CLORANFENI", "TIANFENICOL",
    "MUPIROCIN", "FUSIDIC", "BACITRACIN", "POLIMIXIN", "COLISTIN", "RETAPAMULIN",
    # Antituberculosos y rifamicinas
    "RIFAMPICIN", "RIFAXIMIN", "RIFABUTIN", "ISONIAZID", "ETAMBUTOL", "PIRAZINAMID",
]

# Marcas comunes en México (palabra completa).
MARCAS = [
    "AMOXIL", "AUGMENTIN", "CLAVULIN", "TRIFAMOX", "AMOXIBRON", "PENPROCILINA", "BENZETACIL", "PENTREXYL",
    "KEFLEX", "CECLOR", "ZINNAT", "SUPRAX", "ROCEPHIN", "CEFTREX", "AMCEF", "CEFAGEN", "CEFURACET", "BENEVENTOL",
    "ZITROMAX", "AZITROCIN", "KLARICID", "KLARIX", "DALACIN", "LINCOCIN", "LINCONCIN", "VIBRAMICINA", "MINOCIN",
    "CIPROBAC", "CIPRAIN", "CIPROXINA", "TAVANIC", "AVELOX", "NOROXIN", "NORQUINOL", "GARAMICINA", "AMIKIN",
    "TOBREX", "TOBRADEX", "BACTRIM", "SOLTRIM", "BACTIVER", "BACTROPIN", "MACRODANTINA", "MACROFURIN", "MONUROL",
    "FLAGYL", "VANCOCIN", "ZYVOXAM", "RIFADIN", "FLONORM", "BACTROBAN", "FUCIDIN", "QUEMICETINA", "SECNIDAL",
    "ERITROVIER",
]

RE_GENERICOS = re.compile("|".join(re.escape(g) for g in GENERICOS))
RE_MARCAS = re.compile(r"\b(" + "|".join(re.escape(m) for m in MARCAS) + r")\b")


def _normal(nombre: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    return " ".join(sin_acentos.upper().split())


def es_antibiotico(nombre: str) -> bool:
    texto = _normal(nombre)
    return bool(RE_GENERICOS.search(texto) or RE_MARCAS.search(texto))


def aplicar(producto: Producto) -> None:
    """Pone la marca según el nombre, si nadie la decidió a mano."""
    if producto.antibiotico_manual:
        return
    producto.antibiotico = es_antibiotico(producto.nombre)
    if producto.antibiotico:
        producto.requiere_receta = True


def marcar_a_mano(producto: Producto, antibiotico: bool) -> None:
    producto.antibiotico, producto.antibiotico_manual = antibiotico, True
    if antibiotico:
        producto.requiere_receta = True


def detectar_todos(db: Session, negocio_id: int) -> dict:
    """Revisa todo el catálogo (sin tocar los decididos a mano). No hace commit."""
    marcados = desmarcados = 0
    for p in db.scalars(select(Producto).where(Producto.negocio_id == negocio_id, Producto.antibiotico_manual.is_(False))):
        antes = p.antibiotico
        aplicar(p)
        marcados += p.antibiotico and not antes
        desmarcados += antes and not p.antibiotico
    db.flush()
    total = db.scalar(select(func.count()).select_from(Producto)
                      .where(Producto.negocio_id == negocio_id, Producto.antibiotico.is_(True)))
    return {"marcados": marcados, "desmarcados": desmarcados, "antibioticos": total}

