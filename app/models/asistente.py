from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ConversacionAsistente(Base):
    """Una conversación de un administrador con el asistente de IA."""

    __tablename__ = "conversaciones_asistente"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    titulo: Mapped[str]  # la primera pregunta, recortada
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mensajes: Mapped[list["MensajeAsistente"]] = relationship(order_by="MensajeAsistente.id", cascade="all, delete-orphan")


class MensajeAsistente(Base):
    """Cada mensaje tal como se mandó o se recibió de la API (texto, llamadas
    a consultas y sus resultados). Se guardan exactos y solo se agregan al
    final: al continuar la conversación se reenvían sin cambios."""

    __tablename__ = "mensajes_asistente"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversacion_id: Mapped[int] = mapped_column(ForeignKey("conversaciones_asistente.id", ondelete="CASCADE"), index=True)
    rol: Mapped[str]  # "user" | "assistant"
    contenido: Mapped[list | str] = mapped_column(JSONB)
    tokens_entrada: Mapped[int | None] = mapped_column(default=None)
    tokens_salida: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
