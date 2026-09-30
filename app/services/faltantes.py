"""Reporte de faltantes por proveedor, para armar pedidos.

Un producto es faltante si está activo, tiene máximo y su existencia (la del
sistema, contando lotes en negativo) está en su mínimo o por debajo. La
cantidad sugerida es máximo − existencia.

El historial de proveedores de cada producto sale de las entradas de
mercancía (qué proveedor lo surtió, a qué costo por pieza y cuándo), así que
un producto aparece en el reporte de cada proveedor que lo haya surtido. Para
decidir a quién pedirlo se compara el ÚLTIMO costo de cada proveedor (un
precio viejo puede ya no existir). Los productos sin historial salen en todos
los reportes, en una sección aparte.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Entrada, EntradaRenglon, Lote, Producto, Proveedor, Usuario
from app.services.entradas import _proveedor, _validar_rol


def ultimos_costos(db: Session, negocio_id: int, producto_ids: set[int] | None = None) -> dict[int, list[dict]]:
    """{producto_id: [{proveedor_id, proveedor, costo, fecha}, ...]} con la
    última compra a cada proveedor, del más barato al más caro."""
    stmt = (
        select(EntradaRenglon.producto_id, Entrada.proveedor_id, Proveedor.nombre,
               EntradaRenglon.costo_pieza, Entrada.fecha_recepcion)
        .join(Entrada, Entrada.id == EntradaRenglon.entrada_id)
        .join(Proveedor, Proveedor.id == Entrada.proveedor_id)
        .where(Entrada.negocio_id == negocio_id)
        .distinct(EntradaRenglon.producto_id, Entrada.proveedor_id)
        .order_by(EntradaRenglon.producto_id, Entrada.proveedor_id, Entrada.fecha_recepcion.desc(), EntradaRenglon.id.desc())
    )
    if producto_ids is not None:
        stmt = stmt.where(EntradaRenglon.producto_id.in_(producto_ids))
    resultado: dict[int, list[dict]] = {}
    for producto_id, proveedor_id, nombre, costo, fecha in db.execute(stmt):
        resultado.setdefault(producto_id, []).append(
            {"proveedor_id": proveedor_id, "proveedor": nombre, "costo": costo, "fecha": fecha}
        )
    for lista in resultado.values():
        lista.sort(key=lambda x: (x["costo"], -x["fecha"].toordinal()))
    return resultado


def reporte(db: Session, usuario: Usuario, proveedor_id: int) -> dict:
    _validar_rol(usuario)
    proveedor = _proveedor(db, usuario.negocio_id, proveedor_id)

    existencia = (
        select(Lote.producto_id, func.sum(Lote.cantidad).label("existencia"))
        .where(Lote.negocio_id == usuario.negocio_id).group_by(Lote.producto_id).subquery()
    )
    exist = func.coalesce(existencia.c.existencia, 0)
    filas = db.execute(
        select(Producto, exist)
        .outerjoin(existencia, existencia.c.producto_id == Producto.id)
        .where(Producto.negocio_id == usuario.negocio_id, Producto.activo.is_(True), Producto.encargo.is_(False),
               Producto.minimo.is_not(None), Producto.maximo.is_not(None), Producto.maximo > 0,
               exist <= Producto.minimo)
        .order_by(Producto.nombre)
    ).all()
    costos = ultimos_costos(db, usuario.negocio_id, {p.id for p, _ in filas})

    del_proveedor, sin_proveedor = [], []
    for p, e in filas:
        sugerido = max(Decimal(p.maximo) - Decimal(e), Decimal(1))
        base = {"producto_id": p.id, "clave": p.clave, "nombre": p.nombre, "existencia": e,
                "minimo": p.minimo, "maximo": p.maximo, "sugerido": sugerido}
        historial = costos.get(p.id)
        if not historial:
            sin_proveedor.append(base)
            continue
        este = next((h for h in historial if h["proveedor_id"] == proveedor.id), None)
        if este is None:
            continue  # lo surten otros proveedores; sale en sus reportes
        mejor = historial[0]
        otro_mejor = mejor if mejor["proveedor_id"] != proveedor.id and mejor["costo"] < este["costo"] else None
        del_proveedor.append({
            **base,
            "costo": este["costo"], "fecha_costo": este["fecha"],
            "mejor_proveedor": otro_mejor["proveedor"] if otro_mejor else None,
            "mejor_costo": otro_mejor["costo"] if otro_mejor else None,
            "mejor_fecha": otro_mejor["fecha"] if otro_mejor else None,
            "diferencia_porcentaje": (
                ((este["costo"] - otro_mejor["costo"]) / otro_mejor["costo"] * 100).quantize(Decimal("0.1"))
                if otro_mejor and otro_mejor["costo"] else None
            ),
            "proveedores": [{"proveedor": h["proveedor"], "costo": h["costo"], "fecha": h["fecha"]} for h in historial],
        })
    return {
        "proveedor_id": proveedor.id, "proveedor": proveedor.nombre, "fecha": date.today(),
        "del_proveedor": del_proveedor, "sin_proveedor": sin_proveedor,
        "total_estimado": sum((r["costo"] * r["sugerido"] for r in del_proveedor), Decimal(0)).quantize(Decimal("0.01")),
    }
