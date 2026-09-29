import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TipoTurno(str, enum.Enum):
    MANANA = "manana"
    TARDE = "tarde"


class Turno(Base):
    """Turno de caja. Se abre con un fondo; al cerrarse se guarda lo que el
    sistema esperaba en efectivo y tarjeta, lo que se contó y la diferencia,
    con quién cerró. Una caja solo puede tener un turno abierto a la vez.

    Los importes "esperados" se congelan al cerrar: si después se corrige una
    venta, el corte ya hecho no cambia.
    """

    __tablename__ = "turnos"
    __table_args__ = (
        # Un solo turno abierto (cerrado_en IS NULL) por caja.
        Index("uq_turno_abierto_por_caja", "caja_id", unique=True, postgresql_where=text("cerrado_en IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    caja_id: Mapped[int] = mapped_column(ForeignKey("cajas.id"), index=True)
    tipo: Mapped[TipoTurno]
    fondo_inicial: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    abierto_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    abierto_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cerrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), default=None)
    cerrado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    efectivo_esperado: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    tarjeta_esperado: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    efectivo_contado: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    tarjeta_contado: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    # contado - esperado: negativo = faltante, positivo = sobrante.
    diferencia_efectivo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    diferencia_tarjeta: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    notas_cierre: Mapped[str | None] = mapped_column(default=None)
