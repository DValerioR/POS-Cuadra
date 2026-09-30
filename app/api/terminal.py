"""Terminal Mercado Pago Point: configuración (solo admin) y cobros (venta).
Ver services/terminal.py."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import CobroTerminal, Usuario
from app.services import terminal
from app.services.errores import ERRORES_NEGOCIO, a_http

router = APIRouter(prefix="/terminal", tags=["terminal"])


class TokenIn(BaseModel):
    token: str


class AsignarIn(BaseModel):
    caja_id: int
    terminal_id: str | None = None


class TerminalIn(BaseModel):
    terminal_id: str


class CobroIn(BaseModel):
    caja_id: int
    monto: Decimal = Field(gt=0)


def _cobro(c: CobroTerminal) -> dict:
    return {"id": c.id, "caja_id": c.caja_id, "monto": f"{c.monto:.2f}", "estado": c.estado,
            "mensaje": terminal.MENSAJES.get(c.estado, c.detalle or c.estado), "detalle": c.detalle,
            "tarjeta": c.tarjeta, "venta_id": c.venta_id, "terminado": c.estado not in terminal.PENDIENTES,
            "pagado": c.estado == "processed"}


# --- Configuración -------------------------------------------------------------


@router.get("/token")
def ver_token(usuario: Usuario = Depends(solo_admin)):
    return terminal.estado_token()


@router.put("/token")
def guardar_token(datos: TokenIn, usuario: Usuario = Depends(solo_admin)):
    try:
        return terminal.guardar_token(datos.token)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.delete("/token")
def quitar_token(usuario: Usuario = Depends(solo_admin)):
    return terminal.quitar_token()


@router.get("/terminales")
def terminales(usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Terminales de la cuenta (también sirve para probar el token)."""
    try:
        return terminal.terminales(db, usuario.negocio_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.post("/modo-pdv")
def modo_pdv(datos: TerminalIn, usuario: Usuario = Depends(solo_admin)):
    """Pone la terminal en modo PDV (cobra lo que le manda el sistema). Hay que reiniciarla después."""
    try:
        terminal.activar_pdv(datos.terminal_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    return {"ok": True}


@router.put("/caja")
def asignar(datos: AsignarIn, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    try:
        caja = terminal.asignar(db, usuario.negocio_id, datos.caja_id, datos.terminal_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return {"caja_id": caja.id, "terminal_id": caja.terminal_mp}


# --- Cobros --------------------------------------------------------------------


@router.post("/cobros", status_code=201)
def crear_cobro(datos: CobroIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Manda el monto a la terminal de la caja (o regresa el cobro que ya
    estaba pagado o esperando por ese monto)."""
    try:
        return _cobro(terminal.crear_cobro(db, usuario, datos.caja_id, datos.monto))
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)


@router.get("/cobros/sin-venta")
def sin_venta(caja_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    return [_cobro(c) for c in terminal.sin_venta(db, usuario.negocio_id, caja_id)]


@router.get("/cobros/{cobro_id}")
def ver_cobro(cobro_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Cómo va el cobro (pregunta a Mercado Pago si aún no termina)."""
    try:
        cobro = terminal.actualizar(db, terminal.obtener(db, usuario.negocio_id, cobro_id))
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    db.commit()
    return _cobro(cobro)


@router.post("/cobros/{cobro_id}/cancelar")
def cancelar(cobro_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        cobro = terminal.cancelar(db, usuario, cobro_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return _cobro(cobro)
