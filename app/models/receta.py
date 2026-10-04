from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Medico(Base):
    """Médico que firmó una receta de antibióticos. Se recuerda por su cédula
    para no volver a escribir su nombre y domicilio."""

    __tablename__ = "medicos"
    __table_args__ = (UniqueConstraint("negocio_id", "cedula", name="uq_medico_cedula_por_negocio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    cedula: Mapped[str]  # cédula profesional
    nombre: Mapped[str]
    domicilio: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RecetaVenta(Base):
    """Datos de la receta con la que se vendieron antibióticos (la farmacia
    se queda con la receta). Se capturan después de la venta, desde el
    reporte de antibióticos, para no hacer esperar al cliente. Se copian los
    datos del médico tal como venían en la receta."""

    __tablename__ = "recetas_venta"

    id: Mapped[int] = mapped_column(primary_key=True)
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), index=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), unique=True)
    medico_id: Mapped[int | None] = mapped_column(ForeignKey("medicos.id"), default=None)
    medico_nombre: Mapped[str]
    cedula: Mapped[str]
    domicilio: Mapped[str | None] = mapped_column(default=None)
    fecha_receta: Mapped[date | None] = mapped_column(Date, default=None)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))  # quién la capturó
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
