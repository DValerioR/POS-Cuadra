"""Cargar o actualizar productos desde un Excel (o CSV) desde la pantalla de
Catálogo, para dar de alta a un negocio que viene de otro sistema.

Reglas:
- Se reconoce el renglón de encabezados (en los primeros 15 renglones) por la
  columna del nombre; las columnas se aceptan con los nombres de la plantilla
  o con los más comunes de otros sistemas ("Código", "Descripción", "Precio"...).
- Un producto se busca por su clave (también sin ceros a la izquierda) y, si
  el renglón no trae clave, por su nombre exacto. Si no existe, se crea.
- En un producto que ya existe, una celda vacía no cambia nada.
- El precio de venta es el que paga el cliente, con impuestos, tal cual.
- IVA: 0, 8 o 16. Si un producto nuevo no trae IVA, queda en 0.
- La categoría se busca por nombre; si no existe, se crea (sin margen).
- La existencia solo se usa en productos nuevos: entra en un lote sin
  caducidad, como la importación de PVWin. En los que ya existen se ignora
  (para corregirla está el ajuste de inventario).
- Primero se revisa (sin guardar) y se muestra qué pasaría; luego se guarda
  todo o nada. Un renglón con error no se guarda y no detiene a los demás.
"""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AjusteInventario, Categoria, Lote, Negocio, Producto, TipoAjuste, Usuario
from app.services.catalogo import registrar_precio
from app.services.errores import OperacionInvalida

MAX_RENGLONES = 30000
MOTIVO_EXISTENCIA = "Existencia inicial cargada desde Excel (sin lote ni caducidad)"
ORIGEN_PRECIO = "Importación de Excel"
IVAS = {Decimal(0), Decimal(8), Decimal(16)}

# campo -> (encabezado de la plantilla, ayuda, otros nombres aceptados)
COLUMNAS = {
    "clave": ("Clave", "Código de barras o clave interna. Se usa para encontrar el producto.",
              ("codigo", "codigo de barras", "cod barras", "sku", "articulo", "clave interna", "upc", "ean")),
    "nombre": ("Nombre", "Obligatorio en productos nuevos.",
               ("descripcion", "producto", "nombre del producto", "articulo descripcion")),
    "precio": ("Precio de venta", "Lo que paga el cliente, con impuestos.",
               ("precio", "precio venta", "precio publico", "precio al publico", "pvp", "precio 1")),
    "costo": ("Costo", "Lo que cuesta cada pieza, sin impuestos.",
              ("costo unitario", "precio compra", "precio de compra", "pcio compra", "ultimo costo")),
    "iva": ("IVA %", "0, 8 o 16.", ("iva", "% iva", "tasa iva")),
    "ieps": ("IEPS %", "Solo si lleva IEPS (ej. 8 en dulces).", ("ieps", "% ieps")),
    "categoria": ("Categoría", "Si no existe, se crea.", ("departamento", "depto", "familia", "linea", "grupo")),
    "laboratorio": ("Laboratorio", "O la marca.", ("marca", "fabricante", "proveedor")),
    "clave_sat": ("Clave SAT", "Clave de producto del SAT, 8 números (para facturar).",
                  ("clave prodserv", "clave producto sat", "prodserv", "clave sat producto")),
    "minimo": ("Mínimo", "Para los pedidos.", ("minimo", "stock minimo", "existencia minima")),
    "maximo": ("Máximo", "Para los pedidos.", ("maximo", "stock maximo", "existencia maxima")),
    "existencia": ("Existencia", "Solo en productos nuevos.", ("existencias", "stock", "inventario", "cantidad")),
    "receta": ("Requiere receta", "SÍ o NO.", ("receta", "con receta", "antibiotico")),
}


def _normal(texto) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9% ]", " ", sin_acentos.lower()).split())


ALIAS = {}
for _campo, (_titulo, _, _otros) in COLUMNAS.items():
    for _nombre in (_titulo, *_otros):
        ALIAS.setdefault(_normal(_nombre), _campo)


def plantilla() -> bytes:
    """Excel vacío con las columnas y una hoja de instrucciones."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Productos"
    ws.append([titulo for titulo, _, _ in COLUMNAS.values()])
    for celda in ws[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="0A4D40")
    ws.append(["7501234567890", "PARACETAMOL 500 MG C/20 TABS", 35, 18.5, 0, 0, "Patente", "GENOMMA", "51142106", 5, 20, 12, "NO"])
    ws.append(["7509876543210", "CHOCOLATE 40 G", 22, 14, 16, 8, "Botanas y dulces", "", "50161813", 10, 30, 24, "NO"])
    for letra, ancho in zip("ABCDEFGHIJKLM", (18, 42, 15, 10, 8, 8, 20, 16, 12, 9, 9, 11, 15)):
        ws.column_dimensions[letra].width = ancho
    ws.freeze_panes = "A2"
    ayuda = wb.create_sheet("Instrucciones")
    ayuda.append(["Columna", "Qué poner"])
    for celda in ayuda[1]:
        celda.font = Font(bold=True)
    for titulo, texto, _ in COLUMNAS.values():
        ayuda.append([titulo, texto])
    ayuda.append([])
    ayuda.append(["", "Borra los dos renglones de ejemplo de la hoja Productos. Solo el nombre es obligatorio en los productos nuevos."])
    ayuda.append(["", "Si un producto ya existe (misma clave), las celdas vacías no cambian nada."])
    ayuda.column_dimensions["A"].width = 18
    ayuda.column_dimensions["B"].width = 90
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _celdas(datos: bytes) -> list[list]:
    """Todas las filas del archivo (Excel o CSV) como listas de valores."""
    if datos[:2] == b"PK":  # .xlsx es un zip
        try:
            wb = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
        except Exception:
            raise OperacionInvalida("No se pudo abrir el Excel. Guárdalo como .xlsx e inténtalo de nuevo")
        hoja = wb["Productos"] if "Productos" in wb.sheetnames else wb.worksheets[0]
        filas = [list(f) for f in hoja.iter_rows(values_only=True)]
        wb.close()
        return filas
    if datos[:4] == b"\xd0\xcf\x11\xe0":
        raise OperacionInvalida("Es un Excel viejo (.xls). Ábrelo y guárdalo como .xlsx")
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            texto = datos.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    separador = ";" if texto[:2000].count(";") > texto[:2000].count(",") else ","
    return [list(f) for f in csv.reader(io.StringIO(texto), delimiter=separador)]


@dataclass
class Renglon:
    numero: int  # renglón en el archivo (como lo ve la persona en Excel)
    valores: dict


def leer(datos: bytes) -> tuple[list[Renglon], dict[str, str]]:
    """(renglones, {campo: encabezado como venía en el archivo})."""
    if not datos:
        raise OperacionInvalida("El archivo está vacío")
    filas = _celdas(datos)
    for i, fila in enumerate(filas[:15]):
        campos = {}
        for j, celda in enumerate(fila):
            campo = ALIAS.get(_normal(celda))
            if campo and campo not in campos.values():
                campos[j] = campo
        if "nombre" in campos.values():
            break
    else:
        raise OperacionInvalida("No encontré la columna del nombre del producto. Usa la plantilla o pon "
                                "\"Nombre\" (o \"Descripción\") en el renglón de encabezados")
    encabezados = {campo: str(filas[i][j]).strip() for j, campo in campos.items()}
    renglones = []
    for numero, fila in enumerate(filas[i + 1:], start=i + 2):
        valores = {campo: fila[j] for j, campo in campos.items() if j < len(fila)}
        if all(v is None or str(v).strip() == "" for v in valores.values()):
            continue
        renglones.append(Renglon(numero, valores))
    if len(renglones) > MAX_RENGLONES:
        raise OperacionInvalida(f"El archivo tiene {len(renglones):,} productos; el máximo es {MAX_RENGLONES:,} por carga")
    return renglones, encabezados


# --- Conversión de celdas -------------------------------------------------------

def _texto(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    texto = " ".join(str(v).split())
    return texto or None


def _numero(v, campo: str) -> Decimal | None:
    texto = _texto(v)
    if texto is None:
        return None
    limpio = texto.replace("$", "").replace("%", "").replace(" ", "").strip()
    if "," in limpio and "." not in limpio and re.fullmatch(r"-?\d+,\d{1,2}", limpio):
        limpio = limpio.replace(",", ".")  # coma decimal (Excel en español): 12,50
    else:
        limpio = limpio.replace(",", "")  # separador de miles: 1,250.00
    try:
        numero = Decimal(limpio)
    except InvalidOperation:
        raise ValueError(f"{COLUMNAS[campo][0]}: «{texto}» no es un número")
    if numero < 0:
        raise ValueError(f"{COLUMNAS[campo][0]} no puede ser negativo")
    return numero


def _porcentaje(v, campo: str) -> Decimal | None:
    n = _numero(v, campo)
    if n is not None and 0 < n < 1:  # Excel con formato de porcentaje: 16% llega como 0.16
        n *= 100
    return n.quantize(Decimal("0.01")) if n is not None else None


def _si_no(v) -> bool | None:
    texto = _normal(v)
    if not texto:
        return None
    if texto in ("si", "s", "x", "1", "true", "verdadero"):
        return True
    if texto in ("no", "n", "0", "false", "falso"):
        return False
    raise ValueError(f"Requiere receta: «{v}» debe ser SÍ o NO")


@dataclass
class Datos:
    """Lo que trae un renglón, ya revisado (None = vacío, no se cambia)."""
    clave: str | None = None
    nombre: str | None = None
    precio: Decimal | None = None
    costo: Decimal | None = None
    iva: Decimal | None = None
    ieps: Decimal | None = None
    categoria: str | None = None
    laboratorio: str | None = None
    clave_sat: str | None = None
    minimo: Decimal | None = None
    maximo: Decimal | None = None
    existencia: Decimal | None = None
    receta: bool | None = None


def _revisar(valores: dict) -> Datos:
    d = Datos(
        clave=_texto(valores.get("clave")), nombre=_texto(valores.get("nombre")),
        precio=_numero(valores.get("precio"), "precio"), costo=_numero(valores.get("costo"), "costo"),
        iva=_porcentaje(valores.get("iva"), "iva"), ieps=_porcentaje(valores.get("ieps"), "ieps"),
        categoria=_texto(valores.get("categoria")), laboratorio=_texto(valores.get("laboratorio")),
        clave_sat=_texto(valores.get("clave_sat")), minimo=_numero(valores.get("minimo"), "minimo"),
        maximo=_numero(valores.get("maximo"), "maximo"), existencia=_numero(valores.get("existencia"), "existencia"),
        receta=_si_no(valores.get("receta")),
    )
    if d.nombre:
        d.nombre = d.nombre.upper()
    if d.iva is not None and d.iva not in IVAS:
        raise ValueError(f"IVA de {d.iva.normalize():f}%: debe ser 0, 8 o 16")
    if d.ieps is not None and d.ieps > 200:
        raise ValueError("IEPS fuera de rango")
    if d.clave_sat is not None and not re.fullmatch(r"\d{8}", d.clave_sat):
        raise ValueError(f"Clave SAT «{d.clave_sat}»: son 8 números")
    if d.precio is not None:
        d.precio = d.precio.quantize(Decimal("0.01"))
    if d.minimo is not None and d.maximo is not None and d.minimo > d.maximo:
        raise ValueError("El mínimo es mayor que el máximo")
    if d.clave is not None and len(d.clave) > 60:
        raise ValueError("La clave es demasiado larga")
    if d.nombre is not None and len(d.nombre) > 200:
        raise ValueError("El nombre es demasiado largo")
    return d


# --- Revisar y guardar ------------------------------------------------------------

@dataclass
class Resultado:
    renglones: int = 0
    nuevos: list[dict] = field(default_factory=list)  # renglon, clave, nombre, precio, existencia
    actualizados: list[dict] = field(default_factory=list)  # renglon, clave, nombre, cambios
    sin_cambios: int = 0
    errores: list[dict] = field(default_factory=list)  # renglon, clave, nombre, error
    existencia_ignorada: int = 0  # renglones de productos que ya existían con existencia
    categorias_nuevas: list[str] = field(default_factory=list)
    piezas: Decimal = Decimal(0)


def _comparable(nombre: str) -> str:
    return _normal(nombre).replace(" ", "")


def aplicar(db: Session, usuario: Usuario, datos: bytes, guardar: bool) -> tuple[Resultado, dict[str, str]]:
    """Revisa el archivo contra el catálogo y, con `guardar`, aplica los
    cambios (sin commit; quien llama hace commit o rollback)."""
    renglones, encabezados = leer(datos)
    negocio = db.get(Negocio, usuario.negocio_id)
    r = Resultado(renglones=len(renglones))
    productos = db.scalars(select(Producto).where(Producto.negocio_id == negocio.id)).all()
    por_clave: dict[str, Producto] = {}
    por_clave_sin_ceros: dict[str, list[Producto]] = {}
    por_nombre: dict[str, list[Producto]] = {}
    for p in productos:
        if p.clave:
            por_clave[p.clave] = p
            por_clave_sin_ceros.setdefault(p.clave.lstrip("0"), []).append(p)
        por_nombre.setdefault(_comparable(p.nombre), []).append(p)
    categorias = {_normal(c.nombre): c for c in db.scalars(select(Categoria).where(Categoria.negocio_id == negocio.id))}
    vistos: dict[str, int] = {}  # clave o nombre -> renglón donde apareció primero

    def buscar(d: Datos) -> Producto | None:
        if d.clave:
            if d.clave in por_clave:
                return por_clave[d.clave]
            iguales = por_clave_sin_ceros.get(d.clave.lstrip("0"), [])
            return iguales[0] if len(iguales) == 1 else None
        iguales = por_nombre.get(_comparable(d.nombre or ""), [])
        if len(iguales) > 1:
            raise ValueError("Hay varios productos con ese nombre; pon la clave para saber cuál es")
        return iguales[0] if iguales else None

    def categoria_de(nombre: str) -> Categoria:
        clave = _normal(nombre)
        if clave not in categorias:
            categorias[clave] = Categoria(negocio_id=negocio.id, nombre=nombre)
            r.categorias_nuevas.append(nombre)
            if guardar:
                db.add(categorias[clave])
                db.flush()
        return categorias[clave]

    for renglon in renglones:
        try:
            d = _revisar(renglon.valores)
            if not d.clave and not d.nombre:
                raise ValueError("Falta la clave y el nombre")
            llave = f"clave:{d.clave}" if d.clave else f"nombre:{_comparable(d.nombre or '')}"
            if llave in vistos:
                raise ValueError(f"Repetido: ya venía en el renglón {vistos[llave]}")
            vistos[llave] = renglon.numero
            producto = buscar(d)
            if producto is None and not d.nombre:
                raise ValueError("Falta el nombre (es un producto nuevo)")
        except ValueError as e:
            r.errores.append({"renglon": renglon.numero, "clave": _texto(renglon.valores.get("clave")),
                              "nombre": _texto(renglon.valores.get("nombre")), "error": str(e)})
            continue

        if producto is None:
            r.nuevos.append({"renglon": renglon.numero, "clave": d.clave, "nombre": d.nombre, "precio": d.precio,
                             "existencia": d.existencia})
            if d.categoria:
                categoria_de(d.categoria)
            if d.existencia:
                r.piezas += d.existencia
            if guardar:
                _crear(db, usuario, negocio, d, categoria_de(d.categoria) if d.categoria else None)
            continue

        cambios = _cambios(producto, d, categorias)
        if d.existencia:
            r.existencia_ignorada += 1
        if not cambios:
            r.sin_cambios += 1
            continue
        r.actualizados.append({"renglon": renglon.numero, "clave": producto.clave, "nombre": producto.nombre,
                               "cambios": ", ".join(cambios)})
        if d.categoria and _normal(d.categoria) not in categorias:
            categoria_de(d.categoria)
        if guardar:
            _actualizar(db, usuario, producto, d, categoria_de(d.categoria) if d.categoria else None)

    if guardar:
        db.flush()
    return r, encabezados


def _cambios(p: Producto, d: Datos, categorias: dict[str, Categoria]) -> list[str]:
    """Qué cambiaría en un producto que ya existe (texto para la persona)."""
    cambios = []
    if d.nombre and d.nombre != p.nombre:
        cambios.append("nombre")
    if d.precio is not None and d.precio != p.precio_venta:
        cambios.append(f"precio {p.precio_venta or 'sin precio'} → {d.precio}")
    if d.costo is not None and d.costo != p.costo:
        cambios.append("costo")
    if d.iva is not None and d.iva != p.iva_porcentaje:
        cambios.append(f"IVA {p.iva_porcentaje.normalize():f}% → {d.iva.normalize():f}%")
    if d.ieps is not None and d.ieps != p.ieps_porcentaje:
        cambios.append(f"IEPS {p.ieps_porcentaje.normalize():f}% → {d.ieps.normalize():f}%")
    if d.categoria:
        actual = next((c for c in categorias.values() if c.id is not None and c.id == p.categoria_id), None)
        if actual is None or _normal(actual.nombre) != _normal(d.categoria):
            cambios.append("categoría")
    if d.laboratorio and d.laboratorio != p.laboratorio:
        cambios.append("laboratorio")
    if d.clave_sat and d.clave_sat != p.clave_sat:
        cambios.append("clave SAT")
    if d.minimo is not None and d.minimo != p.minimo:
        cambios.append("mínimo")
    if d.maximo is not None and d.maximo != p.maximo:
        cambios.append("máximo")
    if d.receta is not None and d.receta != p.requiere_receta:
        cambios.append("receta")
    return cambios


def _crear(db: Session, usuario: Usuario, negocio: Negocio, d: Datos, categoria: Categoria | None) -> None:
    p = Producto(
        negocio_id=negocio.id, categoria_id=categoria.id if categoria else None, clave=d.clave, nombre=d.nombre,
        precio_venta=d.precio, costo=d.costo, iva_porcentaje=d.iva or Decimal(0), ieps_porcentaje=d.ieps or Decimal(0),
        laboratorio=d.laboratorio, clave_sat=d.clave_sat, minimo=d.minimo, maximo=d.maximo,
        requiere_receta=bool(d.receta),
    )
    db.add(p)
    db.flush()
    if p.precio_venta is not None:
        registrar_precio(db, p, None, usuario.id, ORIGEN_PRECIO)
    if d.existencia:
        lote = Lote(negocio_id=negocio.id, producto_id=p.id, cantidad=d.existencia, costo_unitario=d.costo)
        db.add(lote)
        db.flush()
        db.add(AjusteInventario(negocio_id=negocio.id, producto_id=p.id, lote_id=lote.id, usuario_id=usuario.id,
                                tipo=TipoAjuste.IMPORTACION, cantidad=d.existencia, motivo=MOTIVO_EXISTENCIA))


def _actualizar(db: Session, usuario: Usuario, p: Producto, d: Datos, categoria: Categoria | None) -> None:
    anterior = p.precio_venta
    if d.nombre:
        p.nombre = d.nombre
    if d.precio is not None:
        p.precio_venta = d.precio
    for campo, valor in (("costo", d.costo), ("iva_porcentaje", d.iva), ("ieps_porcentaje", d.ieps),
                         ("laboratorio", d.laboratorio), ("clave_sat", d.clave_sat), ("minimo", d.minimo),
                         ("maximo", d.maximo), ("requiere_receta", d.receta)):
        if valor is not None:
            setattr(p, campo, valor)
    if categoria is not None:
        p.categoria_id = categoria.id
    registrar_precio(db, p, anterior, usuario.id, ORIGEN_PRECIO)

