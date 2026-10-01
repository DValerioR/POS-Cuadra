import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EstadoConversacion(str, enum.Enum):
    BOT = "bot"  # contesta el bot
    ESPERA = "espera"  # el cliente necesita a una persona; nadie la ha tomado
    PERSONA = "persona"  # la atiende alguien del personal; el bot no contesta


class ConversacionWhatsApp(Base):
    """Una plática de WhatsApp con un cliente (una por número). La contesta el
    bot hasta que el cliente pide a una persona o el bot no sabe qué
    responder; entonces espera a que alguien del personal la tome desde
    Conversaciones. Ver app/whatsapp/bot.py."""

    __tablename__ = "conversaciones_whatsapp"
    __table_args__ = (UniqueConstraint("negocio_id", "telefono", name="uq_conversacion_whatsapp_telefono"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    telefono: Mapped[str]  # como lo manda WhatsApp: 52XXXXXXXXXX
    nombre: Mapped[str | None] = mapped_column(default=None)  # el nombre de su perfil de WhatsApp
    estado: Mapped[EstadoConversacion] = mapped_column(default=EstadoConversacion.BOT, index=True)
    # Por qué se pasó a una persona (lo que dijo el bot) y cuándo.
    motivo_persona: Mapped[str | None] = mapped_column(default=None)
    persona_desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    atendida_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), default=None)
    # Si el aviso al WhatsApp del personal no se pudo mandar, por qué.
    aviso_error: Mapped[str | None] = mapped_column(default=None)
    # Último mensaje del cliente: WhatsApp solo deja contestarle con texto
    # libre dentro de las 24 horas siguientes.
    ultimo_cliente_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ultimo_mensaje_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    sin_leer: Mapped[int] = mapped_column(default=0, server_default="0")  # mensajes del cliente que el personal no ha visto
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mensajes: Mapped[list["MensajeWhatsApp"]] = relationship(
        back_populates="conversacion", order_by="MensajeWhatsApp.id", cascade="all, delete-orphan")


class MensajeWhatsApp(Base):
    __tablename__ = "mensajes_whatsapp"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversacion_id: Mapped[int] = mapped_column(ForeignKey("conversaciones_whatsapp.id", ondelete="CASCADE"), index=True)
    de: Mapped[str]  # cliente | bot | personal | sistema (notas internas, no se envían)
    texto: Mapped[str | None] = mapped_column(default=None)
    # Foto que mandó el cliente (para que el personal la vea).
    imagen: Mapped[bytes | None] = mapped_column(LargeBinary, default=None, deferred=True)
    imagen_tipo: Mapped[str | None] = mapped_column(default=None)
    # Id del mensaje en WhatsApp: WhatsApp puede reenviar el mismo aviso y así no se contesta dos veces.
    wa_id: Mapped[str | None] = mapped_column(unique=True, default=None)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), default=None)  # quién contestó (personal)
    error: Mapped[str | None] = mapped_column(default=None)  # si no se pudo enviar
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversacion: Mapped[ConversacionWhatsApp] = relationship(back_populates="mensajes")
