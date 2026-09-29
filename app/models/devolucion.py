import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TipoDevolucion(str, enum.Enum):
    CANCELACION = "cancelacion"  # toda la venta
    DEVOLUCION = "devolucion"  # algunas piezas
    CAMBIO = "cambio"  # piezas devueltas a cambio de otros productos (venta_nueva_id)


class Devolucion(Base):
    """Cancelación, devolución o cambio de producto (solo admin, con motivo).

    Se registra en el turno en el que se regresa el dinero, que puede no ser
    el de la venta: si la venta es de un turno ya cerrado, su corte no cambia
    y el reembolso sale del turno actual, que es donde realmente sale.
    """

    __tablename__ = "devoluciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), index=True)
    # Solo en cambios: la venta de lo que se llevó el cliente.
    venta_nueva_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"), default=None)
    turno_id: Mapped[int] = mapped_column(ForeignKey("turnos.id"), index=True)
    caja_id: Mapped[int] = mapped_column(ForeignKey("cajas.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    tipo: Mapped[TipoDevolucion]
    motivo: Mapped[str]
    # Valor de lo devuelto. En devoluciones y cancelaciones se regresa todo en
    # dinero (efectivo + tarjeta = total); en un cambio se usa como saldo en la
    # venta nueva y solo la diferencia a favor del cliente sale en efectivo.
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Dinero que salió de la caja.
    efectivo: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tarjeta: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    renglones: Mapped[list["DevolucionRenglon"]] = relationship(order_by="DevolucionRenglon.id")
    venta: Mapped["Venta"] = relationship(foreign_keys=[venta_id], viewonly=True)  # noqa: F821


class DevolucionRenglon(Base):
    """Piezas devueltas y a qué lote regresaron (siempre al lote del que salieron)."""

    __tablename__ = "devolucion_renglones"

    id: Mapped[int] = mapped_column(primary_key=True)
    devolucion_id: Mapped[int] = mapped_column(ForeignKey("devoluciones.id"), index=True)
    venta_renglon_lote_id: Mapped[int] = mapped_column(ForeignKey("venta_renglon_lotes.id"), index=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"))
    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    importe: Mapped[Decimal] = mapped_column(Numeric(12, 2))
