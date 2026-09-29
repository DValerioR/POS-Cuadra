from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Categoria(Base):
    """Categoría de producto (patente, similar, leches de bebé, ...).
    El margen es el % por defecto que se usa al recalcular precio sugerido."""

    __tablename__ = "categorias"
    __table_args__ = (
        UniqueConstraint("negocio_id", "nombre", name="uq_categoria_por_negocio"),
        UniqueConstraint("negocio_id", "pvwin_depto", name="uq_categoria_pvwin_depto"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    nombre: Mapped[str]
    margen_porcentaje: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)
    # Si es False (dulces, perfumería, "VARIOS"), los productos de esta categoría
    # no piden lote ni caducidad y manejan una sola existencia.
    controla_lote: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Número de departamento en PVWin del que salió esta categoría al importar.
    # Permite reimportar sin perder el nombre/margen que se le haya puesto.
    pvwin_depto: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
