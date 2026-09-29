from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.negocio import Negocio
from app.models.producto import Producto
from app.schemas.producto import ProductoCreate, ProductoOut, ProductoUpdate
from app.services.precios import redondear_precio_venta

router = APIRouter(prefix="/productos", tags=["productos"])


@router.get("", response_model=list[ProductoOut])
def listar_productos(negocio_id: int, q: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Producto).where(Producto.negocio_id == negocio_id)
    if q:
        # Por nombre parcial, o por clave exacta (lo que manda el escáner).
        # La clave se compara sin ceros a la izquierda: ver ix_productos_clave_sin_ceros.
        condiciones = [Producto.nombre.ilike(f"%{q}%"), Producto.clave == q]
        if q.lstrip("0"):
            condiciones.append(func.ltrim(Producto.clave, "0") == q.lstrip("0"))
        stmt = stmt.where(or_(*condiciones))
    return db.scalars(stmt).all()


def _guardar(db: Session, producto: Producto) -> Producto:
    negocio = db.get(Negocio, producto.negocio_id)
    if negocio is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
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
def crear_producto(datos: ProductoCreate, db: Session = Depends(get_db)):
    producto = Producto(**datos.model_dump())
    db.add(producto)
    return _guardar(db, producto)


@router.get("/{producto_id}", response_model=ProductoOut)
def obtener_producto(producto_id: int, db: Session = Depends(get_db)):
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto


@router.put("/{producto_id}", response_model=ProductoOut)
def actualizar_producto(producto_id: int, datos: ProductoUpdate, db: Session = Depends(get_db)):
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(producto, campo, valor)
    return _guardar(db, producto)


@router.delete("/{producto_id}", response_model=ProductoOut)
def desactivar_producto(producto_id: int, db: Session = Depends(get_db)):
    """No borra el producto (queda historial de ventas/lotes); solo lo marca inactivo."""
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    producto.activo = False
    db.commit()
    db.refresh(producto)
    return producto
