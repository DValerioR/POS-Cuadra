"""Reglas de inventario por lote. Aquí vive la lógica; los endpoints de
app/api/inventario.py solo traducen HTTP. Las ventas (etapa 2) usarán
lotes_fefo() para decidir de qué lote descontar.

Todo cambio de existencia deja un renglón en ajustes_inventario con usuario
y motivo; nada se borra.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AjusteInventario, Categoria, Lote, Producto, RolUsuario, TipoAjuste, Usuario

# Quién puede hacer cada operación. La captura de caducidad la hace también
# mostrador, porque ocurre al vender con la caja en la mano.
ROLES_AJUSTE = {RolUsuario.ADMIN, RolUsuario.BODEGA}
ROLES_CAPTURA = {RolUsuario.ADMIN, RolUsuario.BODEGA, RolUsuario.MOSTRADOR}


class NoEncontrado(Exception):
    pass


class OperacionInvalida(Exception):
    pass


class SinPermiso(Exception):
    pass


# --- Consultas ------------------------------------------------------------

def obtener_producto(db: Session, negocio_id: int, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None or producto.negocio_id != negocio_id:
        raise NoEncontrado("Producto no encontrado")
    return producto


def controla_lote(db: Session, producto: Producto) -> bool:
    """Sin categoría se asume que sí controla lote (lo más seguro en farmacia)."""
    if producto.categoria_id is None:
        return True
    return db.get(Categoria, producto.categoria_id).controla_lote


def lotes_fefo(db: Session, producto_id: int, bloquear: bool = False) -> list[Lote]:
    """Lotes con existencia en orden FEFO: primero el que caduca antes. Los
    lotes sin caducidad registrada van al final, porque no se sabe cuándo
    caducan; la venta (etapa 2) decidirá cómo tratarlos."""
    stmt = (
        select(Lote)
        .where(Lote.producto_id == producto_id, Lote.cantidad > 0)
        .order_by(Lote.caducidad.asc().nulls_last(), Lote.id)
    )
    if bloquear:
        stmt = stmt.with_for_update()
    return list(db.scalars(stmt))


def avance_caducidades(db: Session, negocio_id: int, limite: int, desplazamiento: int) -> dict:
    """Cuántas piezas siguen sin caducidad (inventario heredado de PVWin), solo
    de productos cuya categoría controla lote."""
    controla = (Producto.categoria_id.is_(None)) | (Categoria.controla_lote.is_(True))
    base = (
        select(Lote)
        .join(Producto, Producto.id == Lote.producto_id)
        .outerjoin(Categoria, Categoria.id == Producto.categoria_id)
        .where(Lote.negocio_id == negocio_id, Lote.cantidad > 0, controla)
        .subquery()
    )
    total = db.scalar(select(func.coalesce(func.sum(base.c.cantidad), 0)))
    sin_caducidad = db.scalar(
        select(func.coalesce(func.sum(base.c.cantidad), 0)).where(base.c.caducidad.is_(None))
    )

    pendientes = (
        select(
            Producto.id.label("producto_id"),
            Producto.clave,
            Producto.nombre,
            func.sum(base.c.cantidad).label("piezas_sin_caducidad"),
        )
        .join(base, base.c.producto_id == Producto.id)
        .where(base.c.caducidad.is_(None))
        .group_by(Producto.id)
    )
    productos_pendientes = db.scalar(select(func.count()).select_from(pendientes.subquery()))
    # Los de más piezas primero: capturarlos avanza más la migración.
    filas = db.execute(
        pendientes.order_by(func.sum(base.c.cantidad).desc(), Producto.nombre)
        .limit(limite)
        .offset(desplazamiento)
    ).mappings()

    return {
        "piezas_total": total,
        "piezas_sin_caducidad": sin_caducidad,
        "porcentaje_capturado": (
            round((total - sin_caducidad) * 100 / total, 1) if total else Decimal(100)
        ),
        "productos_pendientes": productos_pendientes,
        "productos": [dict(f) for f in filas],
    }


# --- Operaciones ----------------------------------------------------------

def _validar_usuario(db: Session, negocio_id: int, usuario_id: int, roles: set[RolUsuario]) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or usuario.negocio_id != negocio_id or not usuario.activo:
        raise NoEncontrado("Usuario no encontrado")
    if usuario.rol not in roles:
        raise SinPermiso(f"El rol {usuario.rol.value} no puede hacer esta operación")
    return usuario


def _lote_sin_caducidad(db: Session, producto: Producto, crear: bool) -> Lote | None:
    """El lote especial (sin número ni caducidad) de un producto, bloqueado para escritura."""
    lote = db.scalar(
        select(Lote)
        .where(Lote.producto_id == producto.id, Lote.caducidad.is_(None), Lote.numero_lote.is_(None))
        .order_by(Lote.id)
        .limit(1)
        .with_for_update()
    )
    if lote is None and crear:
        lote = Lote(
            negocio_id=producto.negocio_id,
            producto_id=producto.id,
            cantidad=Decimal(0),
            costo_unitario=producto.costo,
        )
        db.add(lote)
        db.flush()
    return lote


def _registrar(db: Session, lote: Lote, usuario: Usuario, tipo: TipoAjuste, cantidad: Decimal, motivo: str) -> AjusteInventario:
    if lote.cantidad + cantidad < 0:
        raise OperacionInvalida(
            f"El lote solo tiene {lote.cantidad} piezas; no se pueden quitar {-cantidad}"
        )
    lote.cantidad += cantidad
    ajuste = AjusteInventario(
        negocio_id=lote.negocio_id,
        producto_id=lote.producto_id,
        lote_id=lote.id,
        usuario_id=usuario.id,
        tipo=tipo,
        cantidad=cantidad,
        motivo=motivo,
    )
    db.add(ajuste)
    return ajuste


def capturar_caducidad(
    db: Session,
    negocio_id: int,
    usuario_id: int,
    producto_id: int,
    caducidad: date,
    cantidad: Decimal,
    numero_lote: str | None = None,
) -> Lote:
    """Pasa `cantidad` piezas del lote sin caducidad a un lote real. Si ya hay
    un lote con la misma caducidad y número, se suman ahí. Genera dos ajustes:
    -N en el lote sin caducidad y +N en el real. No hace commit."""
    usuario = _validar_usuario(db, negocio_id, usuario_id, ROLES_CAPTURA)
    producto = obtener_producto(db, negocio_id, producto_id)
    if not controla_lote(db, producto):
        raise OperacionInvalida("La categoría de este producto no maneja lote ni caducidad")
    if cantidad <= 0:
        raise OperacionInvalida("La cantidad debe ser mayor que cero")

    origen = _lote_sin_caducidad(db, producto, crear=False)
    disponibles = origen.cantidad if origen else Decimal(0)
    if cantidad > disponibles:
        raise OperacionInvalida(f"Solo hay {disponibles} piezas sin caducidad registrada")

    numero_lote = (numero_lote or "").strip() or None
    destino = db.scalar(
        select(Lote)
        .where(
            Lote.producto_id == producto.id,
            Lote.caducidad == caducidad,
            Lote.numero_lote.is_not_distinct_from(numero_lote),
        )
        .with_for_update()
    )
    if destino is None:
        destino = Lote(
            negocio_id=negocio_id,
            producto_id=producto.id,
            numero_lote=numero_lote,
            caducidad=caducidad,
            cantidad=Decimal(0),
            costo_unitario=origen.costo_unitario,
        )
        db.add(destino)
        db.flush()

    descripcion = f"caducidad {caducidad:%Y-%m-%d}" + (f", lote {numero_lote}" if numero_lote else "")
    _registrar(db, origen, usuario, TipoAjuste.CAPTURA_CADUCIDAD, -cantidad, f"Pasa a {descripcion}")
    _registrar(db, destino, usuario, TipoAjuste.CAPTURA_CADUCIDAD, cantidad, f"Capturada {descripcion}")
    return destino


def ajustar(
    db: Session,
    negocio_id: int,
    usuario_id: int,
    producto_id: int,
    tipo: TipoAjuste,
    cantidad: Decimal,
    motivo: str,
    lote_id: int | None = None,
) -> AjusteInventario:
    """Ajuste (+/-) o merma (-) sobre un lote. Sin lote_id se usa el lote sin
    caducidad del producto, creándolo si hace falta (ej. conteo físico de un
    producto que se importó en cero). No hace commit."""
    usuario = _validar_usuario(db, negocio_id, usuario_id, ROLES_AJUSTE)
    producto = obtener_producto(db, negocio_id, producto_id)
    if tipo not in (TipoAjuste.AJUSTE, TipoAjuste.MERMA):
        raise OperacionInvalida("Solo se pueden registrar ajustes o mermas")
    if cantidad == 0:
        raise OperacionInvalida("La cantidad no puede ser cero")
    if tipo == TipoAjuste.MERMA and cantidad > 0:
        raise OperacionInvalida("Una merma saca piezas: la cantidad debe ser negativa")
    motivo = motivo.strip()
    if not motivo:
        raise OperacionInvalida("El motivo es obligatorio")

    if lote_id is None:
        lote = _lote_sin_caducidad(db, producto, crear=cantidad > 0)
        if lote is None:
            raise OperacionInvalida("El producto no tiene piezas sin caducidad; indica el lote")
    else:
        lote = db.scalar(select(Lote).where(Lote.id == lote_id).with_for_update())
        if lote is None or lote.producto_id != producto.id:
            raise NoEncontrado("Lote no encontrado para ese producto")

    return _registrar(db, lote, usuario, tipo, cantidad, motivo)
