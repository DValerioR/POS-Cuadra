"""Ofertas que se aplican solas al vender.

Las crea un administrador (desde una sugerencia del asistente o a mano), con
fecha de fin obligatoria. Al crearla se revisa lo mismo que en las
sugerencias (services/ofertas.py): nunca debajo del precio mínimo (el costo
si el producto caduca pronto, costo + 10% si no, con impuestos), ni arriba
del precio normal; a productos con receta solo descuento o precio especial.
Un producto está en una sola oferta activa a la vez (como principal o como
el segundo de un paquete).

Al vender, `calcular` dice cuánto se descuenta en cada renglón. Lo usan el
cobro (ventas.registrar_venta) y la cotización de la pantalla de venta, así
que lo que se ve es exactamente lo que se cobra. El precio del renglón sigue
siendo el normal; el descuento va aparte y el importe es lo que se cobró.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.asistente.consultas import _zona, hoy
from app.models import Lote, Negocio, Oferta, Producto, RolUsuario, Usuario
from app.services import ofertas as sugerencias
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso

CENTAVO = Decimal("0.01")
MAXIMO_DIAS = 180
PIEZAS_POR = {"2x1": (2, 1), "3x2": (3, 2)}  # lleva, paga


def _solo_admin(usuario: Usuario) -> None:
    if usuario.rol != RolUsuario.ADMIN:
        raise SinPermiso("Solo un administrador puede poner o quitar ofertas")


def _producto(db: Session, negocio_id: int, producto_id: int) -> Producto:
    p = db.get(Producto, producto_id)
    if p is None or p.negocio_id != negocio_id:
        raise NoEncontrado("Producto no encontrado")
    if not p.activo:
        raise OperacionInvalida(f"{p.nombre} está desactivado")
    if not p.precio_venta:
        raise OperacionInvalida(f"{p.nombre} no tiene precio de venta")
    if not p.costo or not p.factor_conversion:
        raise OperacionInvalida(f"{p.nombre} no tiene costo: sin él no se sabe cuánto se puede bajar sin perder")
    return p


def _caduca_pronto(db: Session, producto_id: int) -> bool:
    h = hoy()
    return bool(db.scalar(select(func.count()).select_from(Lote).where(
        Lote.producto_id == producto_id, Lote.cantidad > 0, Lote.caducidad >= h,
        Lote.caducidad <= sugerencias._mas_meses(h, sugerencias.CADUCA_MESES))))


def precio_minimo(db: Session, p: Producto) -> Decimal:
    paso = db.get(Negocio, p.negocio_id).redondeo_precio_venta
    return sugerencias.precio_minimo(p, Decimal(p.costo) / Decimal(p.factor_conversion), _caduca_pronto(db, p.id), paso)


def _dinero(valor: Decimal) -> str:
    return f"${valor:,.2f}"


def activas(db: Session, negocio_id: int, dia: date | None = None) -> list[Oferta]:
    dia = dia or hoy()
    return list(db.scalars(select(Oferta).where(
        Oferta.negocio_id == negocio_id, Oferta.activa.is_(True), Oferta.inicio <= dia, Oferta.fin >= dia,
    ).order_by(Oferta.fin, Oferta.id)))


def crear(db: Session, usuario: Usuario, producto_id: int, tipo: str, precio: Decimal | None, fin: date,
          paquete_con_id: int | None = None, motivo: str | None = None, origen: str = "manual") -> Oferta:
    """Crea la oferta desde hoy hasta `fin`. No hace commit."""
    _solo_admin(usuario)
    if tipo not in sugerencias.TIPOS:
        raise OperacionInvalida("Tipo de oferta no válido")
    h = hoy()
    if fin < h:
        raise OperacionInvalida("La fecha de fin ya pasó")
    if fin > h + timedelta(days=MAXIMO_DIAS):
        raise OperacionInvalida(f"Una oferta puede durar como máximo {MAXIMO_DIAS} días")
    p = _producto(db, usuario.negocio_id, producto_id)
    productos = [p]
    minimo = precio_minimo(db, p)
    normal = Decimal(p.precio_venta)

    if p.requiere_receta and tipo not in ("descuento", "precio_especial"):
        raise OperacionInvalida(f"{p.nombre} requiere receta: solo se le puede poner descuento o precio especial")
    if tipo in ("descuento", "precio_especial"):
        paquete_con_id = None
        if precio is None or precio <= 0:
            raise OperacionInvalida("Indica el precio de oferta")
        precio = Decimal(precio).quantize(CENTAVO)
        if precio >= normal:
            raise OperacionInvalida(f"El precio de oferta debe ser menor que el normal ({_dinero(normal)})")
        if precio < minimo:
            raise OperacionInvalida(f"El precio más bajo permitido para {p.nombre} es {_dinero(minimo)}")
    elif tipo in PIEZAS_POR:
        paquete_con_id, precio = None, None
        lleva, paga = PIEZAS_POR[tipo]
        if normal * paga / lleva < minimo:
            raise OperacionInvalida(f"Con {tipo}, {p.nombre} quedaría en {_dinero(normal * paga / lleva)} por pieza; "
                                    f"lo más bajo permitido es {_dinero(minimo)}")
    else:  # paquete
        if not paquete_con_id or paquete_con_id == p.id:
            raise OperacionInvalida("Elige el otro producto del paquete")
        otro = _producto(db, usuario.negocio_id, paquete_con_id)
        if otro.requiere_receta:
            raise OperacionInvalida(f"{otro.nombre} requiere receta: no puede ir en un paquete")
        productos.append(otro)
        if precio is None or precio <= 0:
            raise OperacionInvalida("Indica el precio del paquete")
        precio = Decimal(precio).quantize(CENTAVO)
        juntos = normal + Decimal(otro.precio_venta)
        minimo += precio_minimo(db, otro)
        if precio >= juntos:
            raise OperacionInvalida(f"El precio del paquete debe ser menor que los dos por separado ({_dinero(juntos)})")
        if precio < minimo:
            raise OperacionInvalida(f"El precio más bajo permitido para el paquete es {_dinero(minimo)}")

    ids = [x.id for x in productos]
    ocupado = db.scalar(select(Oferta).where(
        Oferta.negocio_id == usuario.negocio_id, Oferta.activa.is_(True), Oferta.fin >= h,
        or_(Oferta.producto_id.in_(ids), Oferta.paquete_con_id.in_(ids))).limit(1))
    if ocupado is not None:
        nombre = next(x.nombre for x in productos if x.id in (ocupado.producto_id, ocupado.paquete_con_id))
        raise OperacionInvalida(f"{nombre} ya tiene una oferta activa hasta el {ocupado.fin:%d/%m/%Y}; quítala primero")

    oferta = Oferta(
        negocio_id=usuario.negocio_id, producto_id=p.id, tipo=tipo, precio=precio, paquete_con_id=paquete_con_id,
        inicio=h, fin=fin, activa=True, motivo=(" ".join((motivo or "").split())[:200] or None),
        origen="asistente" if origen == "asistente" else "manual", creada_por_id=usuario.id,
    )
    db.add(oferta)
    db.flush()
    return oferta


def quitar(db: Session, usuario: Usuario, oferta_id: int) -> Oferta:
    """Desactiva la oferta desde este momento. No hace commit."""
    _solo_admin(usuario)
    oferta = db.get(Oferta, oferta_id)
    if oferta is None or oferta.negocio_id != usuario.negocio_id:
        raise NoEncontrado("Oferta no encontrada")
    if not oferta.activa:
        raise OperacionInvalida("Esa oferta ya se había quitado")
    oferta.activa = False
    oferta.quitada_por_id = usuario.id
    oferta.quitada_en = datetime.now(_zona())
    db.flush()
    return oferta


def texto(oferta: Oferta, producto_id: int) -> str:
    """Cómo se llama la oferta en el ticket y en la pantalla de venta."""
    if oferta.tipo in PIEZAS_POR:
        return f"Oferta {oferta.tipo}"
    if oferta.tipo == "paquete":
        otro = oferta.paquete_con if producto_id == oferta.producto_id else oferta.producto
        return f"Paquete con {otro.nombre}"
    if oferta.tipo == "descuento" and oferta.precio and oferta.producto.precio_venta:
        porcentaje = ((1 - oferta.precio / oferta.producto.precio_venta) * 100).quantize(Decimal("1"), ROUND_HALF_UP)
        if porcentaje > 0:
            return f"Descuento {porcentaje}%"
    return "Precio especial" if oferta.tipo == "precio_especial" else "Oferta"


# --- Cálculo al vender -----------------------------------------------------------


@dataclass
class Aplicada:
    descuento: Decimal = Decimal(0)
    oferta: Oferta | None = None
    texto: str | None = None


def _repartir(total: Decimal, pesos: list[Decimal]) -> list[Decimal]:
    """Reparte `total` en proporción a `pesos`, al centavo; el último se queda
    con lo que sobre para que la suma sea exacta."""
    suma = sum(pesos, Decimal(0))
    partes, acumulado = [], Decimal(0)
    for i, peso in enumerate(pesos):
        parte = total - acumulado if i == len(pesos) - 1 else (total * peso / suma).quantize(CENTAVO, ROUND_HALF_UP)
        partes.append(parte)
        acumulado += parte
    return partes


def calcular(db: Session, negocio_id: int, renglones: list[tuple[Producto, Decimal]]) -> list[Aplicada]:
    """Descuento de cada renglón (producto, cantidad) según las ofertas de
    hoy. Las piezas de un mismo producto en varios renglones (lotes
    distintos) se juntan para contar los 2x1, 3x2 y paquetes. Una oferta cuyo
    precio ya no es menor que el normal (porque bajó el precio) no se aplica."""
    resultado = [Aplicada() for _ in renglones]
    if not renglones:
        return resultado
    ids = {p.id for p, _ in renglones}
    ofertas = [o for o in activas(db, negocio_id) if o.producto_id in ids]
    if not ofertas:
        return resultado

    cantidades: dict[int, Decimal] = {}
    precios: dict[int, Decimal] = {}
    for p, cantidad in renglones:
        cantidades[p.id] = cantidades.get(p.id, Decimal(0)) + Decimal(cantidad)
        precios[p.id] = Decimal(p.precio_venta or 0)

    descuentos: dict[int, tuple[Decimal, Oferta]] = {}  # descuento total por producto
    for o in ofertas:
        pid, q, precio = o.producto_id, cantidades[o.producto_id], precios[o.producto_id]
        if o.tipo in ("descuento", "precio_especial"):
            if o.precio is not None and o.precio < precio:
                descuentos[pid] = (((precio - o.precio) * q).quantize(CENTAVO), o)
        elif o.tipo in PIEZAS_POR:
            lleva, paga = PIEZAS_POR[o.tipo]
            grupos = (q / lleva).to_integral_value(rounding=ROUND_FLOOR)
            if grupos > 0:
                descuentos[pid] = ((grupos * (lleva - paga) * precio).quantize(CENTAVO), o)
        elif o.tipo == "paquete" and o.paquete_con_id in cantidades and o.precio is not None:
            otro = o.paquete_con_id
            paquetes = min(q, cantidades[otro]).to_integral_value(rounding=ROUND_FLOOR)
            ahorro = precio + precios[otro] - o.precio
            if paquetes > 0 and ahorro > 0:
                a, b = _repartir((paquetes * ahorro).quantize(CENTAVO), [precio, precios[otro]])
                descuentos[pid] = (a, o)
                descuentos[otro] = (b, o)

    for pid, (total, oferta) in descuentos.items():
        indices = [i for i, (p, _) in enumerate(renglones) if p.id == pid]
        partes = _repartir(total, [Decimal(renglones[i][1]) for i in indices])
        for i, parte in zip(indices, partes):
            resultado[i] = Aplicada(parte, oferta, texto(oferta, pid))
    return resultado


def del_producto(db: Session, negocio_id: int, producto_id: int) -> dict | None:
    """La oferta de hoy de un producto, para mostrarla al consultar precio."""
    for o in activas(db, negocio_id):
        if producto_id in (o.producto_id, o.paquete_con_id):
            return {"texto": texto(o, producto_id), "precio": o.precio if o.tipo != "paquete" else None,
                    "paquete_precio": o.precio if o.tipo == "paquete" else None, "fin": o.fin}
    return None
