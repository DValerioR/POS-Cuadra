from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Negocio(Base):
    """Un negocio cliente del sistema. Todas las demás tablas cuelgan de aquí
    mediante negocio_id, para poder vender el sistema a varios negocios."""

    __tablename__ = "negocios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(unique=True)
    logo_url: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
