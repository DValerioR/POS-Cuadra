from datetime import date
from decimal import Decimal
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from app.core.auth import usuario_actual
from app.core.database import get_db
from app.importador import ia_facturas
from app.importador.cfdi import XmlInvalido, leer_cfdi
from app.models import ArchivoFactura, Entrada, Pedido, PedidoEntrada, Producto, Proveedor, TipoUso, Usuario
from app.services import entradas, pedidos, usos
from app.services.errores import ERRORES_NEGOCIO, NoEncontrado, OperacionInvalida, a_http

router = APIRouter(tags=["entradas de mercancía"])


def _exacto(valor):
    """Cantidades y dinero como texto exacto ("12.50"), igual que el resto
    del API, en lugar de números de punto flotante."""
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, dict):
        return {k: _exacto(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_exacto(v) for v in valor]
    return valor


# --- Proveedores ----------------------------------------------------------------

class ProveedorIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    rfc: str | None = Field(default=None, max_length=13)


class ProveedorOut(BaseModel):
    id: int
    nombre: str
    rfc: str | None
    activo: bool


@router.get("/proveedores", response_model=list[ProveedorOut])
def listar_proveedores(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    return db.scalars(select(Proveedor).where(Proveedor.negocio_id == usuario.negocio_id).order_by(Proveedor.nombre)).all()


@router.post("/proveedores", response_model=ProveedorOut, status_code=201)
def crear_proveedor(datos: ProveedorIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        p = entradas.crear_proveedor(db, usuario, datos.nombre, datos.rfc)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return p


# --- Leer una factura -------------------------------------------------------------

async def _archivo(request: Request, usuario: Usuario, db: Session) -> ArchivoFactura:
    nombre = unquote(request.headers.get("x-nombre-archivo", "factura"))
    return entradas.guardar_archivo(db, usuario, nombre, await request.body())


@router.post("/entradas/leer-xml")
async def leer_xml(request: Request, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Lee el XML del CFDI (sin IA) y regresa el borrador para revisar. El
    cuerpo es el archivo tal cual; el nombre va en X-Nombre-Archivo."""
    try:
        archivo = await _archivo(request, usuario, db)
        if archivo.tipo != "application/xml":
            raise OperacionInvalida("Ese archivo no es un XML; para PDF o fotos usa la lectura con IA")
        leida = leer_cfdi(archivo.datos)
        resultado = entradas.borrador(db, usuario, leida, archivo)
    except XmlInvalido as e:
        db.rollback()
        raise a_http(OperacionInvalida(str(e)))
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return _exacto(resultado)


@router.post("/entradas/leer-ia")
async def leer_con_ia(request: Request, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Lee un PDF o una foto de la factura con la API de Claude y regresa el
    borrador para revisar (lo dudoso va marcado). Tarda unos segundos."""
    try:
        archivo = await _archivo(request, usuario, db)
        if archivo.tipo == "application/xml":
            raise OperacionInvalida("Es un XML: usa \"Subir XML\", que lo lee exacto y sin costo")
        usos.revisar(db, usuario.negocio_id, TipoUso.IA)
        leida = await run_in_threadpool(ia_facturas.leer_con_ia, archivo.datos, archivo.tipo)
        usos.registrar(db, usuario.negocio_id, TipoUso.IA, "lectura_factura")
        resultado = entradas.borrador(db, usuario, leida, archivo)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return _exacto(resultado)


@router.get("/entradas/producto/{producto_id}")
def datos_de_producto(producto_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Costo, precio, impuestos y margen de un producto, para un renglón que
    se agrega o se relaciona a mano en la revisión."""
    try:
        entradas._validar_rol(usuario)
        producto = db.get(Producto, producto_id)
        if producto is None or producto.negocio_id != usuario.negocio_id:
            raise NoEncontrado("Producto no encontrado")
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    return _exacto(entradas.datos_producto(db, producto))


# --- Registrar ----------------------------------------------------------------------

class RenglonIn(BaseModel):
    producto_id: int
    cantidad: Decimal = Field(gt=0)
    costo_unitario: Decimal = Field(ge=0)
    factor: Decimal = Field(default=Decimal(1), gt=0)
    numero_lote: str | None = Field(default=None, max_length=40)
    caducidad: date | None = None
    descripcion_proveedor: str | None = Field(default=None, max_length=500)
    clave_proveedor: str | None = Field(default=None, max_length=60)
    aplicar_precio: bool = False


class EntradaIn(BaseModel):
    proveedor_id: int
    folio: str = Field(min_length=1, max_length=60)
    fecha_recepcion: date
    fecha_factura: date | None = None
    origen: str = "manual"
    total_factura: Decimal | None = None
    archivo_id: int | None = None
    notas: str | None = Field(default=None, max_length=500)
    pedido_id: int | None = None  # el pedido que surte esta factura, si hay
    # False: solo historial (la mercancía ya estaba en el inventario).
    afecta_inventario: bool = True
    renglones: list[RenglonIn] = Field(min_length=1, max_length=500)


def _pedido_de(db: Session, e: Entrada) -> dict | None:
    """El pedido que surtió esta entrada, si se ligó a uno."""
    p = db.scalar(select(Pedido).join(PedidoEntrada, PedidoEntrada.pedido_id == Pedido.id)
                  .where(PedidoEntrada.entrada_id == e.id))
    return {"id": p.id, "folio": p.folio, "estado": p.estado.value} if p else None


def _resumen(db: Session, e: Entrada) -> dict:
    return {
        "id": e.id, "proveedor": e.proveedor.nombre, "folio": e.folio, "fecha_factura": e.fecha_factura,
        "fecha_recepcion": e.fecha_recepcion, "origen": e.origen, "subtotal": e.subtotal,
        "afecta_inventario": e.afecta_inventario,
        "total_factura": e.total_factura, "productos": len(e.renglones),
        "piezas": sum((r.piezas for r in e.renglones), Decimal(0)),
        "precios_cambiados": sum(1 for r in e.renglones if r.precio_nuevo is not None),
        "archivo_id": db.scalar(select(ArchivoFactura.id).where(ArchivoFactura.entrada_id == e.id)),
        "pedido": _pedido_de(db, e),
        "created_at": e.created_at,
    }


@router.post("/entradas", status_code=201)
def registrar(datos: EntradaIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Confirma la entrada: lotes, costos, precios elegidos y equivalencias."""
    try:
        entrada = entradas.registrar(
            db, usuario, datos.proveedor_id, datos.folio, datos.fecha_recepcion,
            [entradas.RenglonEntrada(**r.model_dump()) for r in datos.renglones],
            datos.origen, datos.fecha_factura, datos.total_factura, datos.archivo_id, datos.notas,
            afecta_inventario=datos.afecta_inventario,
        )
        if datos.pedido_id is not None:
            pedidos.ligar_entrada(db, usuario, datos.pedido_id, entrada.id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    db.refresh(entrada)
    return _exacto(_resumen(db, entrada))


@router.get("/entradas")
def listar(
    limite: int = Query(30, le=200), usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db),
):
    """Entradas recientes, la más nueva primero."""
    try:
        entradas._validar_rol(usuario)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    lista = db.scalars(
        select(Entrada).where(Entrada.negocio_id == usuario.negocio_id).order_by(Entrada.id.desc()).limit(limite)
    ).all()
    return _exacto([_resumen(db, e) for e in lista])


@router.get("/entradas/{entrada_id}")
def detalle(entrada_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        entradas._validar_rol(usuario)
        e = db.get(Entrada, entrada_id)
        if e is None or e.negocio_id != usuario.negocio_id:
            raise NoEncontrado("Entrada no encontrada")
    except ERRORES_NEGOCIO as err:
        raise a_http(err)
    nombres = dict(db.execute(select(Producto.id, Producto.nombre).where(
        Producto.id.in_({r.producto_id for r in e.renglones}))).all())
    return _exacto({**_resumen(db, e), "notas": e.notas, "renglones": [
        {
            "producto_id": r.producto_id, "producto": nombres.get(r.producto_id), "descripcion_proveedor": r.descripcion_proveedor,
            "cantidad": r.cantidad, "factor": r.factor, "piezas": r.piezas, "costo_unitario": r.costo_unitario,
            "costo_pieza": r.costo_pieza, "numero_lote": r.numero_lote, "caducidad": r.caducidad,
            "costo_anterior": r.costo_anterior, "precio_anterior": r.precio_anterior, "precio_nuevo": r.precio_nuevo,
        }
        for r in e.renglones
    ]})


@router.get("/entradas/archivos/{archivo_id}")
def ver_archivo(archivo_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """El archivo original de la factura."""
    try:
        entradas._validar_rol(usuario)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    a = db.get(ArchivoFactura, archivo_id, options=[undefer(ArchivoFactura.datos)])
    if a is None or a.negocio_id != usuario.negocio_id:
        raise a_http(NoEncontrado("Archivo no encontrado"))
    return Response(a.datos, media_type=a.tipo, headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(a.nombre, safe='')}",
        "Cache-Control": "private, max-age=3600",
    })
