import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RolUsuario(str, enum.Enum):
    ADMIN = "admin"
    BODEGA = "bodega"
    MOSTRADOR = "mostrador"


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (UniqueConstraint("negocio_id", "nombre_usuario", name="uq_usuario_por_negocio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    nombre_usuario: Mapped[str]
    nombre_completo: Mapped[str]
    password_hash: Mapped[str]
    rol: Mapped[RolUsuario]
    activo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
