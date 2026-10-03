"""Factura global al público en general (CFDI 4.0 con InformacionGlobal).

Reglas:
- La hace un administrador, por periodo: diario, semanal (de lunes a domingo,
  sin pasar del mes), quincenal (1-15 y 16 a fin de mes), mensual o bimestral.
  El periodo tiene que haber terminado, para que no se quede fuera ninguna venta.
- Entran los tickets completados del periodo que no se facturaron a un
  cliente ni van en otra global. Si un ticket tuvo devoluciones, entra solo
  lo que el cliente se quedó; si se devolvió todo, no entra.
- Cada ticket es un concepto ("Venta", clave 01010101, unidad ACT, con el
  folio del ticket como número de identificación), uno por cada combinación
  de IVA e IEPS que tenga el ticket.
- Receptor: XAXX010101000, PUBLICO EN GENERAL, régimen 616, uso S01 y el
  código postal del negocio. Forma de pago: la de mayor monto en el periodo.
- Se timbra igual que la de un ticket (IntentoFactura antes de llamar al PAC,
  «Reintentar» sin duplicar). Los tickets quedan apartados para la global
  desde el intento (VentaEnGlobal) y se liberan si se cancela.
"""

import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session, selectinload

from app.facturacion import catalogos
from app.facturacion.pac import Concepto, FacturaDatos, es_de_prueba, obtener_pac
from app.models import (
    EstadoFactura, EstadoVenta, Factura, IntentoFactura, MetodoPago, Negocio, RolUsuario, TipoFactura, TipoUso, Usuario,
    Venta, VentaEnGlobal, VentaRenglon,
)
from app.services import usos
from app.services.errores import OperacionInvalida, SinPermiso
from app.services.facturacion import _aviso_pendiente, _faltantes_negocio, _zona, texto_periodo

CENTAVO = Decimal("0.01")


def _validar(usuario: Usuario) -> None:
    if usuario.rol != RolUsuario.ADMIN:
        raise SinPermiso("La factura global la hace un administrador")


def periodo(periodicidad: str, dia: date) -> tuple[date, date, str, int]:
    """(desde, hasta, meses, año) del periodo que contiene ese día."""
    ultimo = calendar.monthrange(dia.year, dia.month)[1]
    inicio_mes, fin_mes = dia.replace(day=1), dia.replace(day=ultimo)
    meses = f"{dia.month:02d}"
    if periodicidad == "01":
        return dia, dia, meses, dia.year
    if periodicidad == "02":
        lunes = dia - timedelta(days=dia.weekday())
        return max(lunes, inicio_mes), min(lunes + timedelta(days=6), fin_mes), meses, dia.year
    if periodicidad == "03":
        return (inicio_mes, dia.replace(day=15), meses, dia.year) if dia.day <= 15 else \
            (dia.replace(day=16), fin_mes, meses, dia.year)
    if periodicidad == "04":
        return inicio_mes, fin_mes, meses, dia.year
    if periodicidad == "05":
        primero = dia.month if dia.month % 2 else dia.month - 1  # ene-feb, mar-abr, ...
        desde = date(dia.year, primero, 1)
        hasta = date(dia.year, primero + 1, calendar.monthrange(dia.year, primero + 1)[1])
        return desde, hasta, str(12 + (primero + 1) // 2), dia.year
    raise OperacionInvalida("Elige si la factura global es diaria, semanal, quincenal, mensual o bimestral")


def _ventas_libres(db: Session, negocio_id: int, desde: date, hasta: date) -> list[Venta]:
    """Tickets del periodo que se pueden poner en una global."""
    zona = _zona()
    inicio = datetime.combine(desde, time.min, zona)
    fin = datetime.combine(hasta + timedelta(days=1), time.min, zona)
    return db.scalars(
        select(Venta)
        .where(Venta.negocio_id == negocio_id, Venta.estado == EstadoVenta.COMPLETADA,
               Venta.created_at >= inicio, Venta.created_at < fin,
               ~exists().where(and_(Factura.venta_id == Venta.id, Factura.estado != EstadoFactura.CANCELADA)),
               ~exists().where(IntentoFactura.venta_id == Venta.id),
               ~exists().where(VentaEnGlobal.venta_id == Venta.id))
        .options(selectinload(Venta.renglones).selectinload(VentaRenglon.lotes), selectinload(Venta.pagos))
        .order_by(Venta.folio)
    ).all()


def _conceptos_de(venta: Venta) -> list[Concepto]:
    """Lo que el cliente se quedó del ticket, un concepto por cada tasa de IVA/IEPS."""
    por_tasa: dict[tuple[Decimal, Decimal], list[Decimal]] = defaultdict(lambda: [Decimal(0)] * 3)
    for r in venta.renglones:
        devuelta = sum((l.cantidad_devuelta for l in r.lotes), Decimal(0))
        if devuelta >= r.cantidad:
            continue
        factor = (r.cantidad - devuelta) / r.cantidad
        sumas = por_tasa[(r.iva_porcentaje, r.ieps_porcentaje)]
        for i, importe in enumerate((r.subtotal, r.iva, r.ieps)):
            sumas[i] += (importe * factor).quantize(CENTAVO, ROUND_HALF_UP) if factor != 1 else importe
    conceptos = []
    for (iva, ieps), (subtotal, monto_iva, monto_ieps) in sorted(por_tasa.items()):
        if subtotal <= 0:
            continue
        conceptos.append(Concepto(
            clave_prod_serv=catalogos.CLAVE_GENERICA, clave_unidad=catalogos.CLAVE_UNIDAD_GLOBAL, cantidad=Decimal(1),
            descripcion="Venta", no_identificacion=str(venta.folio), valor_unitario=subtotal.quantize(Decimal("0.000001")),
            importe=subtotal, iva_tasa=(iva / 100).quantize(Decimal("0.000001")), iva=monto_iva,
            ieps_tasa=(ieps / 100).quantize(Decimal("0.000001")), ieps=monto_ieps,
        ))
    return conceptos


def _forma_pago(ventas: list[Venta], tarjeta: str) -> str:
    """La forma de pago con más dinero en el periodo (el saldo a favor de un cambio no es dinero)."""
    montos: dict[MetodoPago, Decimal] = defaultdict(Decimal)
    for v in ventas:
        for p in v.pagos:
            if p.metodo != MetodoPago.SALDO_A_FAVOR:
                montos[p.metodo] += p.monto
    principal = max(montos, key=montos.get) if montos else MetodoPago.EFECTIVO
    return {MetodoPago.EFECTIVO: "01", MetodoPago.TARJETA: tarjeta, MetodoPago.TRANSFERENCIA: "03"}.get(principal, "01")


def _calcular(db: Session, negocio_id: int, periodicidad: str, dia: date):
    desde, hasta, meses, anio = periodo(periodicidad, dia)
    ventas = _ventas_libres(db, negocio_id, desde, hasta)
    conceptos_por_venta = [(v, _conceptos_de(v)) for v in ventas]
    conceptos_por_venta = [(v, c) for v, c in conceptos_por_venta if c]
    return desde, hasta, meses, anio, conceptos_por_venta


def _totales(conceptos: list[Concepto]) -> dict[str, Decimal]:
    subtotal = sum((c.importe for c in conceptos), Decimal(0))
    iva = sum((c.iva for c in conceptos), Decimal(0))
    ieps = sum((c.ieps for c in conceptos), Decimal(0))
    return {"subtotal": subtotal, "iva": iva, "ieps": ieps, "total": subtotal + iva + ieps}


def _bloqueo_periodo(hasta: date) -> str | None:
    hoy = datetime.now(_zona()).date()
    if hasta >= hoy:
        return f"El periodo todavía no termina (termina el {hasta:%d/%m/%Y}); la global se hace cuando ya cerró"
    return None


def preparar(db: Session, usuario: Usuario, periodicidad: str, dia: date) -> dict:
    """Lo que la pantalla muestra antes de timbrar la global."""
    _validar(usuario)
    desde, hasta, meses, anio, por_venta = _calcular(db, usuario.negocio_id, periodicidad, dia)
    conceptos = [c for _, c in por_venta for c in c]
    ventas = [v for v, _ in por_venta]
    negocio = db.get(Negocio, usuario.negocio_id)
    bloqueo = _bloqueo_periodo(hasta)
    if not bloqueo and (faltan := _faltantes_negocio(negocio)):
        bloqueo = f"Faltan datos fiscales del negocio ({', '.join(faltan)}): un administrador los pone en Datos del negocio"
    if not bloqueo and not ventas:
        bloqueo = "No hay tickets sin facturar en ese periodo"
    avisos = []
    if hasta.month != datetime.now(_zona()).month or hasta.year != datetime.now(_zona()).year:
        avisos.append("El periodo es de un mes anterior: confirma con el contador que todavía se puede emitir.")
    return {
        "periodicidad": periodicidad, "desde": desde, "hasta": hasta, "meses": meses, "anio": anio,
        "periodo": texto_periodo(periodicidad, desde, hasta),
        "tickets": [{"folio": v.folio, "fecha": v.created_at, **_totales(c)} for v, c in por_venta],
        **_totales(conceptos),
        "forma_pago": _forma_pago(ventas, "04"),
        "con_tarjeta": any(p.metodo == MetodoPago.TARJETA for v in ventas for p in v.pagos),
        "puede_facturar": bloqueo is None, "motivo": bloqueo, "avisos": avisos,
    }


def facturar(db: Session, usuario: Usuario, periodicidad: str, dia: date, tarjeta: str = "04") -> IntentoFactura:
    """Aparta serie, folio y los tickets en un IntentoFactura. No timbra ni
    hace commit (igual que facturacion.facturar)."""
    _validar(usuario)
    if tarjeta not in ("04", "28"):
        raise OperacionInvalida("Forma de pago con tarjeta inválida")
    desde, hasta, meses, anio, por_venta = _calcular(db, usuario.negocio_id, periodicidad, dia)
    if bloqueo := _bloqueo_periodo(hasta):
        raise OperacionInvalida(bloqueo)
    negocio = db.get(Negocio, usuario.negocio_id)
    if faltan := _faltantes_negocio(negocio):
        raise OperacionInvalida(f"Faltan datos fiscales del negocio: {', '.join(faltan)}")
    if not por_venta:
        raise OperacionInvalida("No hay tickets sin facturar en ese periodo")

    pac = obtener_pac()
    if not es_de_prueba(pac.nombre):
        usos.revisar(db, usuario.negocio_id, TipoUso.FACTURA)
    serie = negocio.factura_serie
    folio = max(
        db.scalar(select(func.max(Factura.folio)).where(Factura.negocio_id == negocio.id, Factura.serie == serie)) or 0,
        db.scalar(select(func.max(IntentoFactura.folio)).where(IntentoFactura.negocio_id == negocio.id,
                                                               IntentoFactura.serie == serie)) or 0,
    ) + 1
    conceptos = [c for _, cs in por_venta for c in cs]
    intento = IntentoFactura(
        negocio_id=negocio.id, tipo=TipoFactura.GLOBAL.value, venta_id=None, usuario_id=usuario.id, serie=serie,
        folio=folio, pac=pac.nombre,
        datos={"periodicidad": periodicidad, "meses": meses, "anio": anio, "desde": desde.isoformat(),
               "hasta": hasta.isoformat(), "forma_pago": _forma_pago([v for v, _ in por_venta], tarjeta),
               "total": str(_totales(conceptos)["total"])},
    )
    db.add(intento)
    db.flush()
    for v, _ in por_venta:
        db.add(VentaEnGlobal(negocio_id=negocio.id, venta_id=v.id, intento_id=intento.id))
    db.flush()
    return intento


def datos_global(db: Session, negocio: Negocio, intento: IntentoFactura) -> FacturaDatos:
    """Los datos de la global a partir de los tickets apartados para el intento."""
    d = intento.datos
    ventas = db.scalars(
        select(Venta).join(VentaEnGlobal, VentaEnGlobal.venta_id == Venta.id)
        .where(VentaEnGlobal.intento_id == intento.id)
        .options(selectinload(Venta.renglones).selectinload(VentaRenglon.lotes))
        .order_by(Venta.folio)
    ).all()
    conceptos = [c for v in ventas for c in _conceptos_de(v)]
    if not conceptos:
        raise OperacionInvalida(_aviso_pendiente(intento))
    return FacturaDatos(
        serie=intento.serie, folio=intento.folio, fecha=datetime.now(_zona()).replace(microsecond=0, tzinfo=None),
        lugar_expedicion=negocio.codigo_postal, forma_pago=d["forma_pago"], metodo_pago="PUE",
        emisor_rfc=negocio.rfc, emisor_nombre=negocio.razon_social.upper(), emisor_regimen=negocio.regimen_fiscal,
        receptor_rfc=catalogos.RFC_GENERICO, receptor_nombre=catalogos.NOMBRE_GENERICO,
        receptor_codigo_postal=negocio.codigo_postal, receptor_regimen=catalogos.REGIMEN_GENERICO,
        uso_cfdi=catalogos.USO_GENERICO, conceptos=conceptos, **_totales(conceptos),
        global_periodicidad=d["periodicidad"], global_meses=d["meses"], global_anio=d["anio"],
    )


def tickets_de(db: Session, factura: Factura) -> list[int]:
    """Folios de los tickets que van en una global."""
    return list(db.scalars(
        select(Venta.folio).join(VentaEnGlobal, VentaEnGlobal.venta_id == Venta.id)
        .where(VentaEnGlobal.factura_id == factura.id).order_by(Venta.folio)
    ))
