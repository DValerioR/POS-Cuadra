import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TipoAjuste(str, enum.Enum):
    IMPORTACION = "importacion"  # existencia inicial traída de PVWin
    AJUSTE = "ajuste"  # corrección por conteo físico u otra diferencia
    MERMA = "merma"  # caducado o dañado; sale del inventario sin borrarse
    CAPTURA_CADUCIDAD = "captura_caducidad"  # piezas que pasan del lote "sin caducidad" a uno real


class AjusteInventario(Base):
    """Bitácora de todo cambio de existencia que no sea venta ni entrada de
    mercancía. Nunca se edita ni se borra: una corrección es otro ajuste.

    `cantidad` es con signo: positiva suma piezas al lote, negativa las resta.
    Una captura de caducidad genera dos renglones: -N en el lote sin caducidad
    y +N en el lote real.
    """

    __tablename__ = "ajustes_inventario"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    tipo: Mapped[TipoAjuste]
    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    motivo: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
