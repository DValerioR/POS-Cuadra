"""Encargos de clientes: un producto que un cliente pidió en específico.

Flujo: Por pedir -> Pedido al proveedor -> Llegó -> Entregado (o Cancelado,
o No se pudo encargar si el proveedor no tiene existencias).

Avisos al cliente: al pasar a "Pedido al proveedor", "Llegó" o "No se pudo
encargar", el bot le manda por WhatsApp la plantilla formal que corresponde
(app/whatsapp/cliente.py). Si no se puede (sin teléfono, WhatsApp sin
configurar, falla el envío), queda "Falta avisar" y el personal le avisa y lo
marca ("Ya le avisé").

- Se registran en el mostrador (pantalla Encargos o Consultar precio) o, más
  adelante, por el bot de WhatsApp (sin usuario, `canal="whatsapp"`).
- Los "por pedir" aparecen en la campana y en Pedidos, para agregarlos al
  pedido del proveedor. Al enviar un pedido, los encargos por pedir de sus
  productos pasan solos a "Pedido al proveedor".
- Los productos marcados "Encargo" (Producto.encargo) no tienen mínimo ni
  máximo: solo se piden así.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Encargo, EstadoEncargo, Negocio, Pedido, Producto, RolUsuario, Usuario
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso
from app.whatsapp import cliente as whatsapp

ROLES = {RolUsuario.ADMIN, RolUsuario.MOSTRADOR, RolUsuario.BODEGA}
ABIERTOS = (EstadoEncargo.POR_PEDIR, EstadoEncargo.PEDIDO, EstadoEncargo.LLEGO, EstadoEncargo.NO_DISPONIBLE)
# A qué estados se puede pasar desde cada uno.
SIGUIENTES = {
    EstadoEncargo.POR_PEDIR: {EstadoEncargo.PEDIDO, EstadoEncargo.NO_DISPONIBLE, EstadoEncargo.CANCELADO},
    EstadoEncargo.PEDIDO: {EstadoEncargo.LLEGO, EstadoEncargo.NO_DISPONIBLE, EstadoEncargo.POR_PEDIR, EstadoEncargo.CANCELADO},
    EstadoEncargo.LLEGO: {EstadoEncargo.ENTREGADO, EstadoEncargo.CANCELADO},
    EstadoEncargo.NO_DISPONIBLE: {EstadoEncargo.POR_PEDIR, EstadoEncargo.CANCELADO},
    EstadoEncargo.ENTREGADO: set(),
    EstadoEncargo.CANCELADO: {EstadoEncargo.POR_PEDIR},
}
# Por qué no se pudo encargar: (texto para la farmacia, frase formal para el
# cliente). La frase completa: "...no fue posible encargar X, <frase>."
# En "otro" el detalle del personal NO se le manda al cliente.
MOTIVOS = {
    "sin_existencias": ("El proveedor no tiene existencias", "ya que nuestro proveedor no cuenta con existencias por el momento"),
    "controlado": ("Es un medicamento controlado", "ya que se trata de un medicamento controlado"),
    "proveedor_no_maneja": ("El proveedor no lo maneja", "ya que nuestro proveedor no maneja este producto"),
    "no_manejamos": ("No lo manejamos en la farmacia", "ya que es un producto que no manejamos en nuestra farmacia"),
    "otro": ("Otro motivo", "por causas ajenas a nuestra farmacia"),
}

# Cambios que se le avisan al cliente, con su plantilla de WhatsApp.
PLANTILLA_DE = {
    EstadoEncargo.PEDIDO: "encargo_pedido",
    EstadoEncargo.LLEGO: "encargo_disponible",
    EstadoEncargo.NO_DISPONIBLE: "encargo_no_disponible",
}


def _validar_rol(usuario: Usuario) -> None:
    if usuario.rol not in ROLES:
        raise SinPermiso("No tienes permiso para los encargos")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def obtener(db: Session, negocio_id: int, encargo_id: int) -> Encargo:
    e = db.get(Encargo, encargo_id)
    if e is None or e.negocio_id != negocio_id:
        raise NoEncontrado("Encargo no encontrado")
    return e


def crear(db: Session, negocio_id: int, usuario: Usuario | None, cliente: str, producto_id: int | None = None,
          descripcion: str | None = None, cantidad: Decimal = Decimal(1), telefono: str | None = None,
          notas: str | None = None, canal: str = "mostrador") -> Encargo:
    """Registra un encargo. `usuario` None = lo levantó el bot. No hace commit."""
    if usuario is not None:
        _validar_rol(usuario)
    cliente = " ".join((cliente or "").split())
    if not cliente:
        raise OperacionInvalida("Falta el nombre del cliente")
    if cantidad <= 0:
        raise OperacionInvalida("La cantidad debe ser mayor que cero")
    producto = None
    if producto_id is not None:
        producto = db.get(Producto, producto_id)
        if producto is None or producto.negocio_id != negocio_id:
            raise NoEncontrado("Producto no encontrado")
    descripcion = " ".join((descripcion or (producto.nombre if producto else "")).split())
    if not descripcion:
        raise OperacionInvalida("Indica qué producto quiere el cliente")
    e = Encargo(negocio_id=negocio_id, producto_id=producto.id if producto else None, descripcion=descripcion,
                cantidad=cantidad, cliente=cliente, telefono=" ".join((telefono or "").split()) or None,
                notas=(notas or "").strip() or None, canal=canal, creado_por_id=usuario.id if usuario else None)
    db.add(e)
    db.flush()
    return e


def cambiar_estado(db: Session, usuario: Usuario, encargo_id: int, estado: EstadoEncargo,
                   motivo: str | None = None, detalle: str | None = None) -> Encargo:
    """`motivo` y `detalle`: por qué no se pudo encargar (obligatorio al pasar
    a No se pudo encargar; con "otro", el detalle también). No hace commit."""
    _validar_rol(usuario)
    e = obtener(db, usuario.negocio_id, encargo_id)
    if estado == e.estado:
        return e
    if estado not in SIGUIENTES[e.estado]:
        raise OperacionInvalida(f"Un encargo {texto_estado(e.estado).lower()} no puede pasar a {texto_estado(estado).lower()}")
    detalle = " ".join((detalle or "").split()) or None
    if estado == EstadoEncargo.NO_DISPONIBLE:
        if motivo not in MOTIVOS:
            raise OperacionInvalida("Indica por qué no se pudo encargar")
        if motivo == "otro" and not detalle:
            raise OperacionInvalida("Escribe el motivo")
        e.motivo_no_disponible, e.motivo_detalle = motivo, detalle
    e.estado = estado
    if estado == EstadoEncargo.POR_PEDIR:
        e.pedido_id = None
    db.flush()
    return e


def texto_motivo(e: Encargo) -> str | None:
    """El motivo para mostrarlo en la farmacia (ej. "Otro motivo: descontinuado")."""
    if not e.motivo_no_disponible:
        return None
    base = MOTIVOS.get(e.motivo_no_disponible, ("Otro motivo", ""))[0]
    if e.motivo_no_disponible == "otro" and e.motivo_detalle:
        return e.motivo_detalle
    return f"{base}: {e.motivo_detalle}" if e.motivo_detalle else base


def marcar_avisado(db: Session, usuario: Usuario, encargo_id: int) -> Encargo:
    """El personal ya le avisó al cliente del estado actual. No hace commit."""
    _validar_rol(usuario)
    e = obtener(db, usuario.negocio_id, encargo_id)
    e.avisado_at, e.avisado_estado, e.avisado_por = _ahora(), e.estado, "personal"
    e.aviso_texto = e.aviso_error = None
    db.flush()
    return e


def falta_avisar(e: Encargo) -> bool:
    """Se pidió, llegó o no se pudo encargar, y todavía no se le dice al cliente."""
    return e.estado in PLANTILLA_DE and e.avisado_estado != e.estado


def avisar(db: Session, e: Encargo) -> bool:
    """Le manda al cliente por WhatsApp el aviso del estado actual (si hace
    falta). Si no se puede, deja el motivo en `aviso_error` para que el
    personal le avise. Regresa si se envió. No hace commit."""
    if not falta_avisar(e):
        return False
    telefono = whatsapp.numero(e.telefono)
    if telefono is None:
        e.aviso_error = "El cliente no dejó un teléfono válido para WhatsApp"
    elif not whatsapp.configurado():
        e.aviso_error = "WhatsApp todavía no está configurado"
    else:
        plantilla = whatsapp.PLANTILLAS[PLANTILLA_DE[e.estado]]
        negocio = db.get(Negocio, e.negocio_id)
        cantidad = f"{e.cantidad.normalize():f} " if e.cantidad != 1 else ""
        parametros = [e.cliente, f"{cantidad}{e.descripcion}"]
        if e.estado == EstadoEncargo.NO_DISPONIBLE:
            parametros.append(MOTIVOS.get(e.motivo_no_disponible, MOTIVOS["otro"])[1])
        parametros.append(negocio.nombre)
        try:
            whatsapp.cliente().enviar_plantilla(telefono, plantilla, parametros)
        except whatsapp.ErrorWhatsApp as err:
            e.aviso_error = err.mensaje
        else:
            e.avisado_at, e.avisado_estado, e.avisado_por = _ahora(), e.estado, "whatsapp"
            e.aviso_texto, e.aviso_error = whatsapp.texto(plantilla, parametros), None
    db.flush()
    return e.aviso_error is None


def avisar_de_pedido(db: Session, pedido_id: int) -> None:
    """Avisa a los clientes de los encargos que quedaron en un pedido recién enviado. No hace commit."""
    for e in db.scalars(select(Encargo).where(Encargo.pedido_id == pedido_id)):
        avisar(db, e)


def listar(db: Session, negocio_id: int, abiertos: bool = True, limite: int = 200) -> list[Encargo]:
    stmt = select(Encargo).where(Encargo.negocio_id == negocio_id)
    if abiertos:
        stmt = stmt.where(Encargo.estado.in_(ABIERTOS))
    return list(db.scalars(stmt.order_by(Encargo.created_at.desc(), Encargo.id.desc()).limit(limite)))


def contar_por_pedir(db: Session, negocio_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Encargo).where(
        Encargo.negocio_id == negocio_id, Encargo.estado == EstadoEncargo.POR_PEDIR)) or 0


def por_pedir_con_producto(db: Session, negocio_id: int) -> dict[int, list[Encargo]]:
    """Encargos por pedir de productos del catálogo, por producto (para Pedidos)."""
    resultado: dict[int, list[Encargo]] = {}
    for e in db.scalars(select(Encargo).where(
            Encargo.negocio_id == negocio_id, Encargo.estado == EstadoEncargo.POR_PEDIR,
            Encargo.producto_id.is_not(None)).order_by(Encargo.id)):
        resultado.setdefault(e.producto_id, []).append(e)
    return resultado


def al_enviar_pedido(db: Session, pedido: Pedido) -> int:
    """Los encargos por pedir de los productos del pedido pasan a "Pedido al
    proveedor" (ligados al pedido). Regresa cuántos. No hace commit."""
    productos = {r.producto_id for r in pedido.renglones if r.cantidad > 0}
    n = 0
    for e in db.scalars(select(Encargo).where(
            Encargo.negocio_id == pedido.negocio_id, Encargo.estado == EstadoEncargo.POR_PEDIR,
            Encargo.producto_id.in_(productos))):
        e.estado, e.pedido_id = EstadoEncargo.PEDIDO, pedido.id
        n += 1
    db.flush()
    return n


TEXTOS = {
    EstadoEncargo.POR_PEDIR: "Por pedir",
    EstadoEncargo.PEDIDO: "Pedido al proveedor",
    EstadoEncargo.LLEGO: "Llegó",
    EstadoEncargo.NO_DISPONIBLE: "No se pudo encargar",
    EstadoEncargo.ENTREGADO: "Entregado",
    EstadoEncargo.CANCELADO: "Cancelado",
}


def texto_estado(estado: EstadoEncargo) -> str:
    return TEXTOS[estado]
