"""Encargos de clientes: un producto que un cliente pidió en específico.

Flujo: Por pedir -> Pedido al proveedor -> Llegó -> Entregado (o Cancelado).
El personal le avisa al cliente cuando se pidió y cuando llegó ("Ya le
avisé"); el sistema recuerda el último aviso para saber a quién falta avisar.

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

from app.models import Encargo, EstadoEncargo, Pedido, Producto, RolUsuario, Usuario
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso

ROLES = {RolUsuario.ADMIN, RolUsuario.MOSTRADOR, RolUsuario.BODEGA}
ABIERTOS = (EstadoEncargo.POR_PEDIR, EstadoEncargo.PEDIDO, EstadoEncargo.LLEGO)
# A qué estados se puede pasar desde cada uno.
SIGUIENTES = {
    EstadoEncargo.POR_PEDIR: {EstadoEncargo.PEDIDO, EstadoEncargo.CANCELADO},
    EstadoEncargo.PEDIDO: {EstadoEncargo.LLEGO, EstadoEncargo.POR_PEDIR, EstadoEncargo.CANCELADO},
    EstadoEncargo.LLEGO: {EstadoEncargo.ENTREGADO, EstadoEncargo.CANCELADO},
    EstadoEncargo.ENTREGADO: set(),
    EstadoEncargo.CANCELADO: {EstadoEncargo.POR_PEDIR},
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


def cambiar_estado(db: Session, usuario: Usuario, encargo_id: int, estado: EstadoEncargo) -> Encargo:
    """No hace commit."""
    _validar_rol(usuario)
    e = obtener(db, usuario.negocio_id, encargo_id)
    if estado == e.estado:
        return e
    if estado not in SIGUIENTES[e.estado]:
        raise OperacionInvalida(f"Un encargo {texto_estado(e.estado).lower()} no puede pasar a {texto_estado(estado).lower()}")
    e.estado = estado
    if estado == EstadoEncargo.POR_PEDIR:
        e.pedido_id = None
    db.flush()
    return e


def marcar_avisado(db: Session, usuario: Usuario, encargo_id: int) -> Encargo:
    """El personal ya le avisó al cliente del estado actual. No hace commit."""
    _validar_rol(usuario)
    e = obtener(db, usuario.negocio_id, encargo_id)
    e.avisado_at, e.avisado_estado = _ahora(), e.estado
    db.flush()
    return e


def falta_avisar(e: Encargo) -> bool:
    """Se pidió o llegó y todavía no se le dice al cliente."""
    return e.estado in (EstadoEncargo.PEDIDO, EstadoEncargo.LLEGO) and e.avisado_estado != e.estado


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
    EstadoEncargo.ENTREGADO: "Entregado",
    EstadoEncargo.CANCELADO: "Cancelado",
}


def texto_estado(estado: EstadoEncargo) -> str:
    return TEXTOS[estado]
