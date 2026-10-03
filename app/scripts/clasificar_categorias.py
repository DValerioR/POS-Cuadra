"""Asigna los productos a las categorías con margen, por palabras clave del
nombre, el laboratorio y el departamento de PVWin.

Uso:
    python -m app.scripts.clasificar_categorias --negocio 1            (simula)
    python -m app.scripts.clasificar_categorias --negocio 1 --guardar

Márgenes de Farmacia La Fe (CONTEXTO.md): patente 20%, perfumería 20% (sin
pañales ni leches), similares y genéricos 50%, leches 5%, pañales 15%,
ortopedia 15%, botanas y dulces 15%, y 20% para sueros orales y bebidas,
material de curación, naturistas y suplementos, bisutería/juguetes/regalos,
higiene femenina e incontinencia, limpieza del hogar, equipo médico y
dermocosméticos. "Otros" (lo que no entra en ninguna regla): 50% si el costo
es de hasta $150 y 20% si pasa de $150.

Reglas, en orden (la primera que aplica gana):
1. Pañales: "PAÑAL" en el nombre (los de adulto tipo Tena van en incontinencia).
2. Leches: marcas de fórmula infantil, "FORMULA LACTEA" o "LECHE ... ETAPA/MESES".
3. Similares y genéricos: medicamento de laboratorio de genéricos (AMSA, SCHOEN...).
4. Patente: Depto 1 (medicamentos).
5. Por palabras del nombre: higiene femenina e incontinencia, sueros orales y
   bebidas, botanas y dulces, equipo médico, material de curación, limpieza
   del hogar, ortopedia, bisutería/juguetes/regalos y dermocosméticos (por marca).
6. Perfumería: departamentos de perfumería y cuidado personal (2, 5, 6, 9, 12, 16).
7. Naturistas y suplementos (por palabras; después de perfumería para que una
   crema "con árnica" siga en perfumería).
8. Patente: forma farmacéutica en el nombre (TABS, CAPS, JARABE, GOTAS...).
9. Perfumería: palabras como SH, JABON, DES, CRA, PASTA, MAQ en el nombre.
10. Otros: todo lo demás. Solo se
tocan productos sin categoría o en una categoría "Depto N"; los que ya están
en una de estas categorías no se mueven. Siempre deja un reporte en Excel en datos/.
"""

import argparse
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Categoria, Producto

CATEGORIAS = {  # nombre -> margen
    "Patente": Decimal(20),
    "Perfumería": Decimal(20),
    "Similares y genéricos": Decimal(50),
    "Leches": Decimal(5),
    "Pañales": Decimal(15),
    "Ortopedia": Decimal(15),
    "Botanas y dulces": Decimal(15),
    "Sueros orales y bebidas": Decimal(20),
    "Material de curación": Decimal(20),
    "Naturistas y suplementos": Decimal(20),
    "Bisutería, juguetes y regalos": Decimal(20),
    "Higiene femenina e incontinencia": Decimal(20),
    "Limpieza del hogar": Decimal(20),
    "Equipo médico": Decimal(20),
    "Dermocosméticos": Decimal(20),
    "Otros": Decimal(50),
}
# Margen por rango de costo: {categoría: (costo límite, margen si lo pasa)}.
MARGEN_COSTO_ALTO = {"Otros": (Decimal(150), Decimal(20))}
DEPTOS_PERFUMERIA = {2, 5, 6, 9, 12, 16}
DEPTOS_MEDICAMENTO = {1}

RE_PANAL = re.compile(r"\bPANAL(ES)?\b")
RE_LECHE = re.compile(
    r"\b(NAN|ENFAMIL|ENFAGROW|SIMILAC|NIDO|S-?26|FRISOLAC|NUTRAMIGEN|ALFARE|PREGESTIMIL|SMA|ISOMIL|PROSOBEE|"
    r"NUTRILON|KAREN|NESTOGENO|ALULA|GOLD\s+ETAPA|GOOD\s+START|GOOD\s+CARE|PROMIL|NIDAL|ENFAMON|NOVAMIL|KABRITA)\b|"
    r"FORMULA\s+LACTEA|LECHE\s+(EN\s+)?POLVO|LECHE\s+INFANTIL|^LECHE\b.*\b(ET(APA)?\.?\s*\d|\d+\s*-\s*\d+\s*M|MESES)\b"
)
# Categorías por palabras del nombre (regla 5), en este orden.
POR_NOMBRE = [
    ("Higiene femenina e incontinencia", "toalla femenina, protector o incontinencia", re.compile(
        r"^(P\.?\s?P\.?|TOALLAS?\s+F(EM\w*)?|TAMPON(ES)?|COPA\s+MENSTRUAL)\b|"
        r"\b(TENA|DEPEND|PLENITUD|DIAPRO|SABA|KOTEX|ALWAYS|NATURELLA|LADYSOFT)\b")),
    ("Sueros orales y bebidas", "suero oral o bebida", re.compile(
        r"^(AGRANEL\s+)?SUERO\b(?!.*\b(FACIAL|CAPILAR|ANTIEDAD|HIALURONICO)\b)|"
        r"\b(ELECTROLIT|PEDIALYTE|HYDRASOR|FLORALYTE|GATORADE|POWERADE|BOING|LIPTON|ARIZONA|RED\s+BULL|MONSTER|"
        r"VOLT|AMPER|JUMEX|BONAFONT|EPURA|AGUITAS|SILK)\b|^(BEBIDA|JUGO|REFRESCO|COCA\s?COLA|PEPSI)\b|"
        r"^AGUA\s+(NATURAL|PURIFICADA|MINERAL)\b|^LECHE\s+(DE|CON)\s+(ALMENDRA|SOYA|AVENA|COCO)")),
    ("Botanas y dulces", "botana o dulce", re.compile(
        r"^(SABRITAS|DORITOS|CHEETOS|RUFFLES|TOSTITOS|FRITOS|CHIP-?OTLES|CHURRITOS|PAKETAXO|BIG\s+MIX|PAPAS|"
        r"GALLETAS?|CHOCOLATES?|KINDER|DULCES?|CHICLES?|PALETAS?|MAZAPAN|CACAHUATES?|GOMITAS|HALLS|TRIDENT|ADAMS|"
        r"BUBBALOO|CLORETS|MINI\s+MILK|HOLONDA|NUTELLA|GANSITO|MARINELA|GAMESA|CARLOS\s+V|MILKY\s+WAY|SNICKERS|TIC\s+TAC|HUEVO\s+CHOCOLATE)\b")),
    ("Equipo médico", "equipo médico", re.compile(
        r"\b(TERMOMETRO|OXIMETRO|NEBULIZADOR|BAUMANOMETRO|GLUCOMETRO|TIRAS\s+REACTIVAS|ESTETOSCOPIO|AEROCAMARA|"
        r"BOLSA\s+(PARA|P/)\s*AGUA\s+CALIENTE|PRUEBA\s+DE\s+EMBARAZO|MASCARILLA\s+P/NEBU\w*|HUMIDIFICADOR|"
        r"VAPORIZADOR|LANCETERO|OXIGENO)\b|^OMRON\b")),
    ("Material de curación", "material de curación", re.compile(
        r"^(AGRANEL\s+)?(GASAS?|VENDAS?|JERINGAS?|GUANTES?|SONDAS?|APOSITOS?|ABATELENGUAS|ALGODON|TORUNDAS?|"
        r"CANULAS?|CATETER|MICROPORE|CURITAS?|TELA\s+ADHESIVA|CINTA\s+ADHESIVA|ESPARADRAPO|CUBREBOCAS|LANCETAS?|"
        r"BISTURI|HOJAS?\s+DE\s+BISTURI|AGUA\s+INYECTABLE|AGUA\s+BIDESTILADA|AGUA\s+OXIGENADA|ALCOHOL|ETER|"
        r"VASO\s+CLINICO|BOLSAS?\s+(RECOLEC\w*|P/COLOSTOMIA|PARA\s+COLOSTOMIA|DRENAJE|P/RESIDUOS)|B\.P/COLOSTOMIA|"
        r"PLACAS?\s+P/COLOSTOMIA|SOLUCION\s+(CLORURO|HARTMAN\w*|DX|COMBINACION|GLUCOSA)|EQUIPO\s+P/VENOCLISIS|"
        r"NORMOGOTERO|PUNZOCAT|BENZAL)\b|\b(COLOSTOMIA|SENSIMEDICAL|AMBIDERM|TEGADERM|CUTIMED)\b")),
    ("Limpieza del hogar", "limpieza del hogar", re.compile(
        r"^(LYSOL|CLORO|CLORALEX|DESINFECTANTE|FABULOSO|PINOL|DETERGENTE|INSECTICIDA|RAID|REPELENTE|REPEL|"
        r"BOLSAS?\s+(PARA|P/)\s*BASURA)\b|\b(SANITIZANTE|FAMILY\s+GUARD)\b")),
    ("Ortopedia", "ortopedia", re.compile(
        r"^(FAJAS?|RODILLERAS?|TOBILLERAS?|MUNEQUERAS?|CODERAS?|FERULAS?|COLLARIN|COLLAR\s+CERVI\w*|MULETAS?|"
        r"BASTON|ANDADERA|MUSLERAS?|ESPINILLERAS?|PLANTILLAS?|INMOVILIZADOR|SILLA\s+DE\s+RUEDAS|CABESTRILLO|"
        r"MEDIAS?\s+DE\s+COMPRESION)\b|\b(ORTIZ|ACTIMOVE)\b")),
    ("Bisutería, juguetes y regalos", "bisutería, juguete o regalo", re.compile(
        r"\b(COLLAR(ES)?|ARETES?|BROQUEL(ES)?|DIJES?|PULSERAS?|CADENA|ANILLO|JUGUETES?|CARRIOLA|PELUCHE|"
        r"MORDEDERA|EXHIBIDOR|SONAJA|LLAVERO|JMP)\b|^(JUEGO|JG)\b")),
    ("Dermocosméticos", "marca de dermocosmética", re.compile(
        r"\b(ISDIN|EUCERIN|CETAPHIL|FISIOGEL|LA\s+ROCHE|ROCHE\s+POSAY|AVENE|BIODERMA|VICHY|SESDERMA|CERAVE|"
        r"URIAGE|A-DERMA|DUCRAY|NUXE|HELIOCARE|SVR|NOREVA|UREADIN|MEDERMA|DERMAGLOS|NEOSTRATA|ACNIBEN|"
        r"FOTOULTRA|HIDRAPIEL|SEBIUM|PHYSIOGEL|GERMISDIN|ENDOCARE|PILEXIL)\b")),
]
RE_NATURISTA = re.compile(
    r"NATURAL\W?U\b|\b(SHANOVA|SHANATURAL\W?S|NATUREX|ORGANIK\W?S|KUKAMONGA|SUPLEM\w*|CLOROFILA|BIOTINA|COLAGENO|"
    r"OMEGA\s?3|ARNICA|CALENDULA|ACEITE\s+ESENCIAL|ENSURE|GLUCERNA|NOPALINAZA|PINALINAZA|LINAZA|BIOFIBRA|FIBRA|"
    r"ALBUMINA|CAFE\s+VERDE|GINKGO|SPIRULINA|MORINGA|TE\s+VERDE|EXTRACTO|ISOFLAVONAS)\b"
)
# Laboratorios de genéricos: en el nombre van entre paréntesis ("(AMSA)"),
# así "COREGA ULTRA" no cuenta como el laboratorio Ultra.
_LABS_GENERICOS = (r"AMSA|SCHOEN|SALUCOM|TECNOF|MEDITEC|RAYERE|SANDOZ|ULTRA|GENERICO|G\.?\s?I\.?|IFA\s+CELTICS|"
                   r"COLLINS|BRULUART|ALTIAL|PSICOFARMA|PSICOFAR|MAVI|ARLEX|NOVAG|KENER|LOEFFLER")
RE_GENERICO = re.compile(rf"\([^)]*\b({_LABS_GENERICOS})\b")
RE_LAB_GENERICO = re.compile(rf"^({_LABS_GENERICOS})$")
RE_PERFUMERIA = re.compile(
    r"^(SH|SHAMPOO|ACOND|ACONDICIONADOR|JABON|DES|DESODORANTE|CRA|CREMA|TRAT|TINTE|GEL|LOCION|TALCO|"
    r"PASTA|CEP|CEPILLO|HILO DENTAL|ENJUAGUE|TOALLA|TOALLITAS|P\.?\s?P\.?|PROTECTOR|BLOQ|BLOQUEADOR|"
    r"LABIAL|MAQUILLAJE|RIMEL|DELINEADOR|ESMALTE|QUITAESMALTE|PERFUME|COLONIA|AGUA MICELAR|RASTRILLO|"
    r"NAVAJA|ESPUMA|HIGIENICO|PANUELOS|KLEENEX|COTONETES|CICATRICURE|PAST|ENJ|LOC|MAQ|LIPGLOSS|SOMBRA|RUBOR|"
    r"ESPONJA|TOALLITAS|HUMEDAS|FOTOPROTECTOR|BRONCEADOR|TIRAS\s+PARA\s+PUNTOS|LEENEX|CITY\s+COLOR|SANDY\s+BEAUTY|"
    r"QUITA\s?ESMALTE|LIMA|PERFILADOR|POMADA\s+LABIAL|PROTEC|SPRAY|PEINE|MOUSE|ACEITE|TELA|LIJA|TONICO|"
    r"VASO\s+ENTRENADOR|TAZA|SUJETADOR|CONDONES|PRESERVATIVOS?)\b|\b(CITY\s+COLOR|SANDY\s+BEAUTY|EVENFLO|NUBY)\b"
)
RE_MEDICAMENTO = re.compile(  # también pegado a una cifra: "30TABS", "500MG"
    r"(?<![A-Z])(TABS?|TABLETAS?|CAPS?|CAPSULAS?|COMPRIMIDOS?|GRAGEAS?|GRAG|JBE|JARABE|SUSP|SUSPENSION|INY|INYECTABLE|"
    r"AMPOLLETAS?|AMP|OVULOS?|SUPOSITORIOS?|GOTAS|GTAS|GTS|SOL|SOL\s+ORAL|SOL\s+OFT|OFTALMICA|UNGUENTO|COMP|SOBRES|"
    r"INHALACION|MG|MCG|UI)\b|CAPS?C/|\b(CREMA|GEL)\s+\d+(\.\d+)?\s?%|\d+(\.\d+)?\s?%\s+(CREMA|GEL|TB)\b"
)


def _normal(texto: str | None) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_acentos.upper().split())


@dataclass
class Clasificacion:
    categoria: str | None
    regla: str


def clasificar(nombre: str, laboratorio: str | None, depto: int | None) -> Clasificacion:
    texto = _normal(nombre)
    if RE_PANAL.search(texto):
        return Clasificacion("Pañales", "dice PAÑAL")
    if RE_LECHE.search(texto):
        return Clasificacion("Leches", "marca de fórmula o leche en polvo")
    es_medicamento = depto in DEPTOS_MEDICAMENTO or bool(RE_MEDICAMENTO.search(texto))
    if es_medicamento and (RE_GENERICO.search(texto) or RE_LAB_GENERICO.match(_normal(laboratorio))):
        return Clasificacion("Similares y genéricos", "laboratorio de genéricos")
    if depto in DEPTOS_MEDICAMENTO:
        return Clasificacion("Patente", "Depto 1 (medicamentos)")
    for categoria, regla, patron in POR_NOMBRE:
        if patron.search(texto):
            return Clasificacion(categoria, regla)
    if depto in DEPTOS_PERFUMERIA:
        return Clasificacion("Perfumería", f"Depto {depto} (perfumería y cuidado personal)")
    if RE_NATURISTA.search(texto):
        return Clasificacion("Naturistas y suplementos", "naturista o suplemento")
    if es_medicamento and depto in (None, 3, 7, 8, 10, 11):
        return Clasificacion("Patente", "forma de medicamento en el nombre (revisar)")
    if RE_PERFUMERIA.search(texto):
        return Clasificacion("Perfumería", "palabra de perfumería en el nombre")
    return Clasificacion("Otros", f"ninguna regla (Depto {depto})" if depto is not None else "ninguna regla (sin departamento)")


def asegurar_categorias(db: Session, negocio_id: int) -> dict[str, Categoria]:
    """Todas las categorías del negocio por nombre, creando las de margen que falten."""
    categorias = {c.nombre: c for c in db.scalars(select(Categoria).where(Categoria.negocio_id == negocio_id))}
    for nombre, margen in CATEGORIAS.items():
        if nombre not in categorias:
            limite, margen_alto = MARGEN_COSTO_ALTO.get(nombre, (None, None))
            categorias[nombre] = Categoria(negocio_id=negocio_id, nombre=nombre, margen_porcentaje=margen,
                                           limite_costo=limite, margen_arriba_limite=margen_alto)
            db.add(categorias[nombre])
    db.flush()
    return categorias


def main() -> None:
    parser = argparse.ArgumentParser(description="Asignar productos a las categorías con margen")
    parser.add_argument("--negocio", type=int, required=True)
    parser.add_argument("--guardar", action="store_true", help="sin esto solo simula")
    args = parser.parse_args()

    with SessionLocal() as db:
        categorias = asegurar_categorias(db, args.negocio)
        deptos = {c.id: c.pvwin_depto for c in categorias.values()}
        destino = set(CATEGORIAS)
        ids_destino = {categorias[n].id for n in destino}

        filas: dict[str, list] = defaultdict(list)
        conteo: Counter = Counter()
        productos = db.scalars(select(Producto).where(Producto.negocio_id == args.negocio, Producto.activo.is_(True))
                               .order_by(Producto.nombre)).all()
        for p in productos:
            if p.categoria_id in ids_destino:
                conteo[("ya asignado", "")] += 1
                continue
            depto = deptos.get(p.categoria_id)
            c = clasificar(p.nombre, p.laboratorio, depto)
            hoja = c.categoria or "Sin asignar"
            conteo[(hoja, c.regla)] += 1
            filas[hoja].append((p.clave, p.nombre, p.laboratorio, f"Depto {depto}" if depto else "", c.regla))
            if c.categoria and args.guardar:
                p.categoria_id = categorias[c.categoria].id
        if args.guardar:
            db.commit()
        else:
            db.rollback()

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    ws.append(["Modo", "GUARDADO" if args.guardar else "SIMULACIÓN (no se guardó nada)"])
    ws.append([])
    ws.append(["Categoría", "Regla", "Productos"])
    for celda in ws[3]:
        celda.font = Font(bold=True)
    for (hoja, regla), n in sorted(conteo.items()):
        ws.append([hoja, regla, n])
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 55
    for hoja in [*CATEGORIAS, "Sin asignar"]:
        h = wb.create_sheet(hoja[:31])
        h.append(["Clave", "Producto", "Laboratorio", "Departamento PVWin", "Por qué"])
        for celda in h[1]:
            celda.font = Font(bold=True)
        for fila in filas.get(hoja, []):
            h.append(list(fila))
        for letra, ancho in zip("ABCDE", (16, 52, 18, 18, 48)):
            h.column_dimensions[letra].width = ancho
        h.freeze_panes = "A2"
    ruta = Path("datos") / f"reporte_categorias_{datetime.now():%Y%m%d_%H%M%S}{'' if args.guardar else '_simulacion'}.xlsx"
    ruta.parent.mkdir(exist_ok=True)
    wb.save(ruta)

    print("Guardado." if args.guardar else "SIMULACIÓN: no se guardó nada.")
    totales = Counter()
    for (hoja, _), n in conteo.items():
        totales[hoja] += n
    for hoja, n in sorted(totales.items(), key=lambda x: -x[1]):
        print(f"  {hoja:<24} {n:>6}")
    print(f"  Reporte: {ruta}")


if __name__ == "__main__":
    main()
