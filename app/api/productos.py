from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Categoria, Negocio, PrecioHistorial, Producto, Usuario
from app.schemas.producto import ProductoCreate, ProductoOut, ProductoUpdate
from app.services import catalogo, revision_catalogo
from app.services.errores import ERRORES_NEGOCIO, a_http
from app.services.precios import redondear_precio_venta

router = APIRouter(prefix="/productos", tags=["productos"])


class Filtros:
    """Filtros de la lista de productos (búsqueda, catálogo y lector)."""

    def __init__(
        self,
        q: str | None = None,
        clave: str | None = None,
        solo_revision: bool = False,
        solo_activos: bool = False,
        solo_inactivos: bool = False,
        sin_precio: bool = False,
        sin_categoria: bool = False,
        categoria_id: int | None = None,
    ):
        self.q, self.clave = q, clave
        self.solo_revision, self.solo_activos, self.solo_inactivos = solo_revision, solo_activos, solo_inactivos
        self.sin_precio, self.sin_categoria, self.categoria_id = sin_precio, sin_categoria, categoria_id

    def aplicar(self, stmt, negocio_id: int):
        stmt = stmt.where(Producto.negocio_id == negocio_id)
        if q := (self.q or "").strip():
            # Por nombre: cada palabra en cualquier parte, sin importar acentos ni
            # mayúsculas ("amox 500" encuentra "AMOXICILINA 500MG").
            por_nombre = and_(*(
                func.unaccent(Producto.nombre).ilike(func.unaccent(f"%{palabra}%")) for palabra in q.split()
            ))
            # O por clave exacta (lo que manda el escáner), sin ceros a la
            # izquierda: ver ix_productos_clave_sin_ceros.
            condiciones = [por_nombre, Producto.clave == q]
            if q.lstrip("0"):
                condiciones.append(func.ltrim(Producto.clave, "0") == q.lstrip("0"))
            stmt = stmt.where(or_(*condiciones))
        if clave := (self.clave or "").strip():
            # Solo por clave exacta (el lector de código de barras), sin mezclar
            # coincidencias por nombre.
            condiciones = [Producto.clave == clave]
            if clave.lstrip("0"):
                condiciones.append(func.ltrim(Producto.clave, "0") == clave.lstrip("0"))
            stmt = stmt.where(or_(*condiciones))
        if self.solo_activos:
            stmt = stmt.where(Producto.activo.is_(True))
        if self.solo_inactivos:
            stmt = stmt.where(Producto.activo.is_(False))
        if self.solo_revision:
            stmt = stmt.where(Producto.requiere_revision.is_(True))
        if self.sin_precio:
            stmt = stmt.where(Producto.precio_venta.is_(None))
        if self.sin_categoria:
            stmt = stmt.where(Producto.categoria_id.is_(None))
        if self.categoria_id is not None:
            stmt = stmt.where(Producto.categoria_id == self.categoria_id)
        return stmt


@router.get("", response_model=list[ProductoOut])
def listar_productos(
    filtros: Filtros = Depends(),
    limite: int = Query(50, le=500),
    desplazamiento: int = 0,
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    stmt = filtros.aplicar(select(Producto), usuario.negocio_id)
    return db.scalars(stmt.order_by(Producto.nombre, Producto.id).limit(limite).offset(desplazamiento)).all()


@router.get("/contar")
def contar_productos(filtros: Filtros = Depends(), usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Cuántos productos cumplen los filtros (para paginar)."""
    return {"total": db.scalar(filtros.aplicar(select(func.count()).select_from(Producto), usuario.negocio_id))}


@router.get("/revision/excel")
def revision_excel(usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Reporte de revisión del catálogo en Excel: cada producto con algún
    problema (sin costo, sin clave SAT, IVA dudoso...) y la clave SAT que le
    correspondería. No cambia nada."""
    fecha = datetime.now().strftime("%Y%m%d")
    return Response(
        revision_catalogo.excel(db, usuario.negocio_id),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="revision_catalogo_{fecha}.xlsx"'},
    )


@router.get("/revision/claves-sat")
def claves_sat_sugeridas(usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Productos sin clave SAT o con clave dudosa que tienen una sugerida por su nombre."""
    return revision_catalogo.claves_sugeridas(db, usuario.negocio_id)


class ClaveSatIn(BaseModel):
    producto_id: int
    clave_sat: str = Field(pattern=r"^\d{8}$")


class AplicarClavesIn(BaseModel):
    cambios: list[ClaveSatIn] = Field(min_length=1, max_length=20000)


@router.post("/claves-sat")
def aplicar_claves_sat(datos: AplicarClavesIn, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Pone las claves SAT elegidas (las sugeridas que aprobó el administrador)."""
    try:
        n = revision_catalogo.aplicar_claves(db, usuario.negocio_id, [(c.producto_id, c.clave_sat) for c in datos.cambios])
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return {"cambiados": n}


class CambioEnGrupoIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    categoria_id: int | None = None
    quitar_categoria: bool = False
    iva_porcentaje: Decimal | None = None
    # Con IVA: True = el precio sin impuestos se queda igual (el precio al
    # público sube o baja); False = el precio al público se queda igual.
    ajustar_precio: bool = False
    revisado: bool = False


@router.post("/en-grupo")
def cambiar_en_grupo(datos: CambioEnGrupoIn, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Aplica categoría, IVA y/o "ya revisado" a varios productos a la vez."""
    try:
        n = catalogo.cambiar_en_grupo(
            db, usuario, datos.ids, datos.categoria_id, datos.quitar_categoria,
            datos.iva_porcentaje, datos.ajustar_precio, datos.revisado,
        )
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return {"productos": n}


def _obtener(db: Session, usuario: Usuario, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None or producto.negocio_id != usuario.negocio_id:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto


def _guardar(db: Session, producto: Producto, precio_anterior: Decimal | None, usuario: Usuario) -> Producto:
    if producto.categoria_id is not None:
        categoria = db.get(Categoria, producto.categoria_id)
        if categoria is None or categoria.negocio_id != producto.negocio_id:
            db.rollback()
            raise HTTPException(status_code=404, detail="Categoría no encontrada")
    negocio = db.get(Negocio, producto.negocio_id)
    if producto.precio_venta is not None:
        producto.precio_venta = redondear_precio_venta(
            producto.precio_venta, negocio.redondeo_precio_venta, producto.precio_maximo_publico
        )
    try:
        db.flush()
        catalogo.registrar_precio(db, producto, precio_anterior, usuario.id, "Catálogo")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un producto con esa clave")
    db.refresh(producto)
    return producto


@router.post("", response_model=ProductoOut, status_code=201)
def crear_producto(datos: ProductoCreate, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    producto = Producto(negocio_id=usuario.negocio_id, **datos.model_dump())
    db.add(producto)
    return _guardar(db, producto, None, usuario)


@router.get("/{producto_id}", response_model=ProductoOut)
def obtener_producto(producto_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    return _obtener(db, usuario, producto_id)


@router.put("/{producto_id}", response_model=ProductoOut)
def actualizar_producto(
    producto_id: int, datos: ProductoUpdate, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)
):
    producto = _obtener(db, usuario, producto_id)
    anterior = producto.precio_venta
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(producto, campo, valor)
    return _guardar(db, producto, anterior, usuario)


class PrecioHistorialOut(BaseModel):
    id: int
    precio_anterior: Decimal | None
    precio_nuevo: Decimal | None
    origen: str
    usuario: str | None
    created_at: datetime


@router.get("/{producto_id}/precios", response_model=list[PrecioHistorialOut])
def historial_de_precios(
    producto_id: int, limite: int = Query(20, le=200),
    usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db),
):
    """Cambios del precio de venta, del más reciente al más viejo."""
    _obtener(db, usuario, producto_id)
    filas = db.execute(
        select(PrecioHistorial, Usuario.nombre_completo)
        .outerjoin(Usuario, Usuario.id == PrecioHistorial.usuario_id)
        .where(PrecioHistorial.producto_id == producto_id)
        .order_by(PrecioHistorial.id.desc()).limit(limite)
    ).all()
    return [
        PrecioHistorialOut(
            id=h.id, precio_anterior=h.precio_anterior, precio_nuevo=h.precio_nuevo, origen=h.origen,
            usuario=nombre, created_at=h.created_at,
        )
        for h, nombre in filas
    ]


@router.delete("/{producto_id}", response_model=ProductoOut)
def desactivar_producto(producto_id: int, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """No borra el producto (queda historial de ventas/lotes); solo lo marca inactivo."""
    producto = _obtener(db, usuario, producto_id)
    producto.activo = False
    db.commit()
    db.refresh(producto)
    return producto
