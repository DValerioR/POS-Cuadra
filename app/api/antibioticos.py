from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.entradas import _exacto
from app.core.auth import solo_admin, usuario_actual
from app.core.database import get_db
from app.models import Lote, Producto, Usuario
from app.services import antibioticos, reporte_antibioticos
from app.services.errores import ERRORES_NEGOCIO, NoEncontrado, a_http

router = APIRouter(prefix="/antibioticos", tags=["antibióticos"])


class RecetaIn(BaseModel):
    medico: str = Field(max_length=200)
    cedula: str = Field(max_length=20)
    domicilio: str | None = Field(default=None, max_length=300)
    fecha_receta: date | None = None


class MarcaIn(BaseModel):
    antibiotico: bool


@router.get("/libro")
def libro(desde: date, hasta: date, producto_id: int | None = None, usuario: Usuario = Depends(usuario_actual),
          db: Session = Depends(get_db)):
    """Movimientos de los antibióticos en el periodo, con su existencia."""
    try:
        r = reporte_antibioticos.libro(db, usuario, desde, hasta, producto_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    return _exacto({
        "resumen": r.resumen,
        "movimientos": [reporte_antibioticos.a_dict(m, r.productos) for m in r.movimientos],
        "recetas_pendientes": reporte_antibioticos.contar_pendientes(db, usuario.negocio_id),
        "antibioticos": len(r.productos),
    })


@router.get("/libro/excel")
def libro_excel(desde: date, hasta: date, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        datos = reporte_antibioticos.excel(db, usuario, desde, hasta)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    nombre = f"antibioticos_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx"
    return Response(datos, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nombre)}"})


@router.get("/recetas-pendientes")
def recetas_pendientes(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        return _exacto(reporte_antibioticos.recetas_pendientes(db, usuario))
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.put("/recetas/{venta_id}")
def guardar_receta(venta_id: int, datos: RecetaIn, usuario: Usuario = Depends(usuario_actual),
                   db: Session = Depends(get_db)):
    """Datos de la receta de una venta con antibióticos (se capturan después de vender)."""
    try:
        r = reporte_antibioticos.guardar_receta(db, usuario, venta_id, datos.medico, datos.cedula, datos.domicilio,
                                                datos.fecha_receta)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return _exacto({"venta_id": r.venta_id, "medico": r.medico_nombre, "cedula": r.cedula, "domicilio": r.domicilio,
                    "fecha": r.fecha_receta})


@router.get("/medicos")
def medicos(q: str = Query("", max_length=100), usuario: Usuario = Depends(usuario_actual),
            db: Session = Depends(get_db)):
    """Médicos ya capturados, por cédula o nombre (para no volver a escribirlos)."""
    try:
        return reporte_antibioticos.buscar_medicos(db, usuario, q)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/productos")
def productos(q: str = Query("", max_length=100), usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """La lista de antibióticos; con `q`, busca en todo el catálogo para marcar o desmarcar."""
    filtro = [Producto.negocio_id == usuario.negocio_id]
    if q.strip():
        for palabra in q.split():
            filtro.append(func.unaccent(Producto.nombre).ilike(func.unaccent(f"%{palabra}%")) | (Producto.clave == palabra))
    else:
        filtro.append(Producto.antibiotico.is_(True))
    filas = db.execute(
        select(Producto, func.coalesce(func.sum(Lote.cantidad), 0))
        .outerjoin(Lote, Lote.producto_id == Producto.id)
        .where(*filtro).group_by(Producto.id).order_by(Producto.nombre).limit(1000 if not q.strip() else 100)
    ).all()
    return _exacto([{"id": p.id, "clave": p.clave, "nombre": p.nombre, "antibiotico": p.antibiotico,
                     "manual": p.antibiotico_manual, "activo": p.activo, "existencia": existencia}
                    for p, existencia in filas])


@router.put("/productos/{producto_id}")
def marcar(producto_id: int, datos: MarcaIn, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Marca o desmarca un producto a mano (el sistema ya no lo cambia solo)."""
    p = db.get(Producto, producto_id)
    if p is None or p.negocio_id != usuario.negocio_id:
        raise a_http(NoEncontrado("Producto no encontrado"))
    antibioticos.marcar_a_mano(p, datos.antibiotico)
    db.commit()
    return {"id": p.id, "antibiotico": p.antibiotico, "manual": p.antibiotico_manual}


@router.post("/detectar")
def detectar(usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Revisa otra vez todo el catálogo por nombre (respeta lo marcado a mano)."""
    r = antibioticos.detectar_todos(db, usuario.negocio_id)
    db.commit()
    return r
