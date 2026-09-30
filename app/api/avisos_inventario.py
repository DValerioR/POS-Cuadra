from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import usuario_actual
from app.core.database import get_db
from app.models import AvisoInventario, EstadoAviso, RolUsuario, Usuario
from app.services import avisos_inventario, encargos, inventario, respaldos, solicitudes
from app.services.errores import ERRORES_NEGOCIO, a_http

router = APIRouter(tags=["avisos de inventario"])


class AvisoOut(BaseModel):
    id: int
    producto_id: int
    clave: str | None
    producto: str
    venta_id: int
    folio: int
    caja: str
    vendio: str
    vendidas: Decimal
    faltantes: Decimal
    existencia_actual: Decimal  # en el sistema ahora (puede ser negativa)
    estado: EstadoAviso
    revisado_por: str | None
    revisado_en: datetime | None
    conteo: Decimal | None
    created_at: datetime


class ConteoIn(BaseModel):
    conteo: Decimal = Field(ge=0)


def _nombre(u: Usuario | None) -> str | None:
    return (u.nombre_completo or u.nombre_usuario) if u else None


def _out(db: Session, a: AvisoInventario) -> AvisoOut:
    return AvisoOut(
        id=a.id, producto_id=a.producto_id, clave=a.producto.clave, producto=a.producto.nombre,
        venta_id=a.venta_id, folio=a.venta.folio, caja=a.caja.nombre, vendio=_nombre(a.vendedor),
        vendidas=a.vendidas, faltantes=a.faltantes,
        existencia_actual=inventario.existencia_total(db, a.producto_id),
        estado=a.estado, revisado_por=_nombre(a.revisado_por), revisado_en=a.revisado_en, conteo=a.conteo,
        created_at=a.created_at,
    )


@router.get("/avisos-inventario", response_model=list[AvisoOut])
def listar(
    estado: EstadoAviso | None = None,
    desde: datetime | None = None,
    limite: int = Query(50, le=200),
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    """Ventas sin existencia registrada (solo admin)."""
    try:
        return [_out(db, a) for a in avisos_inventario.listar(db, usuario, estado, desde, limite)]
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.post("/avisos-inventario/{aviso_id}/conteo", response_model=list[AvisoOut])
def registrar_conteo(
    aviso_id: int, datos: ConteoIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db),
):
    """Ajusta la existencia a lo que se contó en anaquel y cierra los avisos del producto."""
    try:
        avisos = avisos_inventario.resolver_con_conteo(db, usuario, aviso_id, datos.conteo)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return [_out(db, a) for a in avisos]


@router.post("/avisos-inventario/{aviso_id}/revisado", response_model=list[AvisoOut])
def marcar_revisado(aviso_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Cierra los avisos del producto sin cambiar la existencia."""
    try:
        avisos = avisos_inventario.marcar_revisado(db, usuario, aviso_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return [_out(db, a) for a in avisos]


@router.get("/notificaciones/pendientes")
def pendientes(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Todo lo que espera a un administrador (para la campana)."""
    try:
        s = solicitudes.contar_pendientes(db, usuario)
        a = avisos_inventario.contar_pendientes(db, usuario)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    # El respaldo falló o hace más de un día que no hay: también espera al administrador.
    r = 1 if usuario.rol == RolUsuario.ADMIN and respaldos.automaticos_activos() and respaldos.estado()["necesita_atencion"] else 0
    # Encargos de clientes que falta pedir al proveedor.
    e = encargos.contar_por_pedir(db, usuario.negocio_id) if usuario.rol == RolUsuario.ADMIN else 0
    return {"solicitudes": s, "inventario": a, "respaldo": r, "encargos": e, "total": s + a + r + e}
