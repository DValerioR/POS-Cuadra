from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Lote(Base):
    """Existencia de un producto por lote. Cada entrada de mercancía con lote
    nuevo crea un registro nuevo (no se suma al anterior). Al vender se
    descuenta primero el lote con caducidad más próxima (FEFO).

    caducidad = None significa "sin caducidad registrada todavía": inventario
    heredado de PVWin que se va capturando conforme se vende.
    """

    __tablename__ = "lotes"
    __table_args__ = (
        Index("ix_lotes_producto_caducidad", "producto_id", "caducidad"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    numero_lote: Mapped[str | None] = mapped_column(default=None)
    caducidad: Mapped[date | None] = mapped_column(Date, default=None)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    costo_unitario: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
