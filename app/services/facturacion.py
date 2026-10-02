"""Facturar un ticket (CFDI 4.0 de ingreso a un cliente).

Reglas:
- Solo ventas completadas, sin devoluciones y que no se hayan facturado.
- Una venta de un mes anterior se puede facturar, pero se avisa: el SAT pide
  facturar en el mes de la venta.
- Los conceptos salen del ticket tal cual (precio con impuestos → valor
  unitario sin impuestos, IEPS e IVA por renglón). Sin clave SAT, se usa la
  genérica 01010101 y se avisa.
- La forma de pago sale de cómo se cobró (la de mayor monto si fue mixto);
  con tarjeta se pregunta si fue de crédito (04) o de débito (28).
- El negocio necesita sus datos fiscales completos (Datos del negocio).
"""

import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.facturacion import catalogos
from app.facturacion.pac import Concepto, FacturaDatos, es_de_prueba, obtener_pac, totales_xml
from app.models import (
    ClienteFiscal, Devolucion, EstadoVenta, Factura, MetodoPago, Negocio, Producto, RolUsuario, Usuario, Venta,
)
from app.services.errores import NoEncontrado, OperacionInvalida, SinPermiso

ROLES = {RolUsuario.ADMIN, RolUsuario.MOSTRADOR}
FORMATO_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
CENTAVO = Decimal("0.01")


def _validar_rol(usuario: Usuario) -> None:
    if usuario.rol not in ROLES:
        raise SinPermiso("Facturan los administradores y mostrador")


def _zona() -> ZoneInfo:
    return ZoneInfo(settings.zona_horaria)


def buscar_venta(db: Session, usuario: Usuario, folio: int) -> Venta:
    _validar_rol(usuario)
    venta = db.scalar(select(Venta).where(Venta.negocio_id == usuario.negocio_id, Venta.folio == folio))
    if venta is None:
        raise NoEncontrado(f"No hay ningún ticket con el folio {folio}")
    return venta


def _problemas(db: Session, venta: Venta) -> tuple[str | None, list[str]]:
    """(por qué no se puede facturar, avisos)."""
    ya = db.scalar(select(Factura).where(Factura.venta_id == venta.id))
    if ya is not None:
        return f"Este ticket ya se facturó ({ya.serie}-{ya.folio}, {ya.receptor_rfc})", []
    if venta.estado == EstadoVenta.CANCELADA:
        return "El ticket está cancelado", []
    if db.scalar(select(func.count()).select_from(Devolucion).where(Devolucion.venta_id == venta.id)):
        return "El ticket tiene devoluciones o cambios; no se puede facturar desde aquí", []
    avisos = []
    hoy = datetime.now(_zona())
    fecha = venta.created_at.astimezone(_zona())
    if (fecha.year, fecha.month) != (hoy.year, hoy.month):
        avisos.append("La venta es de un mes anterior: el SAT pide facturar en el mes de la venta.")
    return None, avisos


def _forma_pago(venta: Venta, tarjeta: str) -> str:
    montos: dict[MetodoPago, Decimal] = {}
    for p in venta.pagos:
        montos[p.metodo] = montos.get(p.metodo, Decimal(0)) + p.monto
    principal = max(montos, key=montos.get) if montos else MetodoPago.EFECTIVO
    return {MetodoPago.EFECTIVO: "01", MetodoPago.TARJETA: tarjeta, MetodoPago.TRANSFERENCIA: "03"}.get(principal, "01")


def _conceptos(db: Session, venta: Venta) -> tuple[list[Concepto], int]:
    """Conceptos del ticket y cuántos no tienen clave SAT."""
    productos = {p.id: p for p in db.scalars(select(Producto).where(Producto.id.in_([r.producto_id for r in venta.renglones])))}
    conceptos, sin_clave = [], 0
    for r in venta.renglones:
        p = productos.get(r.producto_id)
        clave = (p.clave_sat or "").strip() if p else ""
        if not re.fullmatch(r"\d{8}", clave):
            clave, sin_clave = catalogos.CLAVE_GENERICA, sin_clave + 1
        conceptos.append(Concepto(
            clave_prod_serv=clave, clave_unidad=catalogos.CLAVE_UNIDAD, cantidad=Decimal(r.cantidad).normalize(),
            descripcion=r.nombre, no_identificacion=(p.clave if p else None),
            valor_unitario=(r.subtotal / r.cantidad).quantize(Decimal("0.000001")), importe=r.subtotal,
            iva_tasa=(r.iva_porcentaje / 100).quantize(Decimal("0.000001")), iva=r.iva,
            ieps_tasa=(r.ieps_porcentaje / 100).quantize(Decimal("0.000001")), ieps=r.ieps,
        ))
    return conceptos, sin_clave


def _faltantes_negocio(negocio: Negocio) -> list[str]:
    return [texto for campo, texto in (("razon_social", "razón social"), ("rfc", "RFC"), ("regimen_fiscal", "régimen fiscal"),
                                       ("codigo_postal", "código postal")) if not getattr(negocio, campo)]


def preparar(db: Session, usuario: Usuario, folio: int) -> dict:
    """Lo que la pantalla muestra antes de timbrar."""
    venta = buscar_venta(db, usuario, folio)
    negocio = db.get(Negocio, usuario.negocio_id)
    bloqueo, avisos = _problemas(db, venta)
    faltan = _faltantes_negocio(negocio)
    if faltan and not bloqueo:
        bloqueo = f"Faltan datos fiscales del negocio ({', '.join(faltan)}): un administrador los pone en Datos del negocio"
    conceptos, sin_clave = _conceptos(db, venta)
    if sin_clave:
        avisos.append(f"{sin_clave} producto(s) sin clave SAT: se facturan con la genérica {catalogos.CLAVE_GENERICA}.")
    metodos = {p.metodo for p in venta.pagos}
    return {
        "venta_id": venta.id, "folio": venta.folio, "fecha": venta.created_at, "total": venta.total,
        "subtotal": venta.subtotal, "iva": venta.iva, "ieps": venta.ieps,
        "con_tarjeta": MetodoPago.TARJETA in metodos,
        "forma_pago": _forma_pago(venta, "04"),
        "conceptos": [{"descripcion": c.descripcion, "cantidad": c.cantidad, "clave_prod_serv": c.clave_prod_serv,
                       "valor_unitario": c.valor_unitario, "importe": c.importe, "iva": c.iva, "ieps": c.ieps}
                      for c in conceptos],
        "puede_facturar": bloqueo is None, "motivo": bloqueo, "avisos": avisos,
    }


def buscar_cliente(db: Session, usuario: Usuario, rfc: str) -> ClienteFiscal | None:
    _validar_rol(usuario)
    return db.scalar(select(ClienteFiscal).where(ClienteFiscal.negocio_id == usuario.negocio_id,
                                                 ClienteFiscal.rfc == (rfc or "").strip().upper()))


def facturar(db: Session, usuario: Usuario, folio: int, rfc: str, nombre: str, codigo_postal: str,
             regimen: str, uso_cfdi: str, email: str | None = None, tarjeta: str = "04") -> Factura:
    """Timbra la factura del ticket y la guarda. No hace commit."""
    venta = buscar_venta(db, usuario, folio)
    bloqueo, _ = _problemas(db, venta)
    if bloqueo:
        raise OperacionInvalida(bloqueo)
    negocio = db.get(Negocio, usuario.negocio_id)
    if faltan := _faltantes_negocio(negocio):
        raise OperacionInvalida(f"Faltan datos fiscales del negocio: {', '.join(faltan)}")

    rfc = (rfc or "").strip().upper()
    nombre = " ".join((nombre or "").upper().split())
    codigo_postal = (codigo_postal or "").strip()
    if not FORMATO_RFC.match(rfc):
        raise OperacionInvalida("El RFC no tiene el formato correcto (12 o 13 caracteres)")
    if not nombre:
        raise OperacionInvalida("Falta la razón social (como aparece en la constancia de situación fiscal)")
    if not re.fullmatch(r"\d{5}", codigo_postal):
        raise OperacionInvalida("El código postal del cliente son 5 números")
    if error := catalogos.validar_receptor(rfc, regimen, uso_cfdi):
        raise OperacionInvalida(error)
    if tarjeta not in ("04", "28"):
        raise OperacionInvalida("Forma de pago con tarjeta inválida")

    cliente = buscar_cliente(db, usuario, rfc)
    if cliente is None:
        cliente = ClienteFiscal(negocio_id=usuario.negocio_id, rfc=rfc, nombre=nombre, codigo_postal=codigo_postal,
                                regimen_fiscal=regimen, uso_cfdi=uso_cfdi)
        db.add(cliente)
    cliente.nombre, cliente.codigo_postal, cliente.regimen_fiscal, cliente.uso_cfdi = nombre, codigo_postal, regimen, uso_cfdi
    cliente.email = (email or "").strip() or cliente.email
    db.flush()

    conceptos, _ = _conceptos(db, venta)
    folio_factura = (db.scalar(select(func.max(Factura.folio)).where(
        Factura.negocio_id == usuario.negocio_id, Factura.serie == negocio.factura_serie)) or 0) + 1
    forma_pago = _forma_pago(venta, tarjeta)
    datos = FacturaDatos(
        serie=negocio.factura_serie, folio=folio_factura, fecha=datetime.now(_zona()).replace(microsecond=0, tzinfo=None),
        lugar_expedicion=negocio.codigo_postal, forma_pago=forma_pago, metodo_pago="PUE",
        emisor_rfc=negocio.rfc, emisor_nombre=negocio.razon_social.upper(), emisor_regimen=negocio.regimen_fiscal,
        receptor_rfc=rfc, receptor_nombre=nombre, receptor_codigo_postal=codigo_postal, receptor_regimen=regimen,
        uso_cfdi=uso_cfdi, conceptos=conceptos,
        subtotal=venta.subtotal, iva=venta.iva, ieps=venta.ieps, total=venta.total,
    )
    pac = obtener_pac()
    timbrado = pac.timbrar(datos)
    # Los importes como quedaron timbrados (el PAC real puede redondear algún centavo distinto).
    totales = ({"subtotal": venta.subtotal, "iva": venta.iva, "ieps": venta.ieps, "total": venta.total}
               if pac.nombre == "simulado" else totales_xml(timbrado.xml))
    factura = Factura(
        negocio_id=usuario.negocio_id, venta_id=venta.id, cliente_id=cliente.id, usuario_id=usuario.id,
        serie=datos.serie, folio=datos.folio, receptor_rfc=rfc, receptor_nombre=nombre,
        receptor_codigo_postal=codigo_postal, receptor_regimen=regimen, uso_cfdi=uso_cfdi, forma_pago=forma_pago,
        **totales, pac=pac.nombre, pac_id=timbrado.pac_id, uuid=timbrado.uuid, fecha_timbrado=timbrado.fecha_timbrado.replace(tzinfo=_zona())
        if timbrado.fecha_timbrado.tzinfo is None else timbrado.fecha_timbrado,
        xml=timbrado.xml, pdf=timbrado.pdf,
    )
    db.add(factura)
    db.flush()
    return factura


def obtener(db: Session, usuario: Usuario, factura_id: int) -> Factura:
    _validar_rol(usuario)
    f = db.get(Factura, factura_id)
    if f is None or f.negocio_id != usuario.negocio_id:
        raise NoEncontrado("Factura no encontrada")
    return f


def resumen(f: Factura, folio_ticket: int | None = None) -> dict:
    return {
        "id": f.id, "serie": f.serie, "folio": f.folio, "uuid": f.uuid, "estado": f.estado.value,
        "fecha_timbrado": f.fecha_timbrado, "receptor_rfc": f.receptor_rfc, "receptor_nombre": f.receptor_nombre,
        "uso_cfdi": f.uso_cfdi, "forma_pago": f.forma_pago, "total": f.total, "pac": f.pac,
        "de_prueba": es_de_prueba(f.pac), "folio_ticket": folio_ticket,
    }


def listar(db: Session, usuario: Usuario, limite: int = 50) -> list[dict]:
    _validar_rol(usuario)
    filas = db.execute(
        select(Factura, Venta.folio).join(Venta, Venta.id == Factura.venta_id)
        .where(Factura.negocio_id == usuario.negocio_id).order_by(Factura.id.desc()).limit(limite)
    ).all()
    return [resumen(f, folio) for f, folio in filas]
