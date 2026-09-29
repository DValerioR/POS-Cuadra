"""Consultas que puede usar el asistente de IA. Son la ÚNICA forma en que ve
los datos: todas son de solo lectura, filtran por negocio y ponen tope al
número de resultados. Los números (totales, sumas, existencias) los calcula
la base de datos aquí, nunca la IA.

Cada función recibe la sesión, el negocio y los parámetros que eligió el
asistente (ya validados por el esquema de la herramienta) y regresa un dict
que se le manda como resultado.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AvisoInventario, Caja, Categoria, Devolucion, Entrada, EstadoAviso, EstadoSolicitud, EstadoVenta, Lote,
    MetodoPago, Pago, Producto, Proveedor, SolicitudDevolucion, Turno, Usuario, Venta, VentaEnEspera, VentaRenglon,
)
from app.services import inventario

MAXIMO = 50


class ConsultaInvalida(Exception):
    """Parámetros que no tienen sentido; se le explica al asistente."""


def _zona() -> ZoneInfo:
    return ZoneInfo(settings.zona_horaria)


def hoy() -> date:
    return datetime.now(_zona()).date()


def _fecha(texto: str | None, nombre: str) -> date:
    if not texto:
        raise ConsultaInvalida(f"Falta {nombre} (AAAA-MM-DD)")
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise ConsultaInvalida(f"{nombre} debe ser una fecha AAAA-MM-DD, no '{texto}'")


def _rango(desde: str | None, hasta: str | None) -> tuple[date, date, datetime, datetime]:
    d = _fecha(desde, "desde")
    h = _fecha(hasta or desde, "hasta")
    if h < d:
        raise ConsultaInvalida("hasta no puede ser antes que desde")
    if (h - d).days > 731:
        raise ConsultaInvalida("El periodo máximo es de 2 años")
    zona = _zona()
    return d, h, datetime.combine(d, time.min, tzinfo=zona), datetime.combine(h + timedelta(days=1), time.min, tzinfo=zona)


def _dinero(valor) -> str:
    return f"{Decimal(valor or 0):.2f}"


def _cantidad(valor) -> str:
    return f"{Decimal(valor or 0).normalize():f}"


def _limite(n: int | None, defecto: int = 20) -> int:
    return max(1, min(int(n or defecto), MAXIMO))


def _dia_local(columna):
    return func.date(func.timezone(settings.zona_horaria, columna))


# --- Ventas -----------------------------------------------------------------------

def resumen_ventas(db: Session, negocio_id: int, desde: str, hasta: str | None = None, agrupar_por: str | None = None) -> dict:
    d, h, inicio, fin = _rango(desde, hasta)
    filtro = and_(Venta.negocio_id == negocio_id, Venta.created_at >= inicio, Venta.created_at < fin)
    ventas, vendido = db.execute(select(func.count(), func.coalesce(func.sum(Venta.total), 0)).where(filtro)).one()
    canceladas = db.scalar(select(func.count()).where(filtro, Venta.estado == EstadoVenta.CANCELADA))
    pagos = dict(db.execute(
        select(Pago.metodo, func.sum(Pago.monto)).join(Venta, Venta.id == Pago.venta_id).where(filtro).group_by(Pago.metodo)
    ).all())
    devuelto = db.execute(select(
        func.coalesce(func.sum(Devolucion.efectivo), 0), func.coalesce(func.sum(Devolucion.tarjeta), 0),
    ).where(Devolucion.negocio_id == negocio_id, Devolucion.created_at >= inicio, Devolucion.created_at < fin)).one()
    resultado = {
        "periodo": f"{d} a {h}",
        "numero_de_ventas": ventas,
        "ventas_canceladas": canceladas,
        "vendido_con_impuestos": _dinero(vendido),
        "cobrado_en_efectivo": _dinero(pagos.get(MetodoPago.EFECTIVO)),
        "cobrado_con_tarjeta": _dinero(pagos.get(MetodoPago.TARJETA)),
        "regresado_en_devoluciones_efectivo": _dinero(devuelto[0]),
        "regresado_en_devoluciones_tarjeta": _dinero(devuelto[1]),
        "neto_cobrado": _dinero(
            Decimal(pagos.get(MetodoPago.EFECTIVO) or 0) + Decimal(pagos.get(MetodoPago.TARJETA) or 0) - devuelto[0] - devuelto[1]
        ),
        "nota": "vendido_con_impuestos incluye ventas que después se cancelaron; neto_cobrado ya resta lo regresado.",
    }
    if agrupar_por:
        if agrupar_por == "dia":
            clave = _dia_local(Venta.created_at)
            filas = db.execute(select(clave, func.count(), func.sum(Venta.total)).where(filtro).group_by(clave).order_by(clave)).all()
        elif agrupar_por == "caja":
            filas = db.execute(select(Caja.nombre, func.count(), func.sum(Venta.total)).join(Caja, Caja.id == Venta.caja_id)
                               .where(filtro).group_by(Caja.nombre).order_by(Caja.nombre)).all()
        elif agrupar_por == "cajero":
            filas = db.execute(select(Usuario.nombre_completo, func.count(), func.sum(Venta.total)).join(Usuario, Usuario.id == Venta.usuario_id)
                               .where(filtro).group_by(Usuario.nombre_completo).order_by(Usuario.nombre_completo)).all()
        elif agrupar_por == "hora":
            clave = func.extract("hour", func.timezone(settings.zona_horaria, Venta.created_at))
            filas = db.execute(select(clave, func.count(), func.sum(Venta.total)).where(filtro).group_by(clave).order_by(clave)).all()
        else:
            raise ConsultaInvalida("agrupar_por debe ser dia, caja, cajero u hora")
        resultado["grupos"] = [{"grupo": str(g if not isinstance(g, Decimal) else int(g)), "ventas": n, "vendido": _dinero(t)} for g, n, t in filas]
    return resultado


def productos_mas_vendidos(db: Session, negocio_id: int, desde: str, hasta: str | None = None,
                           orden: str = "piezas", limite: int | None = None) -> dict:
    d, h, inicio, fin = _rango(desde, hasta)
    piezas = func.sum(VentaRenglon.cantidad)
    importe = func.sum(VentaRenglon.importe)
    filas = db.execute(
        select(VentaRenglon.producto_id, func.max(VentaRenglon.nombre), piezas, importe)
        .join(Venta, Venta.id == VentaRenglon.venta_id)
        .where(Venta.negocio_id == negocio_id, Venta.created_at >= inicio, Venta.created_at < fin,
               Venta.estado != EstadoVenta.CANCELADA)
        .group_by(VentaRenglon.producto_id)
        .order_by((importe if orden == "importe" else piezas).desc())
        .limit(_limite(limite))
    ).all()
    return {"periodo": f"{d} a {h}", "orden": orden, "productos": [
        {"producto_id": pid, "nombre": nombre, "piezas": _cantidad(p), "vendido": _dinero(i)} for pid, nombre, p, i in filas
    ], "nota": "No incluye ventas canceladas."}


def productos_sin_movimiento(db: Session, negocio_id: int, dias: int = 90, limite: int | None = None) -> dict:
    if not 7 <= int(dias) <= 730:
        raise ConsultaInvalida("dias debe estar entre 7 y 730")
    desde = datetime.now(_zona()) - timedelta(days=int(dias))
    vendidos = select(VentaRenglon.producto_id).join(Venta, Venta.id == VentaRenglon.venta_id).where(
        Venta.negocio_id == negocio_id, Venta.created_at >= desde)
    existencia = func.sum(Lote.cantidad)
    filas = db.execute(
        select(Producto.id, Producto.nombre, existencia, Producto.costo)
        .join(Lote, Lote.producto_id == Producto.id)
        .where(Producto.negocio_id == negocio_id, Producto.activo.is_(True), Producto.id.not_in(vendidos))
        .group_by(Producto.id).having(existencia > 0)
        .order_by((existencia * func.coalesce(Producto.costo, 0)).desc(), existencia.desc())
        .limit(_limite(limite))
    ).all()
    return {"sin_ventas_en_dias": int(dias), "productos": [
        {"producto_id": pid, "nombre": n, "existencia": _cantidad(e),
         "valor_al_costo": _dinero(e * c) if c is not None else "sin costo"} for pid, n, e, c in filas
    ], "nota": "Ordenados por valor detenido al costo."}


# --- Productos e inventario ---------------------------------------------------------

def buscar_productos(db: Session, negocio_id: int, texto: str, limite: int | None = None) -> dict:
    texto = (texto or "").strip()
    if len(texto) < 2:
        raise ConsultaInvalida("Escribe al menos 2 letras del nombre o el código")
    por_nombre = and_(*(func.unaccent(Producto.nombre).ilike(func.unaccent(f"%{p}%")) for p in texto.split()))
    productos = db.scalars(
        select(Producto).where(Producto.negocio_id == negocio_id, or_(por_nombre, Producto.clave == texto))
        .order_by(Producto.activo.desc(), Producto.nombre).limit(_limite(limite, 10))
    ).all()
    categorias = {c.id: c for c in db.scalars(select(Categoria).where(Categoria.negocio_id == negocio_id))}
    salida = []
    for p in productos:
        c = categorias.get(p.categoria_id)
        salida.append({
            "producto_id": p.id, "nombre": p.nombre, "clave": p.clave, "activo": p.activo,
            "precio_venta": _dinero(p.precio_venta) if p.precio_venta is not None else "sin precio",
            "costo_sin_impuestos": _dinero(p.costo) if p.costo is not None else "sin costo",
            "iva": f"{p.iva_porcentaje.normalize():f}%", "ieps": f"{p.ieps_porcentaje.normalize():f}%",
            "categoria": c.nombre if c else None,
            "margen_de_la_categoria": f"{c.margen_porcentaje.normalize():f}%" if c and c.margen_porcentaje is not None else None,
            "existencia": _cantidad(inventario.existencia_total(db, p.id)),
            "por_revisar": p.motivo_revision if p.requiere_revision else None,
        })
    return {"productos": salida}


def existencia_producto(db: Session, negocio_id: int, producto_id: int) -> dict:
    p = db.get(Producto, int(producto_id))
    if p is None or p.negocio_id != negocio_id:
        raise ConsultaInvalida("No existe ese producto; búscalo primero con buscar_productos")
    lotes = db.scalars(select(Lote).where(Lote.producto_id == p.id, Lote.cantidad != 0)
                       .order_by(Lote.caducidad.asc().nulls_last())).all()
    return {"producto": p.nombre, "existencia_total": _cantidad(sum((l.cantidad for l in lotes), Decimal(0))), "lotes": [
        {"lote": l.numero_lote, "caducidad": str(l.caducidad) if l.caducidad else "sin caducidad registrada",
         "piezas": _cantidad(l.cantidad)} for l in lotes
    ]}


def por_caducar(db: Session, negocio_id: int, meses: int = 6) -> dict:
    meses = int(meses)
    if not 0 <= meses <= 24:
        raise ConsultaInvalida("meses debe estar entre 0 y 24")
    h = hoy()
    lotes = inventario.por_caducar(db, negocio_id, h, h + timedelta(days=30 * meses))
    return {"hasta_meses": meses, "total_de_lotes": len(lotes), "lotes": [
        {"nombre": l["nombre"], "lote": l["numero_lote"], "caducidad": str(l["caducidad"]), "piezas": _cantidad(l["cantidad"]),
         "dias_para_caducar": l["dias"]} for l in lotes[:MAXIMO]
    ]}


def estado_del_catalogo(db: Session, negocio_id: int) -> dict:
    base = select(func.count()).select_from(Producto).where(Producto.negocio_id == negocio_id, Producto.activo.is_(True))
    categorias = db.execute(
        select(Categoria.nombre, Categoria.margen_porcentaje, func.count(Producto.id))
        .outerjoin(Producto, Producto.categoria_id == Categoria.id)
        .where(Categoria.negocio_id == negocio_id).group_by(Categoria.id).order_by(Categoria.nombre)
    ).all()
    return {
        "productos_activos": db.scalar(base),
        "sin_precio": db.scalar(base.where(Producto.precio_venta.is_(None))),
        "sin_costo": db.scalar(base.where(Producto.costo.is_(None))),
        "sin_categoria": db.scalar(base.where(Producto.categoria_id.is_(None))),
        "marcados_para_revisar": db.scalar(base.where(Producto.requiere_revision.is_(True))),
        "con_iva": db.scalar(base.where(Producto.iva_porcentaje > 0)),
        "categorias": [{"nombre": n, "margen": f"{m.normalize():f}%" if m is not None else "sin margen", "productos": c}
                       for n, m, c in categorias],
    }


# --- Caja, devoluciones, entradas y pendientes ---------------------------------------------

def cortes_de_caja(db: Session, negocio_id: int, desde: str, hasta: str | None = None) -> dict:
    d, h, inicio, fin = _rango(desde, hasta)
    filas = db.execute(
        select(Turno, Caja.nombre, Usuario.nombre_completo)
        .join(Caja, Caja.id == Turno.caja_id).join(Usuario, Usuario.id == Turno.abierto_por_id)
        .where(Turno.negocio_id == negocio_id, Turno.abierto_en >= inicio, Turno.abierto_en < fin)
        .order_by(Turno.abierto_en).limit(MAXIMO)
    ).all()
    zona = _zona()
    return {"periodo": f"{d} a {h}", "turnos": [
        {"caja": caja, "abrio": quien, "tipo": t.tipo.value, "abierto": t.abierto_en.astimezone(zona).strftime("%Y-%m-%d %H:%M"),
         "cerrado": t.cerrado_en.astimezone(zona).strftime("%Y-%m-%d %H:%M") if t.cerrado_en else "sigue abierto",
         "efectivo_esperado": _dinero(t.efectivo_esperado) if t.cerrado_en else None,
         "efectivo_contado": _dinero(t.efectivo_contado) if t.cerrado_en else None,
         "diferencia_efectivo": _dinero(t.diferencia_efectivo) if t.cerrado_en else None,
         "diferencia_tarjeta": _dinero(t.diferencia_tarjeta) if t.cerrado_en else None,
         "notas": t.notas_cierre}
        for t, caja, quien in filas
    ], "nota": "Diferencia negativa = faltó dinero; positiva = sobró."}


def devoluciones(db: Session, negocio_id: int, desde: str, hasta: str | None = None) -> dict:
    d, h, inicio, fin = _rango(desde, hasta)
    filas = db.execute(
        select(Devolucion, Venta.folio, Usuario.nombre_completo)
        .join(Venta, Venta.id == Devolucion.venta_id).join(Usuario, Usuario.id == Devolucion.usuario_id)
        .where(Devolucion.negocio_id == negocio_id, Devolucion.created_at >= inicio, Devolucion.created_at < fin)
        .order_by(Devolucion.id).limit(MAXIMO)
    ).all()
    return {"periodo": f"{d} a {h}", "devoluciones": [
        {"tipo": dev.tipo.value, "folio_venta": folio, "motivo": dev.motivo, "valor": _dinero(dev.total),
         "efectivo_regresado": _dinero(dev.efectivo), "tarjeta_regresada": _dinero(dev.tarjeta), "hizo_o_autorizo": quien}
        for dev, folio, quien in filas
    ]}


def entradas_de_mercancia(db: Session, negocio_id: int, desde: str, hasta: str | None = None) -> dict:
    d, h, _, _ = _rango(desde, hasta)
    filas = db.execute(
        select(Entrada, Proveedor.nombre).join(Proveedor, Proveedor.id == Entrada.proveedor_id)
        .where(Entrada.negocio_id == negocio_id, Entrada.fecha_recepcion >= d, Entrada.fecha_recepcion <= h)
        .order_by(Entrada.fecha_recepcion, Entrada.id).limit(MAXIMO)
    ).all()
    return {"periodo": f"{d} a {h}", "entradas": [
        {"proveedor": prov, "folio": e.folio, "recibida": str(e.fecha_recepcion), "subtotal_sin_impuestos": _dinero(e.subtotal),
         "productos": len(e.renglones), "piezas": _cantidad(sum((r.piezas for r in e.renglones), Decimal(0))),
         "precios_cambiados": sum(1 for r in e.renglones if r.precio_nuevo is not None)}
        for e, prov in filas
    ]}


def pendientes(db: Session, negocio_id: int) -> dict:
    return {
        "devoluciones_por_autorizar": db.scalar(select(func.count()).select_from(SolicitudDevolucion).where(
            SolicitudDevolucion.negocio_id == negocio_id, SolicitudDevolucion.estado == EstadoSolicitud.PENDIENTE)),
        "ventas_sin_existencia_por_revisar": db.scalar(select(func.count()).select_from(AvisoInventario).where(
            AvisoInventario.negocio_id == negocio_id, AvisoInventario.estado == EstadoAviso.PENDIENTE)),
        "ventas_guardadas_en_espera": db.scalar(select(func.count()).select_from(VentaEnEspera).where(
            VentaEnEspera.negocio_id == negocio_id)),
        "turnos_abiertos": [c for (c,) in db.execute(select(Caja.nombre).join(Turno, Turno.caja_id == Caja.id).where(
            Turno.negocio_id == negocio_id, Turno.cerrado_en.is_(None)))],
        "productos_caducados_con_existencia": len(inventario.por_caducar(db, negocio_id, hoy(), hoy() - timedelta(days=1))),
    }


CONSULTAS = {
    "resumen_ventas": resumen_ventas,
    "productos_mas_vendidos": productos_mas_vendidos,
    "productos_sin_movimiento": productos_sin_movimiento,
    "buscar_productos": buscar_productos,
    "existencia_producto": existencia_producto,
    "por_caducar": por_caducar,
    "estado_del_catalogo": estado_del_catalogo,
    "cortes_de_caja": cortes_de_caja,
    "devoluciones": devoluciones,
    "entradas_de_mercancia": entradas_de_mercancia,
    "pendientes": pendientes,
}
