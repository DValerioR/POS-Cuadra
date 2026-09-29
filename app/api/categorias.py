from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Categoria, Producto, Usuario
from app.schemas.categoria import CategoriaCreate, CategoriaOut, CategoriaUpdate

router = APIRouter(prefix="/categorias", tags=["categorias"])


def _obtener(db: Session, usuario: Usuario, categoria_id: int) -> Categoria:
    categoria = db.get(Categoria, categoria_id)
    if categoria is None or categoria.negocio_id != usuario.negocio_id:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    return categoria


def _guardar(db: Session, categoria: Categoria) -> Categoria:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre")
    db.refresh(categoria)
    return categoria


@router.get("", response_model=list[CategoriaOut])
def listar_categorias(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    conteo = dict(db.execute(
        select(Producto.categoria_id, func.count())
        .where(Producto.negocio_id == usuario.negocio_id, Producto.categoria_id.is_not(None))
        .group_by(Producto.categoria_id)
    ).all())
    categorias = db.scalars(
        select(Categoria).where(Categoria.negocio_id == usuario.negocio_id).order_by(Categoria.nombre)
    ).all()
    return [CategoriaOut.model_validate(c).model_copy(update={"productos": conteo.get(c.id, 0)}) for c in categorias]


@router.post("", response_model=CategoriaOut, status_code=201)
def crear_categoria(datos: CategoriaCreate, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    categoria = Categoria(negocio_id=usuario.negocio_id, **datos.model_dump())
    db.add(categoria)
    return _guardar(db, categoria)


@router.get("/{categoria_id}", response_model=CategoriaOut)
def obtener_categoria(categoria_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    return _obtener(db, usuario, categoria_id)


@router.put("/{categoria_id}", response_model=CategoriaOut)
def actualizar_categoria(
    categoria_id: int, datos: CategoriaUpdate, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)
):
    categoria = _obtener(db, usuario, categoria_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(categoria, campo, valor)
    return _guardar(db, categoria)


@router.delete("/{categoria_id}", status_code=204)
def eliminar_categoria(categoria_id: int, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    db.delete(_obtener(db, usuario, categoria_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="La categoría tiene productos; muévelos antes de borrarla")
