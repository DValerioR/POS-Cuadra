import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EstadoEncargo(str, enum.Enum):
    POR_PEDIR = "por_pedir"  # un cliente lo pidió; falta encargarlo al proveedor
    PEDIDO = "pedido"  # ya se encargó al proveedor
    LLEGO = "llego"  # ya está en la farmacia; falta que el cliente pase
    NO_DISPONIBLE = "no_disponible"  # no se pudo encargar (ej. el proveedor no tiene existencias)
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


class Encargo(Base):
    """Un producto que un cliente pidió en específico (normalmente uno marcado
    "Encargo", que no se tiene en existencia). El personal lo encarga al
    proveedor y le avisa al cliente: cuando se pidió y cuando llegó.

    Puede ser de un producto del catálogo o, si no existe, solo la descripción.
    Llega por el mostrador o, más adelante, por el bot de WhatsApp (`canal`).
    Ver services/encargos.py.
    """

    __tablename__ = "encargos"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id"), default=None, index=True)
    descripcion: Mapped[str]  # el nombre del producto o lo que pidió el cliente
    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1)
    cliente: Mapped[str]
    telefono: Mapped[str | None] = mapped_column(default=None)
    canal: Mapped[str] = mapped_column(default="mostrador", server_default="mostrador")  # mostrador | whatsapp
    notas: Mapped[str | None] = mapped_column(default=None)
    estado: Mapped[EstadoEncargo] = mapped_column(default=EstadoEncargo.POR_PEDIR, index=True)
    # Pedido al proveedor que lo incluye (si se pidió desde Pedidos).
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"), default=None)
    # Cuándo se le avisó al cliente del último cambio (que ya se pidió o que ya llegó).
    avisado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    avisado_estado: Mapped[EstadoEncargo | None] = mapped_column(default=None)
    # Cómo se avisó ("whatsapp" = el bot mandó la plantilla; "personal" = lo
    # marcó alguien), el texto enviado y, si falló el envío, por qué.
    avisado_por: Mapped[str | None] = mapped_column(default=None)
    aviso_texto: Mapped[str | None] = mapped_column(default=None)
    aviso_error: Mapped[str | None] = mapped_column(default=None)
    # Por qué no se pudo encargar: la clave del motivo (ver services/encargos.py,
    # MOTIVOS) y el detalle que escribió el personal (solo para la farmacia).
    motivo_no_disponible: Mapped[str | None] = mapped_column(default=None)
    motivo_detalle: Mapped[str | None] = mapped_column(default=None)
    creado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), default=None)  # None = el bot
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
