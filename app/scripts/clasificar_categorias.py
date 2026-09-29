"""Asigna los productos a las categorías con margen, por palabras clave del
nombre, el laboratorio y el departamento de PVWin.

Uso:
    python -m app.scripts.clasificar_categorias --negocio 1            (simula)
    python -m app.scripts.clasificar_categorias --negocio 1 --guardar

Márgenes de Farmacia La Fe (CONTEXTO.md): patente 20%, perfumería 20% (sin
pañales ni leches), similares y genéricos 50%, leches 5%, pañales 15%.

Reglas, en orden (la primera que aplica gana):
1. Pañales: "PAÑAL" en el nombre.
2. Leches: marcas de fórmula infantil o "FORMULA LACTEA".
3. Similares y genéricos: laboratorios de genéricos (AMSA, SCHOEN...) o "G.I.".
4. Patente: medicamento (Depto 1, o forma farmacéutica en el nombre: TABS,
   CAPS, JARABE, INY...) que no cayó en la regla 3.
5. Perfumería: departamentos de perfumería y cuidado personal (2, 5, 6, 9, 12, 16),
   o, sin departamento, palabras como SH, JABON, DES, CRA, PASTA, TOALLA.
Lo demás (botanas, ortopedia, bisutería, bebidas...) queda sin asignar para
decidirlo en Productos y precios. Solo se tocan productos sin categoría o en
una categoría "Depto N"; los que ya están en una de las cinco no se mueven.
Siempre deja un reporte en Excel en datos/.
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

from app.core.database import SessionLocal
from app.models import Categoria, Producto

CATEGORIAS = {  # nombre -> margen
    "Patente": Decimal(20),
    "Perfumería": Decimal(20),
    "Similares y genéricos": Decimal(50),
    "Leches": Decimal(5),
    "Pañales": Decimal(15),
}
DEPTOS_PERFUMERIA = {2, 5, 6, 9, 12, 16}
DEPTOS_MEDICAMENTO = {1}

RE_PANAL = re.compile(r"\bPANAL(ES)?\b")
RE_LECHE = re.compile(
    r"\b(NAN|ENFAMIL|ENFAGROW|SIMILAC|NIDO|S-?26|FRISOLAC|NUTRAMIGEN|ALFARE|PREGESTIMIL|SMA|ISOMIL|PROSOBEE|"
    r"NUTRILON|KAREN|NESTOGENO|ALULA|GOLD\s+ETAPA)\b|FORMULA\s+LACTEA|LECHE\s+(EN\s+)?POLVO|LECHE\s+INFANTIL"
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
    r"NAVAJA|ESPUMA|HIGIENICO|PANUELOS|KLEENEX|COTONETES|CICATRICURE)\b"
)
RE_MEDICAMENTO = re.compile(  # también pegado a una cifra: "30TABS", "500MG"
    r"(?<![A-Z])(TABS?|TABLETAS?|CAPS?|CAPSULAS?|COMPRIMIDOS?|GRAGEAS?|GRAG|JBE|JARABE|SUSP|SUSPENSION|INY|INYECTABLE|"
    r"AMPOLLETAS?|AMP|OVULOS?|SUPOSITORIOS?|GOTAS|SOL\s+ORAL|MG|MCG|UI)\b"
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
    if depto in DEPTOS_PERFUMERIA:
        return Clasificacion("Perfumería", f"Depto {depto} (perfumería y cuidado personal)")
    if es_medicamento and depto in (None, 3, 7, 11):
        return Clasificacion("Patente", "forma de medicamento en el nombre (revisar)")
    if depto is None and RE_PERFUMERIA.search(texto):
        return Clasificacion("Perfumería", "palabra de perfumería en el nombre (sin departamento)")
    return Clasificacion(None, f"Depto {depto}" if depto is not None else "sin departamento")


def main() -> None:
    parser = argparse.ArgumentParser(description="Asignar productos a las categorías con margen")
    parser.add_argument("--negocio", type=int, required=True)
    parser.add_argument("--guardar", action="store_true", help="sin esto solo simula")
    args = parser.parse_args()

    with SessionLocal() as db:
        categorias = {c.nombre: c for c in db.scalars(select(Categoria).where(Categoria.negocio_id == args.negocio))}
        deptos = {c.id: c.pvwin_depto for c in categorias.values()}
        destino = set(CATEGORIAS)
        for nombre, margen in CATEGORIAS.items():
            if nombre not in categorias:
                categorias[nombre] = Categoria(negocio_id=args.negocio, nombre=nombre, margen_porcentaje=margen)
                db.add(categorias[nombre])
        db.flush()
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
