"""Pedidos a proveedores.

Flujo: se elige el proveedor y se cargan sus faltantes (los del reporte de
faltantes) con la cantidad sugerida o la del asistente; se ajusta a mano y se
guarda como borrador. Al mandarlo (por teléfono, WhatsApp, portal o con el
agente) se marca "enviado". Cuando llega la mercancía, la entrada se liga al
pedido (desde la entrada o desde el pedido) y se compara lo pedido contra lo
que llegó: piezas que faltaron o sobraron, productos que llegaron sin pedirse
y cambios de costo. Si llegó todo, el pedido se cierra solo; si no, se cierra
a mano cuando ya no se espera más.

Las cantidades son en piezas (como el inventario y el reporte de faltantes).
El costo esperado es el último costo por pieza con ese proveedor al armar el
pedido (o, si nunca lo ha surtido, el costo del catálogo por pieza).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Entrada, EntradaRenglon, EstadoPedido, Pedido, PedidoEntrada, PedidoRenglon, Producto, Proveedor, Usuario,
)
from app.services import encargos, faltantes, sugerencias_pedido
from app.services.entradas import _proveedor, _validar_rol
from app.services.errores import NoEncontrado, OperacionInvalida


@dataclass
class RenglonPedido:
    producto_id: int
    cantidad: Decimal


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def obtener(db: Session, usuario: Usuario, pedido_id: int) -> Pedido:
    _validar_rol(usuario)
    pedido = db.get(Pedido, pedido_id)
    if pedido is None or pedido.negocio_id != usuario.negocio_id:
        raise NoEncontrado("Pedido no encontrado")
    return pedido


def ya_pedidos(db: Session, negocio_id: int, excluir_pedido_id: int | None = None) -> dict[int, list[dict]]:
    """{producto_id: [{folio, proveedor}]} de los pedidos enviados que todavía
    no se cierran, para no pedir dos veces lo mismo."""
    stmt = (
        select(PedidoRenglon.producto_id, Pedido.folio, Proveedor.nombre)
        .join(Pedido, Pedido.id == PedidoRenglon.pedido_id)
        .join(Proveedor, Proveedor.id == Pedido.proveedor_id)
        .where(Pedido.negocio_id == negocio_id, Pedido.estado == EstadoPedido.ENVIADO)
    )
    if excluir_pedido_id is not None:
        stmt = stmt.where(Pedido.id != excluir_pedido_id)
    resultado: dict[int, list[dict]] = {}
    for producto_id, folio, proveedor in db.execute(stmt):
        resultado.setdefault(producto_id, []).append({"folio": folio, "proveedor": proveedor})
    return resultado


def preparar(db: Session, usuario: Usuario, proveedor_id: int, sugerencias: bool = False) -> dict:
    """Los faltantes del proveedor listos para armar el pedido. Lo que ya está
    en otro pedido enviado viene con cantidad 0 (se puede subir a mano)."""
    r = faltantes.reporte(db, usuario, proveedor_id)
    ia = sugerencias_pedido.sugerir(db, usuario.negocio_id, r["del_proveedor"]) if sugerencias else {}
    pedidos = ya_pedidos(db, usuario.negocio_id)
    renglones = []
    for x in r["del_proveedor"]:
        s = ia.get(x["producto_id"])
        cantidad = Decimal(s["cantidad"]) if s else x["sugerido"]
        otros = pedidos.get(x["producto_id"], [])
        renglones.append({
            "producto_id": x["producto_id"], "clave": x["clave"], "nombre": x["nombre"],
            "existencia": x["existencia"], "minimo": x["minimo"], "maximo": x["maximo"], "sugerido": x["sugerido"],
            "sugerencia_asistente": s["cantidad"] if s else None, "motivo_asistente": s["motivo"] if s else None,
            "costo": x["costo"], "mejor_proveedor": x["mejor_proveedor"], "mejor_costo": x["mejor_costo"],
            "ya_pedido": otros, "cantidad": Decimal(0) if otros else cantidad,
        })
    sin_proveedor = [{**x, "ya_pedido": pedidos.get(x["producto_id"], [])} for x in r["sin_proveedor"]]
    # Encargos de clientes que falta pedir (de cualquier proveedor): se agregan a mano al pedido.
    de_clientes = []
    for pid, lista in encargos.por_pedir_con_producto(db, usuario.negocio_id).items():
        p = db.get(Producto, pid)
        de_clientes.append({"producto_id": pid, "clave": p.clave, "nombre": p.nombre,
                            "cantidad": sum((e.cantidad for e in lista), Decimal(0)),
                            "clientes": [e.cliente for e in lista], "ya_pedido": pedidos.get(pid, [])})
    return {"proveedor_id": r["proveedor_id"], "proveedor": r["proveedor"], "renglones": renglones,
            "sin_proveedor": sin_proveedor, "encargos": sorted(de_clientes, key=lambda x: x["nombre"]),
            "con_sugerencias": bool(sugerencias)}


def _costos_esperados(db: Session, negocio_id: int, proveedor_id: int, productos: dict[int, Producto]) -> dict:
    ultimos = faltantes.ultimos_costos(db, negocio_id, set(productos))
    costos = {}
    for pid, p in productos.items():
        este = next((h for h in ultimos.get(pid, []) if h["proveedor_id"] == proveedor_id), None)
        if este is not None:
            costos[pid] = este["costo"]
        elif p.costo is not None:
            costos[pid] = (Decimal(p.costo) / (p.factor_conversion or 1)).quantize(Decimal("0.0001"))
        else:
            costos[pid] = None
    return costos


def _poner_renglones(db: Session, usuario: Usuario, pedido: Pedido, renglones: list[RenglonPedido]) -> None:
    cantidades: dict[int, Decimal] = {}
    for r in renglones:
        if r.cantidad < 0:
            raise OperacionInvalida("Las cantidades no pueden ser negativas")
        if r.cantidad > 0:
            cantidades[r.producto_id] = cantidades.get(r.producto_id, Decimal(0)) + r.cantidad
    if not cantidades:
        raise OperacionInvalida("El pedido no tiene productos (todas las cantidades están en cero)")
    productos = {}
    for pid in cantidades:
        p = db.get(Producto, pid)
        if p is None or p.negocio_id != usuario.negocio_id:
            raise NoEncontrado("Producto no encontrado")
        if not p.activo:
            raise OperacionInvalida(f"{p.nombre} está desactivado")
        productos[pid] = p
    costos = _costos_esperados(db, usuario.negocio_id, pedido.proveedor_id, productos)
    pedido.renglones.clear()
    db.flush()
    for pid, cantidad in cantidades.items():
        pedido.renglones.append(PedidoRenglon(producto_id=pid, cantidad=cantidad, costo_esperado=costos[pid]))


def crear(db: Session, usuario: Usuario, proveedor_id: int, renglones: list[RenglonPedido],
          notas: str | None = None) -> Pedido:
    """Guarda el pedido como borrador. No hace commit."""
    _validar_rol(usuario)
    proveedor = _proveedor(db, usuario.negocio_id, proveedor_id)
    folio = (db.scalar(select(func.max(Pedido.folio)).where(Pedido.negocio_id == usuario.negocio_id)) or 0) + 1
    pedido = Pedido(negocio_id=usuario.negocio_id, folio=folio, proveedor_id=proveedor.id,
                    notas=(notas or "").strip() or None, usuario_id=usuario.id)
    db.add(pedido)
    db.flush()
    _poner_renglones(db, usuario, pedido, renglones)
    return pedido


def actualizar(db: Session, usuario: Usuario, pedido_id: int, renglones: list[RenglonPedido],
               notas: str | None = None) -> Pedido:
    pedido = obtener(db, usuario, pedido_id)
    if pedido.estado != EstadoPedido.BORRADOR:
        raise OperacionInvalida("Solo se puede cambiar un pedido que no se ha enviado")
    pedido.notas = (notas or "").strip() or None
    _poner_renglones(db, usuario, pedido, renglones)
    return pedido


def enviar(db: Session, usuario: Usuario, pedido_id: int) -> Pedido:
    pedido = obtener(db, usuario, pedido_id)
    if pedido.estado != EstadoPedido.BORRADOR:
        raise OperacionInvalida("El pedido ya se había enviado")
    pedido.estado = EstadoPedido.ENVIADO
    pedido.enviado_at = _ahora()
    encargos.al_enviar_pedido(db, pedido)
    return pedido


def cancelar(db: Session, usuario: Usuario, pedido_id: int) -> Pedido:
    pedido = obtener(db, usuario, pedido_id)
    if pedido.estado not in (EstadoPedido.BORRADOR, EstadoPedido.ENVIADO):
        raise OperacionInvalida("Ese pedido ya está cerrado")
    if _entradas_ligadas(db, pedido):
        raise OperacionInvalida("Ya llegó mercancía de este pedido; ciérralo en lugar de cancelarlo")
    pedido.estado = EstadoPedido.CANCELADO
    pedido.cerrado_at = _ahora()
    return pedido


def cerrar(db: Session, usuario: Usuario, pedido_id: int) -> Pedido:
    """Ya no se espera más mercancía de este pedido (llegó completo o no)."""
    pedido = obtener(db, usuario, pedido_id)
    if pedido.estado != EstadoPedido.ENVIADO:
        raise OperacionInvalida("Solo se cierra un pedido enviado")
    pedido.estado = EstadoPedido.RECIBIDO
    pedido.cerrado_at = _ahora()
    return pedido


def _entradas_ligadas(db: Session, pedido: Pedido) -> list[Entrada]:
    return list(db.scalars(
        select(Entrada).join(PedidoEntrada, PedidoEntrada.entrada_id == Entrada.id)
        .where(PedidoEntrada.pedido_id == pedido.id).order_by(Entrada.fecha_recepcion, Entrada.id)
    ))


def ligar_entrada(db: Session, usuario: Usuario, pedido_id: int, entrada_id: int) -> Pedido:
    """La entrada surte este pedido. Si con ella ya llegó todo, el pedido se
    cierra solo. No hace commit."""
    pedido = obtener(db, usuario, pedido_id)
    entrada = db.get(Entrada, entrada_id)
    if entrada is None or entrada.negocio_id != usuario.negocio_id:
        raise NoEncontrado("Entrada no encontrada")
    if pedido.estado != EstadoPedido.ENVIADO:
        raise OperacionInvalida(f"El pedido {pedido.folio} no está esperando mercancía")
    if entrada.proveedor_id != pedido.proveedor_id:
        raise OperacionInvalida("La factura es de otro proveedor")
    if db.scalar(select(PedidoEntrada.id).where(PedidoEntrada.entrada_id == entrada.id)):
        raise OperacionInvalida(f"La factura {entrada.folio} ya está ligada a un pedido")
    db.add(PedidoEntrada(pedido_id=pedido.id, entrada_id=entrada.id))
    db.flush()
    if all(c["estado"] in ("completo", "de_mas") for c in comparar(db, pedido)["renglones"] if c["pedidas"]):
        pedido.estado = EstadoPedido.RECIBIDO
        pedido.cerrado_at = _ahora()
    return pedido


def comparar(db: Session, pedido: Pedido) -> dict:
    """Lo pedido contra lo que llegó en las entradas ligadas, por producto."""
    llegadas: dict[int, dict] = {}
    for producto_id, piezas, importe in db.execute(
        select(EntradaRenglon.producto_id, func.sum(EntradaRenglon.piezas),
               func.sum(EntradaRenglon.piezas * EntradaRenglon.costo_pieza))
        .join(PedidoEntrada, PedidoEntrada.entrada_id == EntradaRenglon.entrada_id)
        .where(PedidoEntrada.pedido_id == pedido.id)
        .group_by(EntradaRenglon.producto_id)
    ):
        llegadas[producto_id] = {"piezas": Decimal(piezas), "costo": (Decimal(importe) / piezas).quantize(Decimal("0.0001"))
                                 if piezas else None}
    pedidos = {r.producto_id: r for r in pedido.renglones}
    ids = set(pedidos) | set(llegadas)
    nombres = dict(db.execute(select(Producto.id, Producto.nombre).where(Producto.id.in_(ids))).all()) if ids else {}
    filas = []
    for pid in ids:
        r = pedidos.get(pid)
        pedidas = r.cantidad if r else Decimal(0)
        llego = llegadas.get(pid, {"piezas": Decimal(0), "costo": None})
        if not r:
            estado = "no_pedido"
        elif llego["piezas"] == 0:
            estado = "no_llego"
        elif llego["piezas"] < pedidas:
            estado = "incompleto"
        elif llego["piezas"] > pedidas:
            estado = "de_mas"
        else:
            estado = "completo"
        esperado = r.costo_esperado if r else None
        cambio = None
        if esperado and llego["costo"] is not None and llego["costo"] != esperado:
            cambio = ((llego["costo"] - esperado) / esperado * 100).quantize(Decimal("0.1"))
        filas.append({
            "producto_id": pid, "nombre": nombres.get(pid, ""), "pedidas": pedidas, "llegaron": llego["piezas"],
            "faltan": max(pedidas - llego["piezas"], Decimal(0)), "estado": estado,
            "costo_esperado": esperado, "costo_real": llego["costo"], "cambio_costo_porcentaje": cambio,
        })
    orden = {"no_llego": 0, "incompleto": 1, "de_mas": 2, "no_pedido": 3, "completo": 4}
    filas.sort(key=lambda f: (orden[f["estado"]], f["nombre"]))
    return {
        "renglones": filas,
        "faltantes": sum(1 for f in filas if f["estado"] in ("no_llego", "incompleto")),
        "cambios_de_costo": sum(1 for f in filas if f["cambio_costo_porcentaje"] is not None),
        "no_pedidos": sum(1 for f in filas if f["estado"] == "no_pedido"),
    }


def _resumen(db: Session, pedido: Pedido) -> dict:
    return {
        "id": pedido.id, "folio": pedido.folio, "proveedor_id": pedido.proveedor_id,
        "proveedor": pedido.proveedor.nombre, "estado": pedido.estado.value, "notas": pedido.notas,
        "productos": len(pedido.renglones), "piezas": sum((r.cantidad for r in pedido.renglones), Decimal(0)),
        "total_estimado": sum((r.cantidad * r.costo_esperado for r in pedido.renglones if r.costo_esperado is not None),
                              Decimal(0)).quantize(Decimal("0.01")),
        "created_at": pedido.created_at, "enviado_at": pedido.enviado_at, "cerrado_at": pedido.cerrado_at,
    }


def listar(db: Session, usuario: Usuario, estado: str | None = None, proveedor_id: int | None = None,
           limite: int = 50) -> list[dict]:
    _validar_rol(usuario)
    stmt = select(Pedido).where(Pedido.negocio_id == usuario.negocio_id)
    if estado:
        try:
            stmt = stmt.where(Pedido.estado == EstadoPedido(estado))
        except ValueError:
            raise OperacionInvalida("Estado inválido")
    if proveedor_id is not None:
        stmt = stmt.where(Pedido.proveedor_id == proveedor_id)
    pedidos = db.scalars(stmt.order_by(Pedido.id.desc()).limit(limite)).all()
    return [_resumen(db, p) for p in pedidos]


def detalle(db: Session, usuario: Usuario, pedido_id: int) -> dict:
    pedido = obtener(db, usuario, pedido_id)
    productos = {p.id: p for p in db.scalars(
        select(Producto).where(Producto.id.in_([r.producto_id for r in pedido.renglones]))
    )} if pedido.renglones else {}
    entradas = _entradas_ligadas(db, pedido)
    disponibles = []
    if pedido.estado == EstadoPedido.ENVIADO:
        ligadas = select(PedidoEntrada.entrada_id)
        disponibles = [
            {"id": e.id, "folio": e.folio, "fecha_recepcion": e.fecha_recepcion}
            for e in db.scalars(
                select(Entrada).where(Entrada.negocio_id == usuario.negocio_id, Entrada.proveedor_id == pedido.proveedor_id,
                                      Entrada.created_at >= pedido.created_at, Entrada.id.not_in(ligadas))
                .order_by(Entrada.id.desc()).limit(20)
            )
        ]
    return {
        **_resumen(db, pedido),
        "renglones": sorted([
            {"producto_id": r.producto_id, "clave": productos[r.producto_id].clave,
             "nombre": productos[r.producto_id].nombre, "cantidad": r.cantidad, "costo_esperado": r.costo_esperado,
             "importe": (r.cantidad * r.costo_esperado).quantize(Decimal("0.01")) if r.costo_esperado is not None else None}
            for r in pedido.renglones
        ], key=lambda x: x["nombre"]),
        "entradas": [{"id": e.id, "folio": e.folio, "fecha_recepcion": e.fecha_recepcion} for e in entradas],
        "entradas_disponibles": disponibles,
        "comparacion": comparar(db, pedido) if entradas else None,
    }
