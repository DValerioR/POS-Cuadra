from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VentaEnEspera(Base):
    """Venta a medias que se guarda para atender a otro cliente y retomarla
    después (máximo 5 por caja, ver services/ventas_en_espera.py).

    No aparta existencia: lo que se guarda es lo que había en la pantalla
    (productos, cantidades, lote elegido y caducidad capturada), y todo se
    vuelve a revisar al cobrar. Mientras haya ventas guardadas en una caja,
    no se puede hacer su corte.
    """

    __tablename__ = "ventas_en_espera"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    caja_id: Mapped[int] = mapped_column(ForeignKey("cajas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    # Para reconocerla: "señora de lentes", "el de la receta"...
    nota: Mapped[str | None] = mapped_column(default=None)
    # [{producto_id, cantidad, lote_id, caducidad_mes, numero_lote}, ...]
    renglones: Mapped[list[dict]] = mapped_column(JSONB)
    articulos: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # con los precios de cuando se guardó
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
