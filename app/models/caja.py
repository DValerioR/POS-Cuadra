import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ModoImpresora(str, enum.Enum):
    NINGUNA = "ninguna"
    RED = "red"  # impresora Ethernet: impresora_direccion = "IP:9100"
    AGENTE = "agente"  # impresora USB con agente: impresora_direccion = "http://IP-PC:9110"


class Caja(Base):
    """Un punto de cobro (computadora de mostrador con su cajón e impresora).
    Cada turno se abre en una caja. Ver impresion/transporte.py."""

    __tablename__ = "cajas"
    __table_args__ = (UniqueConstraint("negocio_id", "nombre", name="uq_caja_por_negocio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    nombre: Mapped[str]
    activa: Mapped[bool] = mapped_column(default=True)
    impresora_modo: Mapped[ModoImpresora] = mapped_column(
        default=ModoImpresora.NINGUNA, server_default=ModoImpresora.NINGUNA.name
    )
    impresora_direccion: Mapped[str | None] = mapped_column(default=None)
    # Token compartido con el agente (solo modo AGENTE). Nunca se regresa por la API.
    impresora_token: Mapped[str | None] = mapped_column(default=None)
    # 42 = papel de 80 mm con fuente normal (cabe en todas, también en la
    # Bixolon a 180 dpi); 32 = papel de 58 mm.
    impresora_columnas: Mapped[int] = mapped_column(default=42, server_default="42")
    # Terminal Mercado Pago Point de esta caja (su id en Mercado Pago). Sin
    # ella, el pago con tarjeta se registra a mano.
    terminal_mp: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
