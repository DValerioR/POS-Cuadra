"""Solicitudes de devolución y cancelación.

El cajero no deja la fila esperando: registra lo que el cliente regresa (o
que cancela toda la venta), con motivo, y sigue cobrando. La solicitud llega
al centro de notificaciones, que solo ven los administradores, y cualquiera
de ellos la autoriza o la rechaza desde su computadora. Al autorizarla se
hace la devolución en el turno de la caja que la pidió (de ahí sale el
dinero) y al cajero le aparece cuánto entregar.

Una sola solicitud pendiente por venta. Mientras una caja tenga solicitudes
pendientes no se puede hacer su corte, porque al autorizarlas el dinero sale
de su turno.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EstadoSolicitud, RolUsuario, SolicitudDevolucion, TipoDevolucion, Usuario
from app.services import devoluciones, turnos
from app.services.devoluciones import PiezaDevuelta
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso


def _solo_admin(usuario: Usuario) -> None:
    if usuario.rol != RolUsuario.ADMIN:
        raise SinPermiso("Solo un administrador puede autorizar devoluciones y cancelaciones")


def pendientes_de_caja(db: Session, caja_id: int) -> int:
    return db.scalar(select(func.count()).select_from(SolicitudDevolucion).where(
        SolicitudDevolucion.caja_id == caja_id, SolicitudDevolucion.estado == EstadoSolicitud.PENDIENTE,
    ))


def crear(
    db: Session, usuario: Usuario, venta_id: int, caja_id: int, tipo: TipoDevolucion, motivo: str,
    piezas: list[PiezaDevuelta],
) -> SolicitudDevolucion:
    """El cajero pide una devolución o cancelación. Se valida todo como si se
    hiciera (piezas, turno abierto) pero no se mueve nada. No hace commit."""
    turnos._validar_rol(usuario)
    if tipo == TipoDevolucion.CAMBIO:
        raise OperacionInvalida("Los cambios de producto los hace un administrador en la caja")
    venta, turno, motivo = devoluciones.validar_operacion(db, usuario.negocio_id, venta_id, caja_id, motivo)
    ya_pedida = db.scalar(select(SolicitudDevolucion.id).where(
        SolicitudDevolucion.venta_id == venta.id, SolicitudDevolucion.estado == EstadoSolicitud.PENDIENTE,
    ))
    if ya_pedida:
        raise OperacionInvalida(
            f"Ya hay una solicitud pendiente para el folio {venta.folio}; espera a que el administrador la responda"
        )
    if tipo == TipoDevolucion.CANCELACION:
        piezas = []
    total, efectivo, tarjeta = devoluciones.calcular_reembolso(db, venta, tipo, piezas)
    solicitud = SolicitudDevolucion(
        negocio_id=usuario.negocio_id, venta_id=venta.id, caja_id=turno.caja_id, solicitada_por_id=usuario.id,
        tipo=tipo, motivo=motivo,
        piezas=[{"renglon_id": p.renglon_id, "cantidad": str(p.cantidad), "lote_id": p.lote_id} for p in piezas],
        total=total, efectivo=efectivo, tarjeta=tarjeta,
    )
    db.add(solicitud)
    db.flush()
    return solicitud


def _obtener(db: Session, usuario: Usuario, solicitud_id: int, bloquear: bool = False) -> SolicitudDevolucion:
    stmt = select(SolicitudDevolucion).where(
        SolicitudDevolucion.id == solicitud_id, SolicitudDevolucion.negocio_id == usuario.negocio_id,
    )
    solicitud = db.scalar(stmt.with_for_update() if bloquear else stmt)
    if solicitud is None:
        raise NoEncontrado("Solicitud no encontrada")
    return solicitud


def _pendiente(db: Session, usuario: Usuario, solicitud_id: int) -> SolicitudDevolucion:
    solicitud = _obtener(db, usuario, solicitud_id, bloquear=True)
    if solicitud.estado != EstadoSolicitud.PENDIENTE:
        quien = solicitud.resuelta_por.nombre_completo if solicitud.resuelta_por else "otro administrador"
        verbo = "autorizó" if solicitud.estado == EstadoSolicitud.AUTORIZADA else "rechazó"
        raise OperacionInvalida(f"Esta solicitud ya la {verbo} {quien}")
    return solicitud


def autorizar(db: Session, usuario: Usuario, solicitud_id: int) -> SolicitudDevolucion:
    """Hace la devolución o cancelación en la caja que la pidió. Si ya no se
    puede (la caja cerró su turno, alguien ya devolvió esas piezas), avisa y
    la solicitud sigue pendiente para rechazarla. No hace commit."""
    _solo_admin(usuario)
    solicitud = _pendiente(db, usuario, solicitud_id)
    if solicitud.tipo == TipoDevolucion.CANCELACION:
        devolucion = devoluciones.cancelar_venta(db, usuario, solicitud.venta_id, solicitud.caja_id, solicitud.motivo)
    else:
        piezas = [
            PiezaDevuelta(renglon_id=p["renglon_id"], cantidad=Decimal(p["cantidad"]), lote_id=p["lote_id"])
            for p in solicitud.piezas
        ]
        devolucion = devoluciones.devolver_piezas(
            db, usuario, solicitud.venta_id, solicitud.caja_id, solicitud.motivo, piezas,
        )
    solicitud.estado = EstadoSolicitud.AUTORIZADA
    solicitud.resuelta_por_id = usuario.id
    solicitud.resuelta_en = datetime.now(timezone.utc)
    solicitud.devolucion_id = devolucion.id
    solicitud.total, solicitud.efectivo, solicitud.tarjeta = devolucion.total, devolucion.efectivo, devolucion.tarjeta
    db.flush()
    return solicitud


def rechazar(db: Session, usuario: Usuario, solicitud_id: int, respuesta: str | None) -> SolicitudDevolucion:
    """No hace commit."""
    _solo_admin(usuario)
    solicitud = _pendiente(db, usuario, solicitud_id)
    solicitud.estado = EstadoSolicitud.RECHAZADA
    solicitud.resuelta_por_id = usuario.id
    solicitud.resuelta_en = datetime.now(timezone.utc)
    solicitud.respuesta = (respuesta or "").strip() or None
    db.flush()
    return solicitud


def listar(
    db: Session, usuario: Usuario, estado: EstadoSolicitud | None = None, desde: datetime | None = None,
    limite: int = 50,
) -> list[SolicitudDevolucion]:
    """Centro de notificaciones (solo admin): primero las pendientes, las más viejas arriba."""
    _solo_admin(usuario)
    stmt = select(SolicitudDevolucion).where(SolicitudDevolucion.negocio_id == usuario.negocio_id)
    if estado is not None:
        stmt = stmt.where(SolicitudDevolucion.estado == estado)
    if desde is not None:
        stmt = stmt.where(SolicitudDevolucion.created_at >= desde)
    orden = SolicitudDevolucion.id.asc() if estado == EstadoSolicitud.PENDIENTE else SolicitudDevolucion.id.desc()
    return db.scalars(stmt.order_by(orden).limit(limite)).all()


def contar_pendientes(db: Session, usuario: Usuario) -> int:
    _solo_admin(usuario)
    return db.scalar(select(func.count()).select_from(SolicitudDevolucion).where(
        SolicitudDevolucion.negocio_id == usuario.negocio_id, SolicitudDevolucion.estado == EstadoSolicitud.PENDIENTE,
    ))


def de_caja(db: Session, usuario: Usuario, caja_id: int) -> list[SolicitudDevolucion]:
    """Lo que el cajero de esta caja debe ver: sus pendientes y las respuestas que no ha visto."""
    turnos._validar_rol(usuario)
    turnos.obtener_caja(db, usuario.negocio_id, caja_id)
    return db.scalars(select(SolicitudDevolucion).where(
        SolicitudDevolucion.caja_id == caja_id,
        (SolicitudDevolucion.estado == EstadoSolicitud.PENDIENTE) | SolicitudDevolucion.vista.is_(False),
    ).order_by(SolicitudDevolucion.id)).all()


def marcar_vista(db: Session, usuario: Usuario, solicitud_id: int) -> SolicitudDevolucion:
    """El cajero ya vio la respuesta (y entregó el dinero, si se autorizó). No hace commit."""
    turnos._validar_rol(usuario)
    solicitud = _obtener(db, usuario, solicitud_id)
    if solicitud.estado == EstadoSolicitud.PENDIENTE:
        raise OperacionInvalida("La solicitud todavía no tiene respuesta")
    solicitud.vista = True
    db.flush()
    return solicitud
