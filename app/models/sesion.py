from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Sesion(Base):
    """Sesión iniciada por un usuario. El navegador guarda el token en una
    cookie; aquí solo se guarda su hash (SHA-256), así que una copia de la base
    de datos no sirve para suplantar a nadie.

    Se prefirió sobre JWT porque cerrar sesión o desactivar a un usuario corta
    su acceso de inmediato.
    """

    __tablename__ = "sesiones"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    token_hash: Mapped[str] = mapped_column(unique=True)
    expira: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cerrada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
