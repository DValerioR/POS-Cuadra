from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, LargeBinary, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Proveedor(Base):
    """A quién se le compra (unos nueve o diez distribuidores)."""

    __tablename__ = "proveedores"
    __table_args__ = (
        UniqueConstraint("negocio_id", "nombre", name="uq_proveedor_nombre"),
        UniqueConstraint("negocio_id", "rfc", name="uq_proveedor_rfc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    nombre: Mapped[str]
    rfc: Mapped[str | None] = mapped_column(default=None)  # con él se reconoce en el XML
    activo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProveedorEquivalencia(Base):
    """Cómo nombra un proveedor a un producto del catálogo. La primera vez se
    relaciona a mano en la revisión de la entrada; después se reconoce solo.
    `factor`: piezas que trae cada unidad de la factura (ej. caja de 24)."""

    __tablename__ = "proveedor_equivalencias"
    __table_args__ = (UniqueConstraint("proveedor_id", "descripcion", name="uq_equivalencia_descripcion"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    clave_proveedor: Mapped[str | None] = mapped_column(default=None, index=True)  # NoIdentificacion del CFDI
    descripcion: Mapped[str]  # descripción del proveedor, normalizada para comparar
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    factor: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArchivoFactura(Base):
    """El XML, PDF o foto de la factura, tal como se subió. Queda ligado a la
    entrada al confirmarla (los que nunca se confirman se pueden limpiar)."""

    __tablename__ = "archivos_factura"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    nombre: Mapped[str]
    tipo: Mapped[str]  # media type: application/xml, application/pdf, image/png...
    datos: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    entrada_id: Mapped[int | None] = mapped_column(ForeignKey("entradas.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Entrada(Base):
    """Entrada de mercancía de una factura. Crea los lotes (con caducidad si
    se capturó), actualiza el costo de los productos y, si se eligió, su
    precio de venta. Una factura (proveedor + folio) entra una sola vez."""

    __tablename__ = "entradas"
    __table_args__ = (UniqueConstraint("negocio_id", "proveedor_id", "folio", name="uq_entrada_folio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    folio: Mapped[str]
    fecha_factura: Mapped[date | None] = mapped_column(Date, default=None)
    fecha_recepcion: Mapped[date] = mapped_column(Date)
    origen: Mapped[str]  # "manual" | "xml" | "ia"
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    # Lo que dice la factura (para comparar con la suma de renglones).
    total_factura: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    # Suma de renglones (cantidad × costo, sin impuestos).
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notas: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    renglones: Mapped[list["EntradaRenglon"]] = relationship(order_by="EntradaRenglon.id")
    proveedor: Mapped["Proveedor"] = relationship(viewonly=True)


class EntradaRenglon(Base):
    __tablename__ = "entrada_renglones"

    id: Mapped[int] = mapped_column(primary_key=True)
    entrada_id: Mapped[int] = mapped_column(ForeignKey("entradas.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    descripcion_proveedor: Mapped[str | None] = mapped_column(default=None)
    clave_proveedor: Mapped[str | None] = mapped_column(default=None)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 3))  # en unidades de la factura
    factor: Mapped[Decimal] = mapped_column(Numeric(10, 3))  # piezas por unidad
    piezas: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # las que entran al inventario
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 4))  # por unidad de la factura, sin impuestos
    costo_pieza: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"))
    numero_lote: Mapped[str | None] = mapped_column(default=None)
    caducidad: Mapped[date | None] = mapped_column(Date, default=None)
    costo_anterior: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)
    precio_anterior: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    precio_nuevo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)  # si se aplicó el sugerido
