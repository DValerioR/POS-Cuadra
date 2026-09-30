"""Ofertas que se aplican al vender. Las rutas van bajo /ofertas/..., pero
GET /ofertas es la pantalla: por eso la lista es /ofertas/activas."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.entradas import _exacto
from app.asistente.consultas import hoy
from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Oferta, Usuario
from app.services import ofertas_venta
from app.services.errores import ERRORES_NEGOCIO, a_http

router = APIRouter(prefix="/ofertas", tags=["ofertas"])


class OfertaIn(BaseModel):
    producto_id: int
    tipo: str
    precio: Decimal | None = Field(default=None, ge=0)
    paquete_con_id: int | None = None
    fin: date
    motivo: str | None = None
    origen: str = "manual"


def _nombre(u: Usuario | None) -> str | None:
    return (u.nombre_completo or u.nombre_usuario) if u else None


def _out(db: Session, o: Oferta) -> dict:
    p = o.producto
    return _exacto({
        "id": o.id, "producto_id": o.producto_id, "clave": p.clave, "nombre": p.nombre, "precio_normal": p.precio_venta,
        "tipo": o.tipo, "precio": o.precio, "texto": ofertas_venta.texto(o, o.producto_id),
        "paquete_con": {"producto_id": o.paquete_con.id, "nombre": o.paquete_con.nombre,
                        "precio_normal": o.paquete_con.precio_venta} if o.paquete_con else None,
        "inicio": o.inicio, "fin": o.fin, "activa": o.activa and o.fin >= hoy(), "motivo": o.motivo, "origen": o.origen,
        "creada_por": _nombre(db.get(Usuario, o.creada_por_id)), "created_at": o.created_at,
        "quitada_por": _nombre(db.get(Usuario, o.quitada_por_id)) if o.quitada_por_id else None, "quitada_en": o.quitada_en,
    })


@router.get("/activas")
def activas(usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Ofertas vigentes hoy y las que terminaron o se quitaron en los
    últimos 30 días (para ver qué hubo)."""
    vigentes = ofertas_venta.activas(db, usuario.negocio_id)
    ids = {o.id for o in vigentes}
    recientes = db.scalars(
        select(Oferta).where(Oferta.negocio_id == usuario.negocio_id, Oferta.fin >= date.fromordinal(hoy().toordinal() - 30))
        .order_by(Oferta.fin.desc(), Oferta.id.desc())
    ).all()
    return {"activas": [_out(db, o) for o in vigentes],
            "terminadas": [_out(db, o) for o in recientes if o.id not in ids][:50]}


@router.get("/minimo")
def minimo(producto_id: int, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Precio normal y el más bajo permitido para una oferta del producto."""
    try:
        p = ofertas_venta._producto(db, usuario.negocio_id, producto_id)
        return _exacto({"producto_id": p.id, "nombre": p.nombre, "precio_normal": p.precio_venta,
                        "precio_minimo": ofertas_venta.precio_minimo(db, p), "requiere_receta": p.requiere_receta,
                        "caduca_pronto": ofertas_venta._caduca_pronto(db, p.id)})
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/producto/{producto_id}")
def del_producto(producto_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """La oferta de hoy del producto (o null), para consultar precio."""
    return _exacto(ofertas_venta.del_producto(db, usuario.negocio_id, producto_id))


@router.post("", status_code=201)
def crear(datos: OfertaIn, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    try:
        o = ofertas_venta.crear(db, usuario, datos.producto_id, datos.tipo, datos.precio, datos.fin,
                                datos.paquete_con_id, datos.motivo, datos.origen)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(o)
    return _out(db, o)


@router.post("/{oferta_id}/quitar")
def quitar(oferta_id: int, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    try:
        o = ofertas_venta.quitar(db, usuario, oferta_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(o)
    return _out(db, o)
