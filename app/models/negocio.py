from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, LargeBinary, Numeric, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Negocio(Base):
    """Un negocio cliente del sistema. Todas las demás tablas cuelgan de aquí
    mediante negocio_id, para poder vender el sistema a varios negocios."""

    __tablename__ = "negocios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(unique=True)
    # Imagen de la pantalla de inicio: la sube un administrador desde el núcleo
    # y se guarda en la base (así entra en los respaldos). logo_url apunta a
    # /negocio/logo?v=... y cambia con cada imagen nueva.
    logo_url: Mapped[str | None] = mapped_column(default=None)
    logo_imagen: Mapped[bytes | None] = mapped_column(LargeBinary, default=None, deferred=True)
    logo_tipo: Mapped[str | None] = mapped_column(default=None)
    # Logo de la farmacia (aparte de la imagen de inicio): va en la barra de
    # todas las pantallas, en el inicio de sesión, en la tableta y en el ticket.
    marca_url: Mapped[str | None] = mapped_column(default=None)
    marca_imagen: Mapped[bytes | None] = mapped_column(LargeBinary, default=None, deferred=True)
    marca_tipo: Mapped[str | None] = mapped_column(default=None)
    # Paso al que se redondean los precios de venta (1.00 = pesos enteros,
    # 0.50 = medios pesos). None = no redondear. Ver services/precios.py.
    redondeo_precio_venta: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    # Datos fiscales (los de sus facturas). Se usarán al facturar desde el POS.
    razon_social: Mapped[str | None] = mapped_column(default=None)
    rfc: Mapped[str | None] = mapped_column(default=None)
    regimen_fiscal: Mapped[str | None] = mapped_column(default=None)  # clave del SAT, ej. "612"
    codigo_postal: Mapped[str | None] = mapped_column(default=None)  # lugar de expedición
    # Serie de las facturas que salen del POS (distinta de la de PVWin para no chocar).
    factura_serie: Mapped[str] = mapped_column(default="C", server_default="C")
    # Líneas del ticket arriba (dirección, teléfono, RFC) y abajo (agradecimiento).
    ticket_encabezado: Mapped[str | None] = mapped_column(default=None)
    ticket_pie: Mapped[str | None] = mapped_column(default=None)
    # Imprimir el logo de la farmacia centrado arriba del ticket.
    ticket_logo: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
