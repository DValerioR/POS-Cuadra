"""Catálogo y precios: historial de precios y cambios en grupo.

El precio de venta incluye impuestos (IEPS sobre la base, IVA sobre base +
IEPS) y se redondea como diga el negocio (services/precios.py). Todo cambio
de precio queda en precios_historial con quién y desde dónde.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Categoria, Negocio, PrecioHistorial, Producto, RolUsuario, Usuario
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso
from app.services.precios import redondear_precio_venta

CENTAVO = Decimal("0.01")
IVAS = {Decimal(0), Decimal(16)}


def registrar_precio(
    db: Session, producto: Producto, anterior: Decimal | None, usuario_id: int | None, origen: str,
) -> None:
    """Anota el cambio si el precio de venta cambió. No hace commit."""
    if anterior == producto.precio_venta:
        return
    db.add(PrecioHistorial(
        negocio_id=producto.negocio_id, producto_id=producto.id, usuario_id=usuario_id,
        precio_anterior=anterior, precio_nuevo=producto.precio_venta, origen=origen,
    ))


def precio_con_otro_iva(
    precio: Decimal, iva_antes: Decimal, iva_nuevo: Decimal, ieps: Decimal,
    paso: Decimal | None, maximo: Decimal | None,
) -> Decimal:
    """Precio de venta que deja igual el precio sin impuestos al cambiar el IVA."""
    base = precio / ((1 + Decimal(ieps) / 100) * (1 + Decimal(iva_antes) / 100))
    nuevo = (base * (1 + Decimal(ieps) / 100) * (1 + Decimal(iva_nuevo) / 100)).quantize(CENTAVO, ROUND_HALF_UP)
    return redondear_precio_venta(nuevo, paso, maximo)


def cambiar_en_grupo(
    db: Session,
    usuario: Usuario,
    ids: list[int],
    categoria_id: int | None = None,
    quitar_categoria: bool = False,
    iva: Decimal | None = None,
    ajustar_precio: bool = False,
    revisado: bool = False,
) -> int:
    """Aplica a varios productos a la vez: categoría, IVA (con o sin ajustar
    el precio para que el precio sin impuestos no cambie) y/o "ya revisado".
    Regresa cuántos productos se tocaron. No hace commit."""
    if usuario.rol != RolUsuario.ADMIN:
        raise SinPermiso("Solo un administrador cambia el catálogo")
    if not ids:
        raise OperacionInvalida("Elige al menos un producto")
    if categoria_id is None and not quitar_categoria and iva is None and not revisado:
        raise OperacionInvalida("No hay nada que cambiar")
    if categoria_id is not None:
        categoria = db.get(Categoria, categoria_id)
        if categoria is None or categoria.negocio_id != usuario.negocio_id:
            raise NoEncontrado("Categoría no encontrada")
    if iva is not None and iva not in IVAS:
        raise OperacionInvalida("El IVA solo puede ser 0% o 16%")

    productos = db.scalars(
        select(Producto).where(Producto.negocio_id == usuario.negocio_id, Producto.id.in_(set(ids))).with_for_update()
    ).all()
    if len(productos) != len(set(ids)):
        raise NoEncontrado("Algún producto no existe")
    paso = db.get(Negocio, usuario.negocio_id).redondeo_precio_venta

    for p in productos:
        if categoria_id is not None:
            p.categoria_id = categoria_id
        elif quitar_categoria:
            p.categoria_id = None
        if iva is not None and iva != p.iva_porcentaje:
            if ajustar_precio and p.precio_venta is not None:
                anterior = p.precio_venta
                p.precio_venta = precio_con_otro_iva(
                    p.precio_venta, p.iva_porcentaje, iva, p.ieps_porcentaje, paso, p.precio_maximo_publico,
                )
                registrar_precio(db, p, anterior, usuario.id, f"Cambio en grupo (IVA {p.iva_porcentaje.normalize():f}% → {iva.normalize():f}%)")
            p.iva_porcentaje = iva
        if revisado:
            p.requiere_revision = False
            p.motivo_revision = None
    db.flush()
    return len(productos)


def precio_sugerido(db: Session, producto: Producto, costo_pieza: Decimal | None) -> Decimal | None:
    """Costo + margen de su categoría + impuestos, con el redondeo del negocio
    y sin pasar el precio máximo. None si falta el costo o la categoría no
    tiene margen."""
    if costo_pieza is None or producto.categoria_id is None:
        return None
    categoria = db.get(Categoria, producto.categoria_id)
    if categoria is None or categoria.margen_porcentaje is None:
        return None
    base = Decimal(costo_pieza) * (1 + categoria.margen_porcentaje / 100)
    con_impuestos = (
        base * (1 + Decimal(producto.ieps_porcentaje) / 100) * (1 + Decimal(producto.iva_porcentaje) / 100)
    ).quantize(CENTAVO, ROUND_HALF_UP)
    paso = db.get(Negocio, producto.negocio_id).redondeo_precio_venta
    return redondear_precio_venta(con_impuestos, paso, producto.precio_maximo_publico)
