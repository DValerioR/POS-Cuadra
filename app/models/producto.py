from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"), default=None)
    codigo_barras: Mapped[str | None] = mapped_column(index=True, default=None)
    nombre: Mapped[str] = mapped_column(index=True)
    requiere_receta: Mapped[bool] = mapped_column(default=False)
    precio_venta: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    costo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    # Precio máximo al público impreso en caja (medicamentos de patente).
    # Si el margen calculado da un precio mayor, se usa este y el sistema avisa.
    precio_maximo_publico: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    activo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
