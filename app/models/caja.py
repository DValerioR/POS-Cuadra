from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Caja(Base):
    """Un punto de cobro (computadora de mostrador con su cajón e impresora).
    Cada turno se abre en una caja. Aquí se guardará también cómo se conecta
    su impresora (USB con agente o red)."""

    __tablename__ = "cajas"
    __table_args__ = (UniqueConstraint("negocio_id", "nombre", name="uq_caja_por_negocio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    nombre: Mapped[str]
    activa: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
