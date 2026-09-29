"""Reglas de turnos y corte de caja.

Lo esperado en caja se calcula en `totales_del_turno`: fondo + lo cobrado en
ventas del turno − lo reembolsado en el turno (cancelaciones y devoluciones).
Una venta cancelada en su mismo turno se compensa sola; si es de un turno ya
cerrado, el dinero sale del turno en que se regresó.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Caja, Devolucion, MetodoPago, Pago, RolUsuario, TipoTurno, Turno, Usuario, Venta
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso

# Quien cobra abre y cierra turno; bodega no cobra.
ROLES_CAJA = {RolUsuario.ADMIN, RolUsuario.MOSTRADOR}


@dataclass
class TotalesTurno:
    fondo_inicial: Decimal
    ventas_efectivo: Decimal
    ventas_tarjeta: Decimal
    reembolsos_efectivo: Decimal = Decimal(0)
    reembolsos_tarjeta: Decimal = Decimal(0)

    @property
    def efectivo_esperado(self) -> Decimal:
        return self.fondo_inicial + self.ventas_efectivo - self.reembolsos_efectivo

    @property
    def tarjeta_esperado(self) -> Decimal:
        return self.ventas_tarjeta - self.reembolsos_tarjeta


def _validar_rol(usuario: Usuario) -> None:
    if usuario.rol not in ROLES_CAJA:
        raise SinPermiso(f"El rol {usuario.rol.value} no maneja caja")


def obtener_caja(db: Session, negocio_id: int, caja_id: int) -> Caja:
    caja = db.get(Caja, caja_id)
    if caja is None or caja.negocio_id != negocio_id:
        raise NoEncontrado("Caja no encontrada")
    return caja


def obtener_turno(db: Session, negocio_id: int, turno_id: int) -> Turno:
    turno = db.get(Turno, turno_id)
    if turno is None or turno.negocio_id != negocio_id:
        raise NoEncontrado("Turno no encontrado")
    return turno


def turno_abierto(db: Session, caja_id: int) -> Turno | None:
    return db.scalar(select(Turno).where(Turno.caja_id == caja_id, Turno.cerrado_en.is_(None)))


def totales_del_turno(db: Session, turno: Turno) -> TotalesTurno:
    cobrado = dict(db.execute(
        select(Pago.metodo, func.sum(Pago.monto))
        .join(Venta, Venta.id == Pago.venta_id)
        .where(Venta.turno_id == turno.id)
        .group_by(Pago.metodo)
    ).all())
    reembolsado_efectivo, reembolsado_tarjeta = db.execute(
        select(func.coalesce(func.sum(Devolucion.efectivo), 0), func.coalesce(func.sum(Devolucion.tarjeta), 0))
        .where(Devolucion.turno_id == turno.id)
    ).one()
    return TotalesTurno(
        fondo_inicial=turno.fondo_inicial,
        ventas_efectivo=cobrado.get(MetodoPago.EFECTIVO, Decimal(0)),
        ventas_tarjeta=cobrado.get(MetodoPago.TARJETA, Decimal(0)),
        reembolsos_efectivo=reembolsado_efectivo,
        reembolsos_tarjeta=reembolsado_tarjeta,
    )


def abrir_turno(db: Session, usuario: Usuario, caja_id: int, tipo: TipoTurno, fondo_inicial: Decimal) -> Turno:
    """No hace commit."""
    _validar_rol(usuario)
    caja = obtener_caja(db, usuario.negocio_id, caja_id)
    if not caja.activa:
        raise OperacionInvalida("La caja está desactivada")
    if fondo_inicial < 0:
        raise OperacionInvalida("El fondo no puede ser negativo")
    if turno_abierto(db, caja.id) is not None:
        raise OperacionInvalida(f"La caja '{caja.nombre}' ya tiene un turno abierto; ciérralo primero")

    turno = Turno(
        negocio_id=usuario.negocio_id,
        caja_id=caja.id,
        tipo=tipo,
        fondo_inicial=fondo_inicial,
        abierto_por_id=usuario.id,
    )
    db.add(turno)
    try:
        db.flush()
    except IntegrityError:
        # Otra computadora abrió turno en esta caja al mismo tiempo.
        raise OperacionInvalida(f"La caja '{caja.nombre}' ya tiene un turno abierto; ciérralo primero")
    return turno


def cerrar_turno(
    db: Session,
    usuario: Usuario,
    turno_id: int,
    efectivo_contado: Decimal,
    tarjeta_contado: Decimal,
    notas: str | None = None,
) -> Turno:
    """Congela lo esperado, guarda lo contado y la diferencia. No hace commit."""
    _validar_rol(usuario)
    turno = db.scalar(
        select(Turno).where(Turno.id == turno_id, Turno.negocio_id == usuario.negocio_id).with_for_update()
    )
    if turno is None:
        raise NoEncontrado("Turno no encontrado")
    if turno.cerrado_en is not None:
        raise OperacionInvalida("El turno ya está cerrado")
    if efectivo_contado < 0 or tarjeta_contado < 0:
        raise OperacionInvalida("Lo contado no puede ser negativo")

    totales = totales_del_turno(db, turno)
    turno.cerrado_por_id = usuario.id
    turno.cerrado_en = datetime.now(timezone.utc)
    turno.efectivo_esperado = totales.efectivo_esperado
    turno.tarjeta_esperado = totales.tarjeta_esperado
    turno.efectivo_contado = efectivo_contado
    turno.tarjeta_contado = tarjeta_contado
    turno.diferencia_efectivo = efectivo_contado - totales.efectivo_esperado
    turno.diferencia_tarjeta = tarjeta_contado - totales.tarjeta_esperado
    turno.notas_cierre = (notas or "").strip() or None
    return turno
