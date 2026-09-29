from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Negocio(Base):
    """Un negocio cliente del sistema. Todas las demás tablas cuelgan de aquí
    mediante negocio_id, para poder vender el sistema a varios negocios."""

    __tablename__ = "negocios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(unique=True)
    logo_url: Mapped[str | None] = mapped_column(default=None)
    # Paso al que se redondean los precios de venta (1.00 = pesos enteros,
    # 0.50 = medios pesos). None = no redondear. Ver services/precios.py.
    redondeo_precio_venta: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    # Líneas del ticket arriba (dirección, teléfono, RFC) y abajo (agradecimiento).
    ticket_encabezado: Mapped[str | None] = mapped_column(default=None)
    ticket_pie: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
