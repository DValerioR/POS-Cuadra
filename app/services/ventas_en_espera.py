"""Ventas en espera: guardar una venta a medias para atender a otro cliente.

Máximo 5 por caja. Se guardan en el servidor (no se pierden si se cierra el
navegador) y, mientras haya alguna, no se puede hacer el corte de esa caja.
Retomar una venta la saca de la lista: vuelve a la pantalla y se cobra como
cualquier otra, revisando existencia y precios en ese momento.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Caja, Producto, Usuario, VentaEnEspera
from app.services import turnos
from app.services.errores import NoEncontrado, OperacionInvalida

MAXIMO_POR_CAJA = 5
CENTAVO = Decimal("0.01")


@dataclass
class RenglonEnEspera:
    producto_id: int
    cantidad: Decimal
    lote_id: int | None = None
    caducidad_mes: str | None = None  # "2027-03", como se captura en la pantalla
    numero_lote: str | None = None


def contar(db: Session, caja_id: int) -> int:
    return db.scalar(select(func.count()).select_from(VentaEnEspera).where(VentaEnEspera.caja_id == caja_id))


def listar(db: Session, usuario: Usuario, caja_id: int) -> list[VentaEnEspera]:
    turnos.obtener_caja(db, usuario.negocio_id, caja_id)
    return db.scalars(
        select(VentaEnEspera).where(VentaEnEspera.caja_id == caja_id).order_by(VentaEnEspera.id)
    ).all()


def guardar(
    db: Session, usuario: Usuario, caja_id: int, renglones: list[RenglonEnEspera], nota: str | None = None,
) -> VentaEnEspera:
    """No hace commit."""
    turnos._validar_rol(usuario)
    caja = turnos.obtener_caja(db, usuario.negocio_id, caja_id)
    if not renglones:
        raise OperacionInvalida("No hay productos que guardar")
    # Bloquea la caja para que dos pestañas no pasen del máximo al mismo tiempo.
    db.execute(select(Caja.id).where(Caja.id == caja.id).with_for_update())
    if contar(db, caja.id) >= MAXIMO_POR_CAJA:
        raise OperacionInvalida(
            f"Ya hay {MAXIMO_POR_CAJA} ventas guardadas en esta caja; cobra o borra alguna antes de guardar otra"
        )

    productos = {
        p.id: p for p in db.scalars(select(Producto).where(
            Producto.negocio_id == usuario.negocio_id, Producto.id.in_({r.producto_id for r in renglones}),
        ))
    }
    total = Decimal(0)
    articulos = Decimal(0)
    guardados = []
    for r in renglones:
        producto = productos.get(r.producto_id)
        if producto is None:
            raise NoEncontrado("Producto no encontrado")
        if r.cantidad <= 0:
            raise OperacionInvalida("La cantidad debe ser mayor que cero")
        if r.caducidad_mes:
            try:
                date.fromisoformat(f"{r.caducidad_mes}-01")
            except ValueError:
                raise OperacionInvalida("La caducidad debe ser año y mes, por ejemplo 2027-03")
        total += (producto.precio_venta or 0) * r.cantidad
        articulos += r.cantidad
        guardados.append({
            "producto_id": r.producto_id, "cantidad": str(r.cantidad), "lote_id": r.lote_id,
            "caducidad_mes": r.caducidad_mes or None, "numero_lote": (r.numero_lote or "").strip() or None,
        })

    espera = VentaEnEspera(
        negocio_id=usuario.negocio_id, caja_id=caja.id, usuario_id=usuario.id,
        nota=(nota or "").strip() or None, renglones=guardados,
        articulos=articulos, total=total.quantize(CENTAVO),
    )
    db.add(espera)
    db.flush()
    return espera


def _obtener(db: Session, usuario: Usuario, espera_id: int) -> VentaEnEspera:
    espera = db.scalar(select(VentaEnEspera).where(
        VentaEnEspera.id == espera_id, VentaEnEspera.negocio_id == usuario.negocio_id,
    ).with_for_update())
    if espera is None:
        raise NoEncontrado("Esa venta guardada ya no existe (quizá ya la retomaron)")
    return espera


def retomar(db: Session, usuario: Usuario, espera_id: int) -> VentaEnEspera:
    """La saca de la lista y la regresa para cargarla en la pantalla. No hace commit."""
    turnos._validar_rol(usuario)
    espera = _obtener(db, usuario, espera_id)
    db.delete(espera)
    db.flush()
    return espera


def borrar(db: Session, usuario: Usuario, espera_id: int) -> None:
    """No hace commit."""
    turnos._validar_rol(usuario)
    db.delete(_obtener(db, usuario, espera_id))
    db.flush()
