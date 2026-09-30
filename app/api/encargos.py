"""Encargos de clientes (admin, mostrador y bodega). Ver services/encargos.py."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.entradas import _exacto
from app.core.auth import usuario_actual
from app.core.database import get_db
from app.models import Encargo, EstadoEncargo, Producto, Usuario
from app.services import encargos
from app.services.errores import ERRORES_NEGOCIO, a_http

# GET /encargos es la pantalla: por eso la lista es /encargos/lista.
router = APIRouter(prefix="/encargos", tags=["encargos"])


class EncargoIn(BaseModel):
    cliente: str = Field(min_length=1, max_length=120)
    telefono: str | None = Field(default=None, max_length=40)
    producto_id: int | None = None
    descripcion: str | None = Field(default=None, max_length=200)
    cantidad: Decimal = Field(default=Decimal(1), gt=0)
    notas: str | None = Field(default=None, max_length=500)


class EstadoIn(BaseModel):
    estado: EstadoEncargo


def _out(db: Session, e: Encargo) -> dict:
    p = db.get(Producto, e.producto_id) if e.producto_id else None
    creo = db.get(Usuario, e.creado_por_id) if e.creado_por_id else None
    return _exacto({
        "id": e.id, "producto_id": e.producto_id, "clave": p.clave if p else None, "descripcion": e.descripcion,
        "producto_encargo": bool(p and p.encargo), "cantidad": e.cantidad, "cliente": e.cliente, "telefono": e.telefono,
        "canal": e.canal, "notas": e.notas, "estado": e.estado.value, "estado_texto": encargos.texto_estado(e.estado),
        "pedido_id": e.pedido_id, "falta_avisar": encargos.falta_avisar(e), "avisado_at": e.avisado_at,
        "avisado_por": e.avisado_por, "aviso_texto": e.aviso_texto, "aviso_error": e.aviso_error,
        "creado_por": (creo.nombre_completo or creo.nombre_usuario) if creo else ("Bot de WhatsApp" if e.canal == "whatsapp" else None),
        "created_at": e.created_at, "updated_at": e.updated_at,
    })


@router.get("/lista")
def listar(todos: bool = Query(False), usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Encargos abiertos (por pedir, pedidos y que ya llegaron), o todos con `todos`."""
    try:
        encargos._validar_rol(usuario)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    return [_out(db, e) for e in encargos.listar(db, usuario.negocio_id, abiertos=not todos)]


@router.post("", status_code=201)
def crear(datos: EncargoIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        e = encargos.crear(db, usuario.negocio_id, usuario, datos.cliente, datos.producto_id, datos.descripcion,
                           datos.cantidad, datos.telefono, datos.notas)
    except ERRORES_NEGOCIO as err:
        db.rollback()
        raise a_http(err)
    db.commit()
    return _out(db, e)


@router.put("/{encargo_id}/estado")
def cambiar_estado(encargo_id: int, datos: EstadoIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        e = encargos.cambiar_estado(db, usuario, encargo_id, datos.estado)
    except ERRORES_NEGOCIO as err:
        db.rollback()
        raise a_http(err)
    db.commit()
    # Ya guardado el cambio, el bot le avisa al cliente por WhatsApp (si falla, queda "Falta avisar").
    encargos.avisar(db, e)
    db.commit()
    return _out(db, e)


@router.post("/{encargo_id}/avisado")
def avisado(encargo_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Ya se le avisó al cliente del estado actual (que se pidió o que llegó)."""
    try:
        e = encargos.marcar_avisado(db, usuario, encargo_id)
    except ERRORES_NEGOCIO as err:
        db.rollback()
        raise a_http(err)
    db.commit()
    return _out(db, e)

