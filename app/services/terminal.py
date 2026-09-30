"""Terminal Mercado Pago Point: token, terminal de cada caja y cobros.

Flujo de un cobro con tarjeta (pantalla de venta):
1. `crear_cobro` manda el monto a la terminal de la caja.
2. La pantalla llama `actualizar` cada ~2 s hasta que el cobro termina
   (pagado, cancelado, expirado o fallido).
3. Si se pagó, la venta se registra con `cobro_terminal_id` y `usar_en_venta`
   revisa que el cobro sea de esa caja, esté pagado, sin venta y por el monto
   de tarjeta; luego queda ligado a la venta.
Un cobro pagado que se quedó sin venta se reutiliza en el siguiente cobro del
mismo monto en esa caja (así no se le cobra dos veces al cliente).

El token vive en el .env como MERCADOPAGO_TOKEN (igual que la clave de IA) y
nunca se regresa completo por el API.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config
from app.core.config import settings
from app.models import Caja, CobroTerminal, RolUsuario, Usuario
from app.pagos import mercadopago as mp
from app.services import turnos
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso

VARIABLE = "MERCADOPAGO_TOKEN"
# Tokens de producción (APP_USR-...) o de prueba (TEST-...). Evita también que
# un salto de línea o un "=" pegados por error metan otra variable en el .env.
FORMATO = re.compile(r"^(APP_USR|TEST)-[A-Za-z0-9\-]{20,300}$")
PENDIENTES = {mp.CREADA, mp.EN_TERMINAL}

MENSAJES = {
    mp.CREADA: "Enviando el cobro a la terminal…",
    mp.EN_TERMINAL: "Pida al cliente que pase, inserte o acerque su tarjeta en la terminal.",
    mp.PAGADA: "Pago aprobado.",
    mp.CANCELADA: "El cobro se canceló.",
    mp.EXPIRADA: "El cobro expiró sin pagarse.",
    mp.FALLIDA: "La terminal rechazó el pago.",
    "error": "No se pudo mandar el cobro a la terminal.",
}


def _cliente():
    try:
        return mp.cliente(settings.mercadopago_token)
    except mp.ErrorMercadoPago as e:
        raise OperacionInvalida(e.mensaje)


# --- Token y terminales ------------------------------------------------------


def estado_token() -> dict:
    token = settings.mercadopago_token
    return {"configurado": bool(token), "termina_en": token[-4:] if token else None,
            "prueba": bool(token and token.startswith("TEST-")), "simulado": mp._simulado is not None}


def guardar_token(token: str) -> dict:
    token = (token or "").strip()
    if not FORMATO.match(token):
        raise OperacionInvalida(
            "Ese no parece un token de Mercado Pago: debe empezar con APP_USR- (o TEST-) y no llevar espacios"
        )
    config.escribir_variable(VARIABLE, token)
    settings.mercadopago_token = token
    return estado_token()


def quitar_token() -> dict:
    config.escribir_variable(VARIABLE, None)
    settings.mercadopago_token = None
    return estado_token()


def terminales(db: Session, negocio_id: int) -> list[dict]:
    """Las terminales de la cuenta de Mercado Pago y qué caja usa cada una."""
    try:
        lista = _cliente().terminales()
    except mp.ErrorMercadoPago as e:
        raise OperacionInvalida(e.mensaje)
    cajas = {c.terminal_mp: c for c in db.scalars(select(Caja).where(
        Caja.negocio_id == negocio_id, Caja.terminal_mp.is_not(None)))}
    return [{"id": t.id, "modo": t.modo, "nombre": _nombre_terminal(t.id),
             "caja_id": cajas[t.id].id if t.id in cajas else None,
             "caja": cajas[t.id].nombre if t.id in cajas else None} for t in lista]


def _nombre_terminal(terminal_id: str) -> str:
    """"NEWLAND_N950__N950NCB801293324" → "NEWLAND N950 · serie N950NCB801293324"."""
    modelo, _, serie = terminal_id.partition("__")
    return f"{modelo.replace('_', ' ')} · serie {serie}" if serie else terminal_id


def activar_pdv(terminal_id: str) -> None:
    try:
        _cliente().modo_pdv(terminal_id)
    except mp.ErrorMercadoPago as e:
        raise OperacionInvalida(e.mensaje)


def asignar(db: Session, negocio_id: int, caja_id: int, terminal_id: str | None) -> Caja:
    """Pone (o quita, con None) la terminal de una caja. Una terminal es de una sola caja."""
    caja = turnos.obtener_caja(db, negocio_id, caja_id)
    terminal_id = (terminal_id or "").strip() or None
    if terminal_id:
        otra = db.scalar(select(Caja).where(
            Caja.negocio_id == negocio_id, Caja.terminal_mp == terminal_id, Caja.id != caja.id))
        if otra is not None:
            raise OperacionInvalida(f"Esa terminal ya es de la caja '{otra.nombre}'")
    caja.terminal_mp = terminal_id
    db.flush()
    return caja


# --- Cobros --------------------------------------------------------------------


def _puede_cobrar(usuario: Usuario) -> None:
    if usuario.rol not in (RolUsuario.ADMIN, RolUsuario.MOSTRADOR):
        raise SinPermiso(f"El rol {usuario.rol.value} no puede cobrar")


def obtener(db: Session, negocio_id: int, cobro_id: int) -> CobroTerminal:
    cobro = db.get(CobroTerminal, cobro_id)
    if cobro is None or cobro.negocio_id != negocio_id:
        raise NoEncontrado("Cobro no encontrado")
    return cobro


def crear_cobro(db: Session, usuario: Usuario, caja_id: int, monto) -> CobroTerminal:
    """Manda el monto a la terminal de la caja. Si en esa caja hay un cobro del
    mismo monto que ya se pagó y no tiene venta, o que sigue esperando en la
    terminal, regresa ese en lugar de cobrar otra vez. Hace commit (el cobro
    debe quedar guardado aunque falle lo que sigue)."""
    _puede_cobrar(usuario)
    caja = turnos.obtener_caja(db, usuario.negocio_id, caja_id)
    if not caja.terminal_mp:
        raise OperacionInvalida(f"La caja '{caja.nombre}' no tiene terminal Mercado Pago")
    if turnos.turno_abierto(db, caja.id) is None:
        raise OperacionInvalida(f"La caja '{caja.nombre}' no tiene turno abierto")
    if monto <= 0:
        raise OperacionInvalida("El monto a cobrar debe ser mayor que cero")

    abiertos = db.scalars(select(CobroTerminal).where(
        CobroTerminal.caja_id == caja.id, CobroTerminal.venta_id.is_(None),
        CobroTerminal.estado.in_(PENDIENTES | {mp.PAGADA}),
    ).order_by(CobroTerminal.id)).all()
    for cobro in abiertos:
        actualizar(db, cobro)
        if cobro.estado in PENDIENTES | {mp.PAGADA}:
            if cobro.monto == monto:
                return cobro
            if cobro.estado in PENDIENTES:
                raise OperacionInvalida(
                    f"La terminal tiene esperando un cobro de ${cobro.monto:,.2f}: cancélalo antes de mandar otro"
                )

    cobro = CobroTerminal(negocio_id=usuario.negocio_id, caja_id=caja.id, usuario_id=usuario.id,
                          terminal_id=caja.terminal_mp, monto=monto, idempotencia=mp.nueva_idempotencia())
    db.add(cobro)
    db.commit()
    try:
        orden = _cliente().crear_orden(caja.terminal_mp, monto, f"pos-{cobro.negocio_id}-{cobro.id}", cobro.idempotencia)
    except (mp.ErrorMercadoPago, OperacionInvalida) as e:
        cobro.estado, cobro.detalle = "error", getattr(e, "mensaje", str(e))
        db.commit()
        raise OperacionInvalida(cobro.detalle)
    cobro.orden_id, cobro.pago_id, cobro.estado, cobro.detalle = orden.id, orden.pago_id, orden.estado, orden.detalle
    db.commit()
    return cobro


def actualizar(db: Session, cobro: CobroTerminal) -> CobroTerminal:
    """Pregunta a Mercado Pago cómo va el cobro (si aún no terminó). Si no hay
    conexión, se queda como estaba y se vuelve a preguntar después. No hace commit."""
    if cobro.orden_id and cobro.estado in PENDIENTES:
        try:
            orden = _cliente().consultar(cobro.orden_id)
        except (mp.ErrorMercadoPago, OperacionInvalida):
            return cobro
        cobro.estado, cobro.detalle = orden.estado, orden.detalle
        cobro.pago_id = orden.pago_id or cobro.pago_id
        cobro.tarjeta = orden.tarjeta or cobro.tarjeta
        db.flush()
    return cobro


def cancelar(db: Session, usuario: Usuario, cobro_id: int) -> CobroTerminal:
    """Cancela un cobro que aún no llega a la terminal. Si ya está en la
    terminal, se cancela ahí (con el botón de la terminal). No hace commit."""
    _puede_cobrar(usuario)
    cobro = actualizar(db, obtener(db, usuario.negocio_id, cobro_id))
    if cobro.estado == mp.EN_TERMINAL:
        raise OperacionInvalida("El cobro ya está en la terminal: cancélalo con el botón rojo de la terminal")
    if cobro.estado != mp.CREADA:
        return cobro
    try:
        orden = _cliente().cancelar(cobro.orden_id, mp.nueva_idempotencia())
    except mp.ErrorMercadoPago as e:
        raise OperacionInvalida(e.mensaje)
    cobro.estado, cobro.detalle = orden.estado, orden.detalle
    db.flush()
    return cobro


def usar_en_venta(db: Session, negocio_id: int, caja_id: int, cobro_id: int, tarjeta) -> CobroTerminal:
    """Revisa que el cobro sirva para esta venta (antes de registrarla)."""
    cobro = actualizar(db, obtener(db, negocio_id, cobro_id))
    if cobro.caja_id != caja_id:
        raise OperacionInvalida("Ese cobro con tarjeta es de otra caja")
    if cobro.venta_id is not None:
        raise OperacionInvalida("Ese cobro con tarjeta ya se usó en otra venta")
    if cobro.estado != mp.PAGADA:
        raise OperacionInvalida("La terminal todavía no confirma el pago con tarjeta")
    if cobro.monto != tarjeta:
        raise OperacionInvalida(
            f"La terminal cobró ${cobro.monto:,.2f} y la venta dice ${tarjeta:,.2f} con tarjeta"
        )
    return cobro


def sin_venta(db: Session, negocio_id: int, caja_id: int) -> list[CobroTerminal]:
    """Cobros pagados en la terminal que no quedaron en ninguna venta (para avisar)."""
    return list(db.scalars(select(CobroTerminal).where(
        CobroTerminal.negocio_id == negocio_id, CobroTerminal.caja_id == caja_id,
        CobroTerminal.estado == mp.PAGADA, CobroTerminal.venta_id.is_(None),
    ).order_by(CobroTerminal.id)))
