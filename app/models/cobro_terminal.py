from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CobroTerminal(Base):
    """Un cobro con tarjeta mandado a la terminal Mercado Pago de una caja.

    Se crea antes de registrar la venta: la venta solo se registra cuando la
    terminal dice que se pagó, y entonces queda ligada (`venta_id`). Un cobro
    pagado sin venta (se cayó la red al registrarla, se cerró la pantalla) se
    reutiliza en el siguiente cobro del mismo monto en esa caja.
    Ver app/pagos/mercadopago.py y services/terminal.py.
    """

    __tablename__ = "cobros_terminal"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    caja_id: Mapped[int] = mapped_column(ForeignKey("cajas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    terminal_id: Mapped[str]
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    idempotencia: Mapped[str]
    orden_id: Mapped[str | None] = mapped_column(default=None, index=True)
    pago_id: Mapped[str | None] = mapped_column(default=None)
    # Estado de la orden en Mercado Pago: created, at_terminal, processed,
    # canceled, expired, failed (ver pagos/mercadopago.py).
    estado: Mapped[str] = mapped_column(default="created")
    detalle: Mapped[str | None] = mapped_column(default=None)
    tarjeta: Mapped[str | None] = mapped_column(default=None)
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
