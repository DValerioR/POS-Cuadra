import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TipoUso(str, enum.Enum):
    IA = "ia"
    FACTURA = "factura"


class UsoServicio(Base):
    """Un uso de un servicio que se paga por consumo: una acción con la API de
    Claude o una factura real timbrada. Se cuentan por mes contra los topes
    del plan (ver services/usos.py). Solo se guardan los que salieron bien."""

    __tablename__ = "usos_servicio"
    __table_args__ = (Index("ix_usos_servicio_negocio_tipo_fecha", "negocio_id", "tipo", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"))
    tipo: Mapped[TipoUso]
    # Qué lo gastó: "asistente", "lectura_factura", "foto_producto", "ofertas",
    # "sugerencias_pedido", "bot_whatsapp", "foto_whatsapp" o "factura".
    origen: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
