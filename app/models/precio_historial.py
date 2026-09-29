from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PrecioHistorial(Base):
    """Cada cambio del precio de venta de un producto: de cuánto a cuánto,
    quién y desde dónde (catálogo, cambio en grupo, importación). Nunca se
    edita ni se borra."""

    __tablename__ = "precios_historial"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), default=None)  # None = un script
    precio_anterior: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    precio_nuevo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    origen: Mapped[str]  # "Catálogo", "Cambio en grupo", "Lista de precios de PVWin"...
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
