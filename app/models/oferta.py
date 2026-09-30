from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Oferta(Base):
    """Oferta que se aplica sola al vender, del día `inicio` al día `fin`
    (incluidos). Tipos (ver services/ofertas_venta.py):
    - "descuento" y "precio_especial": `precio` es el precio por pieza con impuestos;
    - "2x1" y "3x2": sin precio (se paga el precio normal de las que no son de regalo);
    - "paquete": `precio` es lo que cuesta llevar juntos este producto y `paquete_con`.
    Un producto está en una sola oferta activa a la vez. Nunca se borra:
    quitarla antes de tiempo la desactiva y deja quién y cuándo."""

    __tablename__ = "ofertas"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    tipo: Mapped[str]
    precio: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    paquete_con_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id"), default=None, index=True)
    inicio: Mapped[date] = mapped_column(Date)
    fin: Mapped[date] = mapped_column(Date)
    activa: Mapped[bool] = mapped_column(default=True)
    motivo: Mapped[str | None] = mapped_column(default=None)
    # "asistente" si vino de una sugerencia, "manual" si la capturó el administrador.
    origen: Mapped[str] = mapped_column(default="manual")
    creada_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    quitada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), default=None)
    quitada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    producto: Mapped["Producto"] = relationship(foreign_keys=[producto_id])  # noqa: F821
    paquete_con: Mapped["Producto | None"] = relationship(foreign_keys=[paquete_con_id])  # noqa: F821
