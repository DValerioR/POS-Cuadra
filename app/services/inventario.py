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
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso

# Quién puede hacer cada operación. La captura de caducidad la hace también
# mostrador, porque ocurre al vender con la caja en la mano.
ROLES_AJUSTE = {RolUsuario.ADMIN, RolUsuario.BODEGA}
ROLES_CAPTURA = {RolUsuario.ADMIN, RolUsuario.BODEGA, RolUsuario.MOSTRADOR}


# --- Consultas ------------------------------------------------------------

def obtener_producto(db: Session, negocio_id: int, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None or producto.negocio_id != negocio_id:
        raise NoEncontrado("Producto no encontrado")
    return producto


def controla_lote(db: Session, producto: Producto) -> bool:
    """Sin categoría se asume que sí controla lote (lo más seguro en farmacia).
    Un producto marcado "no caduca" nunca lo controla."""
    if producto.no_caduca:
        return False
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
    de productos cuya categoría controla lote y que no están marcados "no caduca"."""
    controla = ((Producto.categoria_id.is_(None)) | (Categoria.controla_lote.is_(True))) & Producto.no_caduca.is_(False)
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

def marcar_no_caduca(db: Session, negocio_id: int, usuario_id: int, producto_id: int, no_caduca: bool) -> Producto:
    """Marca (o desmarca) que el producto no caduca. Sus piezas se quedan en el
    lote sin caducidad; solo deja de pedirse la caducidad. No hace commit."""
    _validar_usuario(db, negocio_id, usuario_id, ROLES_AJUSTE)
    producto = obtener_producto(db, negocio_id, producto_id)
    producto.no_caduca = no_caduca
    return producto


def _validar_usuario(db: Session, negocio_id: int, usuario_id: int, roles: set[RolUsuario]) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or usuario.negocio_id != negocio_id or not usuario.activo:
        raise NoEncontrado("Usuario no encontrado")
    if usuario.rol not in roles:
        raise SinPermiso(f"El rol {usuario.rol.value} no puede hacer esta operación")
    return usuario


def lote_sin_caducidad(db: Session, producto: Producto, crear: bool) -> Lote | None:
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

    origen = lote_sin_caducidad(db, producto, crear=False)
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
        lote = lote_sin_caducidad(db, producto, crear=cantidad > 0)
        if lote is None:
            raise OperacionInvalida("El producto no tiene piezas sin caducidad; indica el lote")
    else:
        lote = db.scalar(select(Lote).where(Lote.id == lote_id).with_for_update())
        if lote is None or lote.producto_id != producto.id:
            raise NoEncontrado("Lote no encontrado para ese producto")

    return _registrar(db, lote, usuario, tipo, cantidad, motivo)


def existencia_total(db: Session, producto_id: int) -> Decimal:
    """Suma de todos los lotes, incluido el sin caducidad aunque esté en
    negativo (piezas vendidas que el sistema no tenía registradas)."""
    return db.scalar(select(func.coalesce(func.sum(Lote.cantidad), 0)).where(Lote.producto_id == producto_id))


def fijar_existencia(
    db: Session, negocio_id: int, usuario_id: int, producto_id: int, conteo: Decimal, motivo: str,
) -> list[AjusteInventario]:
    """Deja la existencia del producto igual al conteo físico, con ajustes
    registrados. Los lotes con caducidad se respetan mientras alcance el
    conteo; lo demás queda en el lote sin caducidad (que ya no queda en
    negativo). Si el conteo es menor que lo que hay en lotes con caducidad,
    se quitan primero de los que caducan antes. No hace commit."""
    usuario = _validar_usuario(db, negocio_id, usuario_id, ROLES_AJUSTE)
    producto = obtener_producto(db, negocio_id, producto_id)
    if conteo < 0:
        raise OperacionInvalida("El conteo no puede ser negativo")
    motivo = motivo.strip()
    if not motivo:
        raise OperacionInvalida("El motivo es obligatorio")

    lotes = db.scalars(
        select(Lote).where(Lote.producto_id == producto.id)
        .order_by(Lote.caducidad.asc().nulls_last(), Lote.id).with_for_update()
    ).all()
    con_caducidad = [l for l in lotes if not (l.caducidad is None and l.numero_lote is None)]
    en_lotes = sum((max(l.cantidad, Decimal(0)) for l in con_caducidad), Decimal(0))

    ajustes = []
    if conteo >= en_lotes:
        objetivo_sin_caducidad = conteo - en_lotes
    else:
        # Sobran piezas en lotes con caducidad: se quitan de las que caducan antes.
        objetivo_sin_caducidad = Decimal(0)
        sobran = en_lotes - conteo
        for lote in con_caducidad:
            if sobran == 0:
                break
            quitar = min(max(lote.cantidad, Decimal(0)), sobran)
            if quitar > 0:
                ajustes.append(_registrar(db, lote, usuario, TipoAjuste.AJUSTE, -quitar, motivo))
                sobran -= quitar
    sin_caducidad = lote_sin_caducidad(db, producto, crear=objetivo_sin_caducidad > 0)
    if sin_caducidad is not None and sin_caducidad.cantidad != objetivo_sin_caducidad:
        diferencia = objetivo_sin_caducidad - sin_caducidad.cantidad
        ajustes.append(_registrar(db, sin_caducidad, usuario, TipoAjuste.AJUSTE, diferencia, motivo))
    # Lotes con caducidad en negativo (no debería haber) también se corrigen a cero.
    for lote in con_caducidad:
        if lote.cantidad < 0:
            ajustes.append(_registrar(db, lote, usuario, TipoAjuste.AJUSTE, -lote.cantidad, motivo))
    db.flush()
    return ajustes


# --- Consultas de la pantalla de inventario ---------------------------------

def movimientos(db: Session, negocio_id: int, producto_id: int, limite: int = 50) -> list[dict]:
    """Ajustes, mermas, capturas e importación del producto, del más reciente
    al más viejo, con quién lo hizo y de qué lote."""
    obtener_producto(db, negocio_id, producto_id)
    filas = db.execute(
        select(AjusteInventario, Usuario.nombre_completo, Usuario.nombre_usuario, Lote.numero_lote, Lote.caducidad)
        .join(Usuario, Usuario.id == AjusteInventario.usuario_id)
        .join(Lote, Lote.id == AjusteInventario.lote_id)
        .where(AjusteInventario.producto_id == producto_id)
        .order_by(AjusteInventario.id.desc())
        .limit(limite)
    ).all()
    return [
        {
            "id": a.id, "tipo": a.tipo, "cantidad": a.cantidad, "motivo": a.motivo, "created_at": a.created_at,
            "usuario": nombre or usuario, "numero_lote": numero_lote, "caducidad": caducidad,
        }
        for a, nombre, usuario, numero_lote, caducidad in filas
    ]


def por_caducar(db: Session, negocio_id: int, hoy: date, hasta: date) -> list[dict]:
    """Lotes con piezas que ya caducaron o caducan hasta `hasta`, el más próximo primero."""
    filas = db.execute(
        select(Lote, Producto.clave, Producto.nombre)
        .join(Producto, Producto.id == Lote.producto_id)
        .where(Lote.negocio_id == negocio_id, Lote.cantidad > 0, Lote.caducidad.is_not(None), Lote.caducidad <= hasta)
        .order_by(Lote.caducidad, Producto.nombre)
    ).all()
    return [
        {
            "lote_id": l.id, "producto_id": l.producto_id, "clave": clave, "nombre": nombre,
            "numero_lote": l.numero_lote, "caducidad": l.caducidad, "cantidad": l.cantidad,
            "dias": (l.caducidad - hoy).days,
        }
        for l, clave, nombre in filas
    ]
