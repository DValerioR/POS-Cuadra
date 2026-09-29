import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EstadoVenta(str, enum.Enum):
    COMPLETADA = "completada"
    CANCELADA = "cancelada"


class MetodoPago(str, enum.Enum):
    EFECTIVO = "efectivo"
    TARJETA = "tarjeta"
    TRANSFERENCIA = "transferencia"  # preparada, desactivada por ahora


class Venta(Base):
    """Una venta cobrada. Nunca se borra: cancelarla cambia su estado.

    Los importes incluyen impuestos (así se vende al público); subtotal, iva
    e ieps son el desglose.
    """

    __tablename__ = "ventas"
    __table_args__ = (UniqueConstraint("negocio_id", "folio", name="uq_venta_folio_por_negocio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    folio: Mapped[int]  # consecutivo por negocio, el que va en el ticket
    turno_id: Mapped[int] = mapped_column(ForeignKey("turnos.id"), index=True)
    caja_id: Mapped[int] = mapped_column(ForeignKey("cajas.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    estado: Mapped[EstadoVenta] = mapped_column(default=EstadoVenta.COMPLETADA)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    ieps: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    iva: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    renglones: Mapped[list["VentaRenglon"]] = relationship(back_populates="venta", order_by="VentaRenglon.id")
    pagos: Mapped[list["Pago"]] = relationship(back_populates="venta", order_by="Pago.id")


class VentaRenglon(Base):
    """Un producto vendido. Precio e impuestos se copian del producto al
    vender, para que cambiar el precio después no altere ventas pasadas."""

    __tablename__ = "venta_renglones"

    id: Mapped[int] = mapped_column(primary_key=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    nombre: Mapped[str]  # como se llamaba al vender (va en el ticket)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # con impuestos
    importe: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # cantidad × precio, con impuestos
    iva_porcentaje: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    ieps_porcentaje: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    ieps: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    iva: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    venta: Mapped[Venta] = relationship(back_populates="renglones")
    lotes: Mapped[list["VentaRenglonLote"]] = relationship(order_by="VentaRenglonLote.id")


class VentaRenglonLote(Base):
    """De qué lote salió cada pieza vendida (rastreo de retiros sanitarios y
    devolución al lote original)."""

    __tablename__ = "venta_renglon_lotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    renglon_id: Mapped[int] = mapped_column(ForeignKey("venta_renglones.id"), index=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), index=True)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    lote: Mapped["Lote"] = relationship()  # noqa: F821  (para el ticket: "entregar lote A")


class Pago(Base):
    """Cómo se pagó. `monto` es lo que se aplicó a la venta; en efectivo,
    `recibido` es lo que entregó el cliente y `cambio` lo que se le regresó.
    La suma de `monto` de una venta es su total."""

    __tablename__ = "pagos"

    id: Mapped[int] = mapped_column(primary_key=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), index=True)
    metodo: Mapped[MetodoPago]
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    recibido: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    cambio: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)

    venta: Mapped[Venta] = relationship(back_populates="pagos")
