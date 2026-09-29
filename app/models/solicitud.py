import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.devolucion import TipoDevolucion


class EstadoSolicitud(str, enum.Enum):
    PENDIENTE = "pendiente"
    AUTORIZADA = "autorizada"
    RECHAZADA = "rechazada"


class SolicitudDevolucion(Base):
    """Devolución o cancelación que pide el cajero y autoriza un administrador
    desde el centro de notificaciones, en cualquier computadora. Así el
    administrador no tiene que ir a la caja y la fila sigue avanzando.

    Al autorizarse se registra la devolución (`devolucion_id`) en el turno de
    la caja que la pidió, que es de donde sale el dinero; al cajero le aparece
    cuánto entregar. `vista` = el cajero ya vio la respuesta.
    """

    __tablename__ = "solicitudes_devolucion"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), index=True)
    caja_id: Mapped[int] = mapped_column(ForeignKey("cajas.id"), index=True)
    solicitada_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    tipo: Mapped[TipoDevolucion]  # solo devolución o cancelación
    motivo: Mapped[str]
    # Devolución: [{renglon_id, cantidad, lote_id}]; cancelación: [].
    piezas: Mapped[list[dict]] = mapped_column(JSONB)
    # Lo que se regresaría (al pedirla) o lo que se regresó (al autorizarla).
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    efectivo: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tarjeta: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    estado: Mapped[EstadoSolicitud] = mapped_column(default=EstadoSolicitud.PENDIENTE, index=True)
    resuelta_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), default=None)
    resuelta_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    respuesta: Mapped[str | None] = mapped_column(default=None)  # por qué se rechazó
    devolucion_id: Mapped[int | None] = mapped_column(ForeignKey("devoluciones.id"), default=None)
    vista: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    venta: Mapped["Venta"] = relationship(viewonly=True)  # noqa: F821
    caja: Mapped["Caja"] = relationship(viewonly=True)  # noqa: F821
    solicitada_por: Mapped["Usuario"] = relationship(foreign_keys=[solicitada_por_id], viewonly=True)  # noqa: F821
    resuelta_por: Mapped["Usuario | None"] = relationship(foreign_keys=[resuelta_por_id], viewonly=True)  # noqa: F821
