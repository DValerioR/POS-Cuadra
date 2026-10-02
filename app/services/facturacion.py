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
- Antes de llamar al PAC se guarda un IntentoFactura con su serie y folio.
  Si la conexión se corta a la mitad no se sabe si quedó timbrada: el
  intento se queda y «Reintentar» primero la busca en el PAC, para no hacer
  un CFDI duplicado ante el SAT.
"""

import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.facturacion import catalogos
from app.facturacion.pac import Concepto, FacturaDatos, TimbradoIncierto, es_de_prueba, obtener_pac, totales_xml
from app.models import (
    ClienteFiscal, Devolucion, EstadoVenta, Factura, IntentoFactura, MetodoPago, Negocio, Producto, RolUsuario, TipoUso,
    Usuario, Venta,
)
from app.services import usos
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
    pendiente = _intento_de(db, venta)
    if pendiente is not None and not bloqueo:
        bloqueo = _aviso_pendiente(pendiente)
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
        "pendiente": _resumen_intento(pendiente, venta.folio, venta.total) if pendiente else None,
    }


def buscar_cliente(db: Session, usuario: Usuario, rfc: str) -> ClienteFiscal | None:
    _validar_rol(usuario)
    return db.scalar(select(ClienteFiscal).where(ClienteFiscal.negocio_id == usuario.negocio_id,
                                                 ClienteFiscal.rfc == (rfc or "").strip().upper()))


def facturar(db: Session, usuario: Usuario, folio: int, rfc: str, nombre: str, codigo_postal: str,
             regimen: str, uso_cfdi: str, email: str | None = None, tarjeta: str = "04") -> IntentoFactura:
    """Revisa los datos, guarda al cliente y aparta serie y folio en un
    IntentoFactura. No timbra ni hace commit: quien llama hace commit (para
    que el intento quede guardado antes de llamar al PAC) y luego `timbrar`."""
    venta = buscar_venta(db, usuario, folio)
    bloqueo, _ = _problemas(db, venta)
    if bloqueo:
        raise OperacionInvalida(bloqueo)
    if (pendiente := _intento_de(db, venta)) is not None:
        raise OperacionInvalida(_aviso_pendiente(pendiente))
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

    pac = obtener_pac()
    if not es_de_prueba(pac.nombre):  # las de prueba no cuestan ni cuentan contra el tope
        usos.revisar(db, usuario.negocio_id, TipoUso.FACTURA)
    serie = negocio.factura_serie
    folio_factura = max(
        db.scalar(select(func.max(Factura.folio)).where(Factura.negocio_id == usuario.negocio_id, Factura.serie == serie)) or 0,
        db.scalar(select(func.max(IntentoFactura.folio)).where(IntentoFactura.negocio_id == usuario.negocio_id,
                                                               IntentoFactura.serie == serie)) or 0,
    ) + 1
    intento = IntentoFactura(
        negocio_id=usuario.negocio_id, venta_id=venta.id, usuario_id=usuario.id, serie=serie, folio=folio_factura,
        pac=pac.nombre, datos={"rfc": rfc, "nombre": nombre, "codigo_postal": codigo_postal, "regimen": regimen,
                               "uso_cfdi": uso_cfdi, "tarjeta": tarjeta},
    )
    db.add(intento)
    db.flush()
    return intento


def _datos(db: Session, negocio: Negocio, venta: Venta, intento: IntentoFactura) -> FacturaDatos:
    d = intento.datos
    conceptos, _ = _conceptos(db, venta)
    return FacturaDatos(
        serie=intento.serie, folio=intento.folio, fecha=datetime.now(_zona()).replace(microsecond=0, tzinfo=None),
        lugar_expedicion=negocio.codigo_postal, forma_pago=_forma_pago(venta, d["tarjeta"]), metodo_pago="PUE",
        emisor_rfc=negocio.rfc, emisor_nombre=negocio.razon_social.upper(), emisor_regimen=negocio.regimen_fiscal,
        receptor_rfc=d["rfc"], receptor_nombre=d["nombre"], receptor_codigo_postal=d["codigo_postal"],
        receptor_regimen=d["regimen"], uso_cfdi=d["uso_cfdi"], conceptos=conceptos,
        subtotal=venta.subtotal, iva=venta.iva, ieps=venta.ieps, total=venta.total,
    )


def _pac_del_intento(intento: IntentoFactura):
    pac = obtener_pac()
    if pac.nombre != intento.pac:
        raise OperacionInvalida(f"Esta factura se mandó a timbrar con «{intento.pac}» y ahora está configurado "
                                f"«{pac.nombre}». Regresa la conexión anterior para poder revisarla")
    return pac


def _aviso_pendiente(intento: IntentoFactura) -> str:
    detalle = f" ({intento.mensaje})" if intento.mensaje else ""
    return (f"La factura {intento.serie}-{intento.folio} de este ticket no se pudo confirmar{detalle}. "
            "Usa «Reintentar»: primero revisa si ya quedó timbrada, así no se duplica ante el SAT")


def _incierto(intento: IntentoFactura, e: TimbradoIncierto) -> OperacionInvalida:
    intento.mensaje = str(e)
    intento.pac_id = e.pac_id or intento.pac_id
    return OperacionInvalida(_aviso_pendiente(intento))


def timbrar(db: Session, usuario: Usuario, intento: IntentoFactura) -> Factura:
    """Manda a timbrar un intento ya guardado. Si el PAC la rechazó, el
    intento se borra; si no se sabe qué pasó, se queda para «Reintentar».
    En los dos casos lanza OperacionInvalida, y quien llama hace commit
    igual, para guardar lo que pasó."""
    venta = db.get(Venta, intento.venta_id)
    datos = _datos(db, db.get(Negocio, intento.negocio_id), venta, intento)
    pac = _pac_del_intento(intento)
    try:
        timbrado = pac.timbrar(datos)
    except TimbradoIncierto as e:
        raise _incierto(intento, e)
    except OperacionInvalida:
        db.delete(intento)
        raise
    return _guardar(db, intento, venta, datos, pac, timbrado)


def reintentar(db: Session, usuario: Usuario, intento_id: int) -> Factura:
    """Revisa en el PAC si la factura ya se timbró: si está, la guarda; si
    no, la timbra con la misma serie y folio. Como `timbrar`, quien llama
    hace commit aunque falle."""
    intento = _intento(db, usuario, intento_id)
    venta = db.get(Venta, intento.venta_id)
    datos = _datos(db, db.get(Negocio, intento.negocio_id), venta, intento)
    pac = _pac_del_intento(intento)
    intento.intentos += 1
    try:
        timbrado = pac.recuperar(datos, intento.pac_id)
    except TimbradoIncierto as e:
        raise _incierto(intento, e)
    if timbrado is None:
        # Confirmado que no se timbró: se vuelve a mandar, si el ticket todavía se puede facturar.
        bloqueo, _ = _problemas(db, venta)
        if bloqueo:
            db.delete(intento)
            raise OperacionInvalida(f"La factura no llegó a timbrarse y el ticket ya no se puede facturar: {bloqueo}")
        try:
            timbrado = pac.timbrar(datos)
        except TimbradoIncierto as e:
            raise _incierto(intento, e)
        except OperacionInvalida:
            db.delete(intento)
            raise
    return _guardar(db, intento, venta, datos, pac, timbrado)


def descartar(db: Session, usuario: Usuario, intento_id: int) -> None:
    """Quita un intento solo si el PAC confirma que no se timbró (para
    corregir los datos del cliente y empezar de nuevo). No hace commit."""
    intento = _intento(db, usuario, intento_id)
    datos = _datos(db, db.get(Negocio, intento.negocio_id), db.get(Venta, intento.venta_id), intento)
    pac = _pac_del_intento(intento)
    try:
        timbrado = pac.recuperar(datos, intento.pac_id)
    except TimbradoIncierto as e:
        raise OperacionInvalida(f"Todavía no se puede descartar: {e}. Intenta más tarde")
    if timbrado is not None:
        raise OperacionInvalida("Esa factura sí quedó timbrada. Usa «Reintentar» para guardarla; si tenía un error, "
                                "cancélala después")
    db.delete(intento)
    db.flush()


def _guardar(db: Session, intento: IntentoFactura, venta: Venta, datos: FacturaDatos, pac, timbrado) -> Factura:
    d = intento.datos
    # Los importes como quedaron timbrados (el PAC real puede redondear algún centavo distinto).
    totales = ({"subtotal": venta.subtotal, "iva": venta.iva, "ieps": venta.ieps, "total": venta.total}
               if pac.nombre == "simulado" else totales_xml(timbrado.xml))
    cliente = db.scalar(select(ClienteFiscal).where(ClienteFiscal.negocio_id == intento.negocio_id,
                                                    ClienteFiscal.rfc == d["rfc"]))
    factura = Factura(
        negocio_id=intento.negocio_id, venta_id=venta.id, cliente_id=cliente.id, usuario_id=intento.usuario_id,
        serie=intento.serie, folio=intento.folio, receptor_rfc=d["rfc"], receptor_nombre=d["nombre"],
        receptor_codigo_postal=d["codigo_postal"], receptor_regimen=d["regimen"], uso_cfdi=d["uso_cfdi"],
        forma_pago=datos.forma_pago, **totales, pac=pac.nombre, pac_id=timbrado.pac_id, uuid=timbrado.uuid,
        fecha_timbrado=timbrado.fecha_timbrado.replace(tzinfo=_zona())
        if timbrado.fecha_timbrado.tzinfo is None else timbrado.fecha_timbrado,
        xml=timbrado.xml, pdf=timbrado.pdf,
    )
    negocio_id = intento.negocio_id
    db.delete(intento)
    db.flush()
    db.add(factura)
    if not es_de_prueba(pac.nombre):
        usos.registrar(db, negocio_id, TipoUso.FACTURA, "factura")
    db.flush()
    return factura


def _intento_de(db: Session, venta: Venta) -> IntentoFactura | None:
    return db.scalar(select(IntentoFactura).where(IntentoFactura.venta_id == venta.id))


def _intento(db: Session, usuario: Usuario, intento_id: int) -> IntentoFactura:
    _validar_rol(usuario)
    intento = db.get(IntentoFactura, intento_id)
    if intento is None or intento.negocio_id != usuario.negocio_id:
        raise NoEncontrado("Esa factura pendiente ya no existe (quizá ya se resolvió)")
    return intento


def pendientes(db: Session, usuario: Usuario) -> list[dict]:
    """Las facturas que no se pudieron confirmar, para «Reintentar»."""
    _validar_rol(usuario)
    filas = db.execute(
        select(IntentoFactura, Venta.folio, Venta.total).join(Venta, Venta.id == IntentoFactura.venta_id)
        .where(IntentoFactura.negocio_id == usuario.negocio_id).order_by(IntentoFactura.created_at)
    ).all()
    return [_resumen_intento(i, folio, total) for i, folio, total in filas]


def _resumen_intento(i: IntentoFactura, folio_ticket: int, total: Decimal) -> dict:
    return {"id": i.id, "serie": i.serie, "folio": i.folio, "folio_ticket": folio_ticket, "total": total,
            "receptor_rfc": i.datos["rfc"], "receptor_nombre": i.datos["nombre"], "mensaje": i.mensaje,
            "intentos": i.intentos, "created_at": i.created_at, "de_prueba": es_de_prueba(i.pac)}

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
