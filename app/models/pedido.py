import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EstadoPedido(str, enum.Enum):
    BORRADOR = "borrador"  # se está armando; se puede cambiar
    ENVIADO = "enviado"  # ya se le mandó al proveedor; se espera la mercancía
    RECIBIDO = "recibido"  # cerrado: llegó (completo o no) y se comparó
    CANCELADO = "cancelado"


class Pedido(Base):
    """Pedido a un proveedor. Se arma con sus faltantes y, al llegar la
    mercancía, se liga a una o más entradas para comparar lo pedido contra
    lo que llegó (cantidades y costos)."""

    __tablename__ = "pedidos"
    __table_args__ = (UniqueConstraint("negocio_id", "folio", name="uq_pedido_folio_por_negocio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    folio: Mapped[int]  # consecutivo por negocio
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    estado: Mapped[EstadoPedido] = mapped_column(default=EstadoPedido.BORRADOR)
    notas: Mapped[str | None] = mapped_column(default=None)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cerrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    renglones: Mapped[list["PedidoRenglon"]] = relationship(
        order_by="PedidoRenglon.id", cascade="all, delete-orphan"
    )
    proveedor: Mapped["Proveedor"] = relationship(viewonly=True)  # noqa: F821


class PedidoRenglon(Base):
    """Un producto pedido, en piezas. `costo_esperado` es el último costo por
    pieza con ese proveedor al armar el pedido, para detectar cambios de precio."""

    __tablename__ = "pedido_renglones"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    costo_esperado: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)


class PedidoEntrada(Base):
    """Entrada de mercancía que surte (parte de) un pedido. Una entrada
    surte a lo más un pedido; un pedido puede llegar en varias entradas."""

    __tablename__ = "pedido_entradas"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    entrada_id: Mapped[int] = mapped_column(ForeignKey("entradas.id"), unique=True)
