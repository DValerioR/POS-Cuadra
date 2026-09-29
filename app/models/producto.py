from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Producto(Base):
    __tablename__ = "productos"
    __table_args__ = (UniqueConstraint("negocio_id", "clave", name="uq_producto_clave_por_negocio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"), default=None)
    # Código de barras o clave interna (columna "Clave" de PVWin). Es lo que
    # lee el escáner. Única por negocio; puede faltar en productos sin código.
    clave: Mapped[str | None] = mapped_column(index=True, default=None)
    nombre: Mapped[str] = mapped_column(index=True)
    clave_sat: Mapped[str | None] = mapped_column(default=None)
    laboratorio: Mapped[str | None] = mapped_column(default=None)
    requiere_receta: Mapped[bool] = mapped_column(default=False)
    # Puede faltar: el catálogo de PVWin no trae precio de venta.
    precio_venta: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    # Costo sin impuestos, por unidad de compra. Con 4 decimales porque los
    # proveedores manejan costos como 196.668.
    costo: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)
    # Precio máximo al público impreso en caja (medicamentos de patente).
    # Si el margen calculado da un precio mayor, se usa este y el sistema avisa.
    precio_maximo_publico: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    # Cuántas unidades de venta trae una unidad de compra. Ej: se compra una
    # caja de 24 sobres y se vende por sobre -> factor 24. Al dar entrada a
    # 1 caja se suman 24 piezas.
    factor_conversion: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=1, server_default="1")
    iva_porcentaje: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, server_default="0")
    ieps_porcentaje: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, server_default="0")
    # Existencias mínima y máxima, para las sugerencias de pedido.
    minimo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    maximo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    # Marcado por el importador u otro proceso cuando algo necesita ojo humano
    # (sin grupo, costo en cero, clave repetida, ...). El motivo dice qué revisar.
    requiere_revision: Mapped[bool] = mapped_column(default=False, server_default=false())
    motivo_revision: Mapped[str | None] = mapped_column(default=None)
    activo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Búsqueda por clave ignorando ceros a la izquierda: Excel se come el 0 inicial
# de muchos códigos de barras al exportar de PVWin ("013117000894" quedó como
# "13117000894"), así que se compara sin ceros de ambos lados.
Index("ix_productos_clave_sin_ceros", func.ltrim(Producto.clave, "0"))
