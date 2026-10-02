from urllib.parse import quote

from defusedxml import ElementTree
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, undefer

from app.api.entradas import _exacto
from app.core.auth import solo_admin, usuario_actual
from app.core.config import settings
from app.core.database import get_db
from app.facturacion import catalogos
from app.models import Factura, Negocio, Usuario, Venta
from app.services import configuracion_facturacion, facturacion
from app.services.errores import ERRORES_NEGOCIO, a_http

# La pantalla es /facturas; el API va en /cfdi para no chocar con ella.
router = APIRouter(prefix="/cfdi", tags=["facturación"])


class FacturarIn(BaseModel):
    folio_ticket: int
    rfc: str = Field(max_length=13)
    nombre: str = Field(max_length=254)
    codigo_postal: str = Field(max_length=5)
    regimen_fiscal: str = Field(max_length=3)
    uso_cfdi: str = Field(max_length=4)
    email: str | None = Field(default=None, max_length=120)
    tarjeta: str = "04"  # si se pagó con tarjeta: 04 crédito o 28 débito


@router.get("/catalogos")
def catalogos_sat(usuario: Usuario = Depends(usuario_actual)):
    return {
        "regimenes": {k: v[0] for k, v in catalogos.REGIMENES.items()},
        "usos": {k: v[0] for k, v in catalogos.USOS_CFDI.items()},
        "formas_pago": catalogos.FORMAS_PAGO,
        "pac": settings.pac or None,
        "de_prueba": configuracion_facturacion.estado()["de_prueba"],  # las facturas salen sin validez fiscal
    }


class ClaveIn(BaseModel):
    clave: str = Field(max_length=400)


@router.get("/conexion")
def conexion(usuario: Usuario = Depends(solo_admin)):
    """Con qué PAC se timbra y si hay clave (solo sus últimos 4 caracteres)."""
    return configuracion_facturacion.estado()


@router.put("/conexion/clave")
def guardar_clave(datos: ClaveIn, usuario: Usuario = Depends(solo_admin)):
    """Guarda la clave de Facturapi en el .env y timbra con ella desde ese momento."""
    try:
        return configuracion_facturacion.guardar(datos.clave)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.delete("/conexion/clave")
def quitar_clave(usuario: Usuario = Depends(solo_admin)):
    """Regresa a las facturas de prueba."""
    return configuracion_facturacion.quitar()


@router.post("/conexion/probar")
def probar_clave(usuario: Usuario = Depends(solo_admin)):
    try:
        return configuracion_facturacion.probar()
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/ticket/{folio}")
def preparar(folio: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """El ticket listo para facturar (o por qué no se puede)."""
    try:
        return _exacto(facturacion.preparar(db, usuario, folio))
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/clientes/{rfc}")
def cliente(rfc: str, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Los datos fiscales guardados de un cliente (para no volver a pedirlos)."""
    try:
        c = facturacion.buscar_cliente(db, usuario, rfc)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    if c is None:
        raise HTTPException(status_code=404, detail="Cliente nuevo")
    return {"rfc": c.rfc, "nombre": c.nombre, "codigo_postal": c.codigo_postal, "regimen_fiscal": c.regimen_fiscal,
            "uso_cfdi": c.uso_cfdi, "email": c.email}


@router.post("", status_code=201)
def facturar(datos: FacturarIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        f = facturacion.facturar(db, usuario, datos.folio_ticket, datos.rfc, datos.nombre, datos.codigo_postal,
                                 datos.regimen_fiscal, datos.uso_cfdi, datos.email, datos.tarjeta)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return _exacto(facturacion.resumen(f, datos.folio_ticket))


@router.get("")
def listar(limite: int = Query(50, le=200), usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        return _exacto(facturacion.listar(db, usuario, limite))
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


def _factura(db: Session, usuario: Usuario, factura_id: int) -> Factura:
    try:
        return facturacion.obtener(db, usuario, factura_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/{factura_id}")
def detalle(factura_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Todo lo de la factura para su representación impresa, leído del XML
    timbrado (así se ve exactamente lo que se facturó)."""
    f = db.get(Factura, _factura(db, usuario, factura_id).id, options=[undefer(Factura.xml), undefer(Factura.pdf)])
    raiz = ElementTree.fromstring(f.xml.encode("utf-8"))
    local = lambda n: n.tag.split("}")[-1]  # noqa: E731
    conceptos, timbre, emisor = [], {}, {}
    for n in raiz.iter():
        if local(n) == "Concepto":
            conceptos.append({k: n.attrib.get(k) for k in ("ClaveProdServ", "NoIdentificacion", "Cantidad", "ClaveUnidad",
                                                            "Descripcion", "ValorUnitario", "Importe")})
        elif local(n) == "TimbreFiscalDigital":
            timbre = dict(n.attrib)
        elif local(n) == "Emisor":
            emisor = dict(n.attrib)
    negocio = db.get(Negocio, f.negocio_id)
    folio_ticket = db.get(Venta, f.venta_id).folio
    return _exacto({
        **facturacion.resumen(f, folio_ticket),
        "fecha": raiz.attrib.get("Fecha"), "lugar_expedicion": raiz.attrib.get("LugarExpedicion"),
        "metodo_pago": f.metodo_pago, "subtotal": f.subtotal, "iva": f.iva, "ieps": f.ieps,
        "receptor_codigo_postal": f.receptor_codigo_postal, "receptor_regimen": f.receptor_regimen,
        "emisor_rfc": emisor.get("Rfc"), "emisor_nombre": emisor.get("Nombre"), "emisor_regimen": emisor.get("RegimenFiscal"),
        "negocio": negocio.nombre, "marca_url": negocio.marca_url,
        "conceptos": conceptos, "sello_cfd": timbre.get("SelloCFD"), "sello_sat": timbre.get("SelloSAT"),
        "no_certificado_sat": timbre.get("NoCertificadoSAT"), "rfc_prov_certif": timbre.get("RfcProvCertif"),
        "tiene_pdf": f.pdf is not None,
    })


@router.get("/{factura_id}/xml")
def xml(factura_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    f = db.get(Factura, _factura(db, usuario, factura_id).id, options=[undefer(Factura.xml)])
    nombre = f"{f.serie}{f.folio}_{f.receptor_rfc}.xml"
    return Response(f.xml.encode("utf-8"), media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nombre)}"})


@router.get("/{factura_id}/pdf")
def pdf(factura_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """El PDF del PAC, si lo regresó (el PAC de prueba no lo da: se imprime la página)."""
    f = db.get(Factura, _factura(db, usuario, factura_id).id, options=[undefer(Factura.pdf)])
    if not f.pdf:
        raise HTTPException(status_code=404, detail="Esta factura no tiene PDF del PAC; usa Imprimir")
    nombre = f"{f.serie}{f.folio}_{f.receptor_rfc}.pdf"
    return Response(f.pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nombre)}"})
