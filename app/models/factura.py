import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, LargeBinary, Numeric, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
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
    # Se pidió cancelar y el cliente debe aceptarla (el SAT le da 72 horas).
    CANCELACION_PENDIENTE = "cancelacion_pendiente"
    CANCELADA = "cancelada"


class TipoFactura(str, enum.Enum):
    TICKET = "ticket"  # a un cliente, por un ticket
    GLOBAL = "global"  # al público en general, por los tickets no facturados de un periodo


class Factura(Base):
    """CFDI de ingreso timbrado por el PAC: de un ticket a un cliente, o la
    factura global de un periodo al público en general. Un ticket se factura
    una sola vez (salvo que esa factura se cancele). Solo se guardan las que
    el PAC timbró."""

    __tablename__ = "facturas"
    __table_args__ = (
        UniqueConstraint("negocio_id", "serie", "folio", name="uq_factura_folio"),
        Index("uq_factura_venta_vigente", "venta_id", unique=True, postgresql_where=text("estado <> 'CANCELADA'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    tipo: Mapped[str] = mapped_column(default=TipoFactura.TICKET.value, server_default=TipoFactura.TICKET.value)
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"), default=None)  # None en la global
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes_fiscales.id"), index=True, default=None)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    serie: Mapped[str]
    folio: Mapped[int]
    estado: Mapped[EstadoFactura] = mapped_column(default=EstadoFactura.VIGENTE)
    # Factura global: el periodo (InformacionGlobal del CFDI).
    global_periodicidad: Mapped[str | None] = mapped_column(default=None)  # 01 diaria ... 05 bimestral
    global_meses: Mapped[str | None] = mapped_column(default=None)  # 01-12, o 13-18 si es bimestral
    global_anio: Mapped[int | None] = mapped_column(default=None)
    global_desde: Mapped[date | None] = mapped_column(Date, default=None)
    global_hasta: Mapped[date | None] = mapped_column(Date, default=None)
    # Cancelación ante el SAT.
    cancelacion_motivo: Mapped[str | None] = mapped_column(default=None)  # 02 o 03
    cancelacion_solicitada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cancelada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cancelacion_mensaje: Mapped[str | None] = mapped_column(default=None)  # ej. "el cliente la rechazó"
    cancelado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), default=None)
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


class IntentoFactura(Base):
    """Una factura que se mandó a timbrar y todavía no se confirma. Se guarda
    (con commit) ANTES de llamar al PAC: si se corta la conexión a la mitad,
    el PAC pudo haberla timbrado, y volver a timbrar sin revisar haría un
    CFDI duplicado ante el SAT. Mientras exista, la venta no se factura de
    nuevo: "Reintentar" primero busca la factura en el PAC y solo si no está
    la timbra (con la misma serie y folio). Al quedar guardada la Factura, el
    intento se borra; si el PAC la rechazó, también."""

    __tablename__ = "intentos_factura"
    __table_args__ = (UniqueConstraint("negocio_id", "serie", "folio", name="uq_intento_factura_folio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    tipo: Mapped[str] = mapped_column(default=TipoFactura.TICKET.value, server_default=TipoFactura.TICKET.value)
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"), unique=True, default=None)  # None en la global
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    serie: Mapped[str]
    folio: Mapped[int]
    pac: Mapped[str]  # con qué PAC se mandó (no se recupera con otro)
    pac_id: Mapped[str | None] = mapped_column(default=None)  # si el PAC alcanzó a contestar
    # Lo capturado: rfc, nombre, codigo_postal, regimen, uso_cfdi, email, tarjeta.
    # En la global: periodicidad, meses, anio, desde, hasta y forma_pago.
    datos: Mapped[dict] = mapped_column(JSONB)
    mensaje: Mapped[str | None] = mapped_column(default=None)  # por qué no se pudo confirmar
    intentos: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VentaEnGlobal(Base):
    """Un ticket que va en una factura global (o en una que se está
    timbrando: intento_id). Un ticket solo puede ir en una global; si la
    global se cancela, sus renglones se borran y los tickets quedan libres."""

    __tablename__ = "ventas_en_global"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), unique=True)
    factura_id: Mapped[int | None] = mapped_column(ForeignKey("facturas.id", ondelete="CASCADE"), index=True, default=None)
    intento_id: Mapped[int | None] = mapped_column(ForeignKey("intentos_factura.id", ondelete="CASCADE"), index=True,
                                                   default=None)
