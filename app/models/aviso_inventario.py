import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EstadoAviso(str, enum.Enum):
    PENDIENTE = "pendiente"
    REVISADO = "revisado"


class AvisoInventario(Base):
    """Se vendió más de lo que el sistema tenía registrado. La venta no se
    detiene (físicamente sí había piezas): lo que faltaba se descuenta del lote
    "sin caducidad" del producto, que queda en negativo, y los administradores
    lo ven en el centro de notificaciones para contar y corregir la existencia.

    Al registrar el conteo se ajusta la existencia y se cierran todos los
    avisos pendientes de ese producto.
    """

    __tablename__ = "avisos_inventario"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"))
    caja_id: Mapped[int] = mapped_column(ForeignKey("cajas.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))  # quien vendió
    vendidas: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # piezas del renglón
    faltantes: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # las que el sistema no tenía
    estado: Mapped[EstadoAviso] = mapped_column(default=EstadoAviso.PENDIENTE, index=True)
    revisado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), default=None)
    revisado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    conteo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)  # lo que se contó en anaquel
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    producto: Mapped["Producto"] = relationship(viewonly=True)  # noqa: F821
    venta: Mapped["Venta"] = relationship(viewonly=True)  # noqa: F821
    caja: Mapped["Caja"] = relationship(viewonly=True)  # noqa: F821
    vendedor: Mapped["Usuario"] = relationship(foreign_keys=[usuario_id], viewonly=True)  # noqa: F821
    revisado_por: Mapped["Usuario | None"] = relationship(foreign_keys=[revisado_por_id], viewonly=True)  # noqa: F821
