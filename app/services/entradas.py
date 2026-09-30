"""Entradas de mercancía.

Tres formas de llenar una entrada (manual, XML del CFDI, PDF o foto leídos
con IA) que terminan en la misma pantalla de revisión: nada de lo leído entra
directo al inventario. Al confirmar:
- cada renglón crea (o suma a) su lote: con caducidad, al lote de esa
  caducidad y número; sin caducidad, al lote "sin caducidad" del producto;
- el costo del producto pasa a ser el de la factura (por pieza);
- si se eligió, el precio de venta pasa al sugerido por el margen de la
  categoría (solo un administrador) y queda en el historial de precios;
- se guarda la equivalencia "cómo lo llama el proveedor" -> producto, para
  reconocerlo solo la siguiente vez.

Una factura (proveedor + folio) entra una sola vez.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.importador.facturas import FacturaLeida
from app.models import (
    ArchivoFactura, Categoria, Entrada, EntradaRenglon, Lote, Producto, Proveedor, ProveedorEquivalencia,
    RolUsuario, Usuario,
)
from app.services import catalogo, inventario
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso

ROLES_ENTRADA = {RolUsuario.ADMIN, RolUsuario.BODEGA}
CENTAVO = Decimal("0.01")
ARCHIVO_MAXIMO = 10 * 1024 * 1024


def _validar_rol(usuario: Usuario) -> None:
    if usuario.rol not in ROLES_ENTRADA:
        raise SinPermiso("Las entradas de mercancía las registran bodega o un administrador")


def comparable(texto: str | None) -> str:
    """Descripción para comparar: sin espacios ni signos, en mayúsculas."""
    return re.sub(r"[^0-9A-ZÁÉÍÓÚÜÑ]", "", (texto or "").upper())


# --- Proveedores --------------------------------------------------------------

def crear_proveedor(db: Session, usuario: Usuario, nombre: str, rfc: str | None) -> Proveedor:
    _validar_rol(usuario)
    nombre = " ".join((nombre or "").split())
    if not nombre:
        raise OperacionInvalida("El proveedor necesita un nombre")
    rfc = (rfc or "").strip().upper() or None
    if rfc and not re.fullmatch(r"[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}", rfc):
        raise OperacionInvalida("El RFC no tiene el formato correcto (12 o 13 caracteres)")
    for campo, valor, texto in ((Proveedor.nombre, nombre, "ese nombre"), (Proveedor.rfc, rfc, "ese RFC")):
        if valor and db.scalar(select(Proveedor.id).where(Proveedor.negocio_id == usuario.negocio_id, campo == valor)):
            raise OperacionInvalida(f"Ya existe un proveedor con {texto}")
    proveedor = Proveedor(negocio_id=usuario.negocio_id, nombre=nombre, rfc=rfc)
    db.add(proveedor)
    db.flush()
    return proveedor


def _proveedor(db: Session, negocio_id: int, proveedor_id: int) -> Proveedor:
    p = db.get(Proveedor, proveedor_id)
    if p is None or p.negocio_id != negocio_id:
        raise NoEncontrado("Proveedor no encontrado")
    return p


# --- Archivos -----------------------------------------------------------------

def tipo_de_archivo(datos: bytes) -> str | None:
    """Tipo según los primeros bytes (no se confía en el nombre)."""
    inicio = datos[:512].lstrip()
    if datos.startswith(b"%PDF"):
        return "application/pdf"
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if datos.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    if datos[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if inicio.startswith(b"\xef\xbb\xbf"):
        inicio = inicio[3:]
    if inicio.startswith(b"<?xml") or inicio.startswith(b"<cfdi:"):
        return "application/xml"
    return None


def guardar_archivo(db: Session, usuario: Usuario, nombre: str, datos: bytes) -> ArchivoFactura:
    _validar_rol(usuario)
    if not datos:
        raise OperacionInvalida("El archivo está vacío")
    if len(datos) > ARCHIVO_MAXIMO:
        raise OperacionInvalida("El archivo es muy pesado; el máximo es 10 MB")
    tipo = tipo_de_archivo(datos)
    if tipo is None:
        raise OperacionInvalida("El archivo debe ser XML, PDF o una imagen (PNG, JPG, WEBP o GIF)")
    archivo = ArchivoFactura(
        negocio_id=usuario.negocio_id, usuario_id=usuario.id, nombre=(nombre or "factura")[:200], tipo=tipo, datos=datos,
    )
    db.add(archivo)
    db.flush()
    return archivo


# --- Reconocer productos ----------------------------------------------------

def digito_verificador(codigo: str) -> str:
    """Dígito verificador GS1 (EAN/UPC) de un código sin él."""
    suma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(codigo)))
    return str((10 - suma % 10) % 10)


def _por_codigo(db: Session, negocio_id: int, clave: str) -> Producto | None:
    return db.scalar(select(Producto).where(
        Producto.negocio_id == negocio_id, Producto.activo.is_(True),
        (Producto.clave == clave) | (func.ltrim(Producto.clave, "0") == clave.lstrip("0")),
    ).limit(1))


def reconocer(
    db: Session, negocio_id: int, proveedor_id: int | None, clave: str | None, descripcion: str | None,
) -> tuple[Producto | None, Decimal, str | None]:
    """(producto, factor, cómo se reconoció). Primero la equivalencia del
    proveedor (por su clave o por la descripción), después el código de
    barras en el catálogo. Walmart manda el código con ceros a la izquierda y
    sin el dígito verificador ("000750647512078"): si no se encuentra tal cual,
    se prueba agregándoselo."""
    if proveedor_id is not None:
        stmt = select(ProveedorEquivalencia).where(ProveedorEquivalencia.proveedor_id == proveedor_id)
        eq = None
        if clave:
            eq = db.scalar(stmt.where(ProveedorEquivalencia.clave_proveedor == clave).order_by(ProveedorEquivalencia.id.desc()))
        if eq is None and descripcion:
            eq = db.scalar(stmt.where(ProveedorEquivalencia.descripcion == comparable(descripcion)))
        if eq is not None:
            producto = db.get(Producto, eq.producto_id)
            if producto is not None and producto.activo:
                return producto, eq.factor, "equivalencia"
    if clave and clave.lstrip("0"):
        producto = _por_codigo(db, negocio_id, clave)
        sin_ceros = clave.lstrip("0")
        if producto is None and sin_ceros.isdigit() and len(sin_ceros) in (11, 12):
            producto = _por_codigo(db, negocio_id, sin_ceros + digito_verificador(sin_ceros))
        if producto is not None:
            return producto, Decimal(producto.factor_conversion or 1), "codigo"
    return None, Decimal(1), None


def datos_producto(db: Session, producto: Producto) -> dict:
    """Lo que la revisión necesita para mostrar costo, precio y sugerido."""
    margen = limite_costo = margen_arriba_limite = None
    controla = True
    if producto.categoria_id is not None:
        categoria = db.get(Categoria, producto.categoria_id)
        margen = categoria.margen_porcentaje
        limite_costo, margen_arriba_limite = categoria.limite_costo, categoria.margen_arriba_limite
        controla = categoria.controla_lote
    controla = controla and not producto.no_caduca
    return {
        "id": producto.id, "nombre": producto.nombre, "clave": producto.clave,
        "costo": producto.costo, "precio_venta": producto.precio_venta,
        "precio_maximo_publico": producto.precio_maximo_publico,
        "iva_porcentaje": producto.iva_porcentaje, "ieps_porcentaje": producto.ieps_porcentaje,
        "margen": margen, "limite_costo": limite_costo, "margen_arriba_limite": margen_arriba_limite,
        "controla_lote": controla, "factor_conversion": producto.factor_conversion,
    }


def borrador(db: Session, usuario: Usuario, leida: FacturaLeida, archivo: ArchivoFactura | None) -> dict:
    """La factura leída lista para la pantalla de revisión: proveedor
    reconocido por RFC (o por nombre) y cada renglón con su producto si ya se
    conoce."""
    _validar_rol(usuario)
    proveedor = None
    if leida.proveedor_rfc:
        proveedor = db.scalar(select(Proveedor).where(
            Proveedor.negocio_id == usuario.negocio_id, Proveedor.rfc == leida.proveedor_rfc,
        ))
    if proveedor is None and leida.proveedor_nombre:
        proveedor = db.scalar(select(Proveedor).where(
            Proveedor.negocio_id == usuario.negocio_id,
            func.upper(Proveedor.nombre) == leida.proveedor_nombre.upper(),
        ))
    renglones = []
    for r in leida.renglones:
        producto, factor, como = reconocer(db, usuario.negocio_id, proveedor.id if proveedor else None, r.clave, r.descripcion)
        renglones.append({
            "descripcion": r.descripcion, "clave": r.clave, "unidad": r.unidad,
            "cantidad": r.cantidad, "costo_unitario": r.costo_unitario, "importe": r.importe,
            "iva": r.iva, "ieps": r.ieps, "numero_lote": r.numero_lote, "caducidad": r.caducidad,
            "dudoso": r.dudoso, "nota": r.nota,
            "producto": datos_producto(db, producto) if producto else None,
            "factor": factor, "reconocido": como,
        })
    return {
        "origen": leida.origen,
        "archivo_id": archivo.id if archivo else None,
        "archivo_nombre": archivo.nombre if archivo else None,
        "proveedor_id": proveedor.id if proveedor else None,
        "proveedor_nombre": leida.proveedor_nombre,
        "proveedor_rfc": leida.proveedor_rfc,
        "folio": leida.folio,
        "fecha_factura": leida.fecha,
        "subtotal": leida.subtotal,
        "total": leida.total,
        "dudas": leida.dudas,
        "renglones": renglones,
    }


# --- Registrar ----------------------------------------------------------------

@dataclass
class RenglonEntrada:
    producto_id: int
    cantidad: Decimal
    costo_unitario: Decimal
    factor: Decimal = Decimal(1)
    numero_lote: str | None = None
    caducidad: date | None = None
    descripcion_proveedor: str | None = None
    clave_proveedor: str | None = None
    aplicar_precio: bool = False


def _lote_destino(db: Session, producto: Producto, numero_lote: str | None, caducidad: date | None) -> Lote:
    if caducidad is None:
        return inventario.lote_sin_caducidad(db, producto, crear=True)
    lote = db.scalar(select(Lote).where(
        Lote.producto_id == producto.id, Lote.caducidad == caducidad,
        Lote.numero_lote.is_not_distinct_from(numero_lote),
    ).with_for_update())
    if lote is None:
        lote = Lote(negocio_id=producto.negocio_id, producto_id=producto.id, numero_lote=numero_lote,
                    caducidad=caducidad, cantidad=Decimal(0))
        db.add(lote)
        db.flush()
    return lote


def _guardar_equivalencia(db: Session, negocio_id: int, proveedor_id: int, r: RenglonEntrada) -> None:
    descripcion = comparable(r.descripcion_proveedor)
    if not descripcion:
        return
    eq = db.scalar(select(ProveedorEquivalencia).where(
        ProveedorEquivalencia.proveedor_id == proveedor_id, ProveedorEquivalencia.descripcion == descripcion,
    ))
    if eq is None:
        eq = ProveedorEquivalencia(negocio_id=negocio_id, proveedor_id=proveedor_id, descripcion=descripcion,
                                   producto_id=r.producto_id)
        db.add(eq)
    eq.producto_id = r.producto_id
    eq.factor = r.factor
    eq.clave_proveedor = (r.clave_proveedor or "").strip() or None


def registrar(
    db: Session,
    usuario: Usuario,
    proveedor_id: int,
    folio: str,
    fecha_recepcion: date,
    renglones: list[RenglonEntrada],
    origen: str = "manual",
    fecha_factura: date | None = None,
    total_factura: Decimal | None = None,
    archivo_id: int | None = None,
    notas: str | None = None,
) -> Entrada:
    """No hace commit."""
    _validar_rol(usuario)
    proveedor = _proveedor(db, usuario.negocio_id, proveedor_id)
    folio = " ".join((folio or "").split()).upper()
    if not folio:
        raise OperacionInvalida("Falta el folio de la factura")
    if not renglones:
        raise OperacionInvalida("La entrada no tiene productos")
    if origen not in ("manual", "xml", "ia"):
        raise OperacionInvalida("Origen inválido")
    if db.scalar(select(Entrada.id).where(
        Entrada.negocio_id == usuario.negocio_id, Entrada.proveedor_id == proveedor.id, Entrada.folio == folio,
    )):
        raise OperacionInvalida(f"La factura {folio} de {proveedor.nombre} ya se registró")
    if any(r.aplicar_precio for r in renglones) and usuario.rol != RolUsuario.ADMIN:
        raise SinPermiso("Solo un administrador cambia precios de venta")
    archivo = None
    if archivo_id is not None:
        archivo = db.get(ArchivoFactura, archivo_id)
        if archivo is None or archivo.negocio_id != usuario.negocio_id or archivo.entrada_id is not None:
            raise NoEncontrado("Archivo de la factura no encontrado")

    entrada = Entrada(
        negocio_id=usuario.negocio_id, proveedor_id=proveedor.id, folio=folio, fecha_factura=fecha_factura,
        fecha_recepcion=fecha_recepcion, origen=origen, usuario_id=usuario.id, total_factura=total_factura,
        subtotal=Decimal(0), notas=(notas or "").strip() or None,
    )
    db.add(entrada)
    db.flush()

    subtotal = Decimal(0)
    for r in renglones:
        producto = inventario.obtener_producto(db, usuario.negocio_id, r.producto_id)
        if not producto.activo:
            raise OperacionInvalida(f"{producto.nombre} está desactivado")
        if r.cantidad <= 0 or r.factor <= 0:
            raise OperacionInvalida(f"Cantidad inválida para {producto.nombre}")
        if r.costo_unitario < 0:
            raise OperacionInvalida(f"Costo inválido para {producto.nombre}")
        numero_lote = (r.numero_lote or "").strip().upper() or None
        piezas = (r.cantidad * r.factor).quantize(CENTAVO, ROUND_HALF_UP)
        costo_pieza = (r.costo_unitario / r.factor).quantize(Decimal("0.0001"), ROUND_HALF_UP)

        lote = _lote_destino(db, producto, numero_lote, r.caducidad)
        lote.cantidad += piezas
        lote.costo_unitario = costo_pieza

        renglon = EntradaRenglon(
            producto_id=producto.id, descripcion_proveedor=r.descripcion_proveedor, clave_proveedor=r.clave_proveedor,
            cantidad=r.cantidad, factor=r.factor, piezas=piezas, costo_unitario=r.costo_unitario,
            costo_pieza=costo_pieza, lote_id=lote.id, numero_lote=numero_lote, caducidad=r.caducidad,
            costo_anterior=producto.costo, precio_anterior=producto.precio_venta,
        )
        producto.costo = costo_pieza
        if r.aplicar_precio:
            nuevo = catalogo.precio_sugerido(db, producto, costo_pieza)
            if nuevo is None:
                raise OperacionInvalida(f"{producto.nombre} no tiene precio sugerido: su categoría no tiene margen")
            anterior = producto.precio_venta
            producto.precio_venta = nuevo
            renglon.precio_nuevo = nuevo
            catalogo.registrar_precio(db, producto, anterior, usuario.id, f"Entrada de mercancía (factura {folio})")
        entrada.renglones.append(renglon)
        subtotal += (r.cantidad * r.costo_unitario)
        _guardar_equivalencia(db, usuario.negocio_id, proveedor.id, r)
        db.flush()

    entrada.subtotal = subtotal.quantize(CENTAVO, ROUND_HALF_UP)
    if archivo is not None:
        archivo.entrada_id = entrada.id
    db.flush()
    return entrada
