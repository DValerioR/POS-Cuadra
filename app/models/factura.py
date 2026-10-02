import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, LargeBinary, Numeric, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClienteFiscal(Base):
    """Datos fiscales de un cliente que pidió factura. Se guardan para que la
    próxima vez baste con escribir su RFC."""

    __tablename__ = "clientes_fiscales"
    __table_args__ = (UniqueConstraint("negocio_id", "rfc", name="uq_cliente_rfc_por_negocio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    rfc: Mapped[str]
    nombre: Mapped[str]  # razón social, tal cual la constancia de situación fiscal
    codigo_postal: Mapped[str]  # domicilio fiscal
    regimen_fiscal: Mapped[str]  # clave del SAT
    uso_cfdi: Mapped[str]  # el último que usó (se propone la próxima vez)
    email: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EstadoFactura(str, enum.Enum):
    VIGENTE = "vigente"
    CANCELADA = "cancelada"


class Factura(Base):
    """CFDI de ingreso timbrado por el PAC para una venta (un ticket se
    factura una sola vez). Solo se guardan las que el PAC timbró."""

    __tablename__ = "facturas"
    __table_args__ = (UniqueConstraint("negocio_id", "serie", "folio", name="uq_factura_folio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), unique=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes_fiscales.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    serie: Mapped[str]
    folio: Mapped[int]
    estado: Mapped[EstadoFactura] = mapped_column(default=EstadoFactura.VIGENTE)
    # Datos del receptor como quedaron en la factura (el cliente puede cambiar después).
    receptor_rfc: Mapped[str]
    receptor_nombre: Mapped[str]
    receptor_codigo_postal: Mapped[str]
    receptor_regimen: Mapped[str]
    uso_cfdi: Mapped[str]
    forma_pago: Mapped[str]  # 01 efectivo, 04 tarjeta de crédito, 28 de débito...
    metodo_pago: Mapped[str] = mapped_column(default="PUE")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    iva: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    ieps: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Lo que regresa el PAC.
    pac: Mapped[str]  # qué PAC la timbró ("simulado" y "facturapi-pruebas" = de prueba, sin validez)
    pac_id: Mapped[str | None] = mapped_column(default=None)  # su identificador en el PAC (para cancelarla)
    uuid: Mapped[str] = mapped_column(unique=True)
    fecha_timbrado: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    xml: Mapped[str] = mapped_column(Text, deferred=True)
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary, default=None, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
