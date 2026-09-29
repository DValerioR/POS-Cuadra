from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Categoria, Negocio, Producto, Usuario
from app.schemas.producto import ProductoCreate, ProductoOut, ProductoUpdate
from app.services.precios import redondear_precio_venta

router = APIRouter(prefix="/productos", tags=["productos"])


@router.get("", response_model=list[ProductoOut])
def listar_productos(
    q: str | None = None,
    solo_revision: bool = False,
    limite: int = Query(50, le=500),
    desplazamiento: int = 0,
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    stmt = select(Producto).where(Producto.negocio_id == usuario.negocio_id)
    if q:
        # Por nombre parcial, o por clave exacta (lo que manda el escáner).
        # La clave se compara sin ceros a la izquierda: ver ix_productos_clave_sin_ceros.
        condiciones = [Producto.nombre.ilike(f"%{q}%"), Producto.clave == q]
        if q.lstrip("0"):
            condiciones.append(func.ltrim(Producto.clave, "0") == q.lstrip("0"))
        stmt = stmt.where(or_(*condiciones))
    if solo_revision:
        stmt = stmt.where(Producto.requiere_revision.is_(True))
    stmt = stmt.order_by(Producto.nombre, Producto.id).limit(limite).offset(desplazamiento)
    return db.scalars(stmt).all()


def _obtener(db: Session, usuario: Usuario, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None or producto.negocio_id != usuario.negocio_id:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto


def _guardar(db: Session, producto: Producto) -> Producto:
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
    return _guardar(db, producto)


@router.get("/{producto_id}", response_model=ProductoOut)
def obtener_producto(producto_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    return _obtener(db, usuario, producto_id)


@router.put("/{producto_id}", response_model=ProductoOut)
def actualizar_producto(
    producto_id: int, datos: ProductoUpdate, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)
):
    producto = _obtener(db, usuario, producto_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(producto, campo, valor)
    return _guardar(db, producto)


@router.delete("/{producto_id}", response_model=ProductoOut)
def desactivar_producto(producto_id: int, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """No borra el producto (queda historial de ventas/lotes); solo lo marca inactivo."""
    producto = _obtener(db, usuario, producto_id)
    producto.activo = False
    db.commit()
    db.refresh(producto)
    return producto
