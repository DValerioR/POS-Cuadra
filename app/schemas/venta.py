from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.devolucion import TipoDevolucion
from app.models.venta import EstadoVenta, MetodoPago


class RenglonIn(BaseModel):
    producto_id: int
    cantidad: Decimal = Field(gt=0)
    lote_id: int | None = None  # lote que se entregó; sin lote = FEFO
    caducidad: date | None = None  # caducidad de la caja en mano (si no estaba registrada)
    numero_lote: str | None = None


class VentaIn(BaseModel):
    caja_id: int
    renglones: list[RenglonIn] = Field(min_length=1)
    tarjeta: Decimal = Field(default=Decimal(0), ge=0)
    efectivo_recibido: Decimal = Field(default=Decimal(0), ge=0)


class LoteVendidoOut(BaseModel):
    lote_id: int
    cantidad: Decimal
    cantidad_devuelta: Decimal
    numero_lote: str | None
    caducidad: date | None


class RenglonOut(BaseModel):
    id: int
    producto_id: int
    nombre: str
    cantidad: Decimal
    precio_unitario: Decimal
    importe: Decimal
    subtotal: Decimal
    ieps: Decimal
    iva: Decimal
    cantidad_devuelta: Decimal
    lotes: list[LoteVendidoOut]


class PagoOut(BaseModel):
    metodo: MetodoPago
    monto: Decimal
    recibido: Decimal | None
    cambio: Decimal | None


class VentaOut(BaseModel):
    id: int
    folio: int
    turno_id: int
    caja_id: int
    usuario_id: int
    estado: EstadoVenta
    subtotal: Decimal
    ieps: Decimal
    iva: Decimal
    total: Decimal
    cambio: Decimal
    created_at: datetime
    renglones: list[RenglonOut]
    pagos: list[PagoOut]
    devoluciones: list["DevolucionOut"] = []
    avisos: list[str] = []  # ej. "requiere receta"; solo al registrar


class VentaResumenOut(BaseModel):
    id: int
    folio: int
    turno_id: int
    caja_id: int
    usuario_id: int
    estado: EstadoVenta
    total: Decimal
    created_at: datetime


class CancelarIn(BaseModel):
    caja_id: int  # caja (con turno abierto) de donde sale el dinero
    motivo: str = Field(min_length=1)


class PiezaDevueltaIn(BaseModel):
    renglon_id: int
    cantidad: Decimal = Field(gt=0)
    lote_id: int | None = None  # lote de la caja devuelta, si se sabe


class DevolverIn(BaseModel):
    caja_id: int
    motivo: str = Field(min_length=1)
    piezas: list[PiezaDevueltaIn] = Field(min_length=1)


class DevolucionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    venta_id: int
    turno_id: int
    usuario_id: int
    tipo: TipoDevolucion
    motivo: str
    total: Decimal
    efectivo: Decimal
    tarjeta: Decimal
    created_at: datetime


# VentaOut menciona DevolucionOut antes de que exista; se resuelve aquí.
VentaOut.model_rebuild()
