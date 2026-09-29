"""Avisos de ventas sin existencia registrada (ver models/aviso_inventario.py).

Solo los ven y resuelven los administradores, en el centro de notificaciones.
Resolver = contar cuántas piezas hay en anaquel: la existencia se ajusta a
ese número y se cierran todos los avisos pendientes del producto. También se
pueden marcar como revisados sin contar (por ejemplo, si ya se ajustó).
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AvisoInventario, EstadoAviso, RolUsuario, Usuario
from app.services import inventario
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso


def _solo_admin(usuario: Usuario) -> None:
    if usuario.rol != RolUsuario.ADMIN:
        raise SinPermiso("Solo un administrador revisa los avisos de inventario")


def listar(
    db: Session, usuario: Usuario, estado: EstadoAviso | None = None, desde: datetime | None = None, limite: int = 50,
) -> list[AvisoInventario]:
    _solo_admin(usuario)
    stmt = select(AvisoInventario).where(AvisoInventario.negocio_id == usuario.negocio_id)
    if estado is not None:
        stmt = stmt.where(AvisoInventario.estado == estado)
    if desde is not None:
        stmt = stmt.where(AvisoInventario.created_at >= desde)
    orden = AvisoInventario.id.asc() if estado == EstadoAviso.PENDIENTE else AvisoInventario.id.desc()
    return db.scalars(stmt.order_by(orden).limit(limite)).all()


def contar_pendientes(db: Session, usuario: Usuario) -> int:
    _solo_admin(usuario)
    return db.scalar(select(func.count()).select_from(AvisoInventario).where(
        AvisoInventario.negocio_id == usuario.negocio_id, AvisoInventario.estado == EstadoAviso.PENDIENTE,
    ))


def _pendiente(db: Session, usuario: Usuario, aviso_id: int) -> AvisoInventario:
    aviso = db.scalar(select(AvisoInventario).where(
        AvisoInventario.id == aviso_id, AvisoInventario.negocio_id == usuario.negocio_id,
    ).with_for_update())
    if aviso is None:
        raise NoEncontrado("Aviso no encontrado")
    if aviso.estado != EstadoAviso.PENDIENTE:
        quien = aviso.revisado_por.nombre_completo if aviso.revisado_por else "otro administrador"
        raise OperacionInvalida(f"Este aviso ya lo revisó {quien}")
    return aviso


def _cerrar_del_producto(db: Session, usuario: Usuario, producto_id: int, conteo: Decimal | None) -> list[AvisoInventario]:
    avisos = db.scalars(select(AvisoInventario).where(
        AvisoInventario.negocio_id == usuario.negocio_id, AvisoInventario.producto_id == producto_id,
        AvisoInventario.estado == EstadoAviso.PENDIENTE,
    ).with_for_update()).all()
    ahora = datetime.now(timezone.utc)
    for a in avisos:
        a.estado, a.revisado_por_id, a.revisado_en, a.conteo = EstadoAviso.REVISADO, usuario.id, ahora, conteo
    db.flush()
    return avisos


def resolver_con_conteo(db: Session, usuario: Usuario, aviso_id: int, conteo: Decimal) -> list[AvisoInventario]:
    """Ajusta la existencia al conteo físico y cierra los avisos del producto. No hace commit."""
    _solo_admin(usuario)
    aviso = _pendiente(db, usuario, aviso_id)
    inventario.fijar_existencia(
        db, usuario.negocio_id, usuario.id, aviso.producto_id, conteo,
        f"Conteo físico por venta sin existencia registrada (folio {aviso.venta.folio})",
    )
    return _cerrar_del_producto(db, usuario, aviso.producto_id, conteo)


def marcar_revisado(db: Session, usuario: Usuario, aviso_id: int) -> list[AvisoInventario]:
    """Cierra los avisos del producto sin tocar la existencia. No hace commit."""
    _solo_admin(usuario)
    aviso = _pendiente(db, usuario, aviso_id)
    return _cerrar_del_producto(db, usuario, aviso.producto_id, None)
