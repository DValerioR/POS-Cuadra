from fastapi import APIRouter, Depends, Query, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.asistente import chat
from app.core.auth import solo_admin
from app.core.database import get_db
from app.models import Usuario
from app.services.errores import ERRORES_NEGOCIO, a_http

router = APIRouter(prefix="/asistente", tags=["asistente de IA"])


class PreguntaIn(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)
    conversacion_id: int | None = None


@router.post("/preguntar")
async def preguntar(datos: PreguntaIn, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Pregunta al asistente (solo admin). Tarda unos segundos: consulta la
    base de datos las veces que necesite antes de responder."""
    try:
        resultado = await run_in_threadpool(chat.preguntar, db, usuario, datos.texto, datos.conversacion_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return resultado


@router.get("/conversaciones")
def conversaciones(limite: int = Query(30, le=100), usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    return [{"id": c.id, "titulo": c.titulo, "updated_at": c.updated_at} for c in chat.listar(db, usuario, limite)]


@router.get("/conversaciones/{conversacion_id}")
def conversacion(conversacion_id: int, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    try:
        return chat.visibles(db, usuario, conversacion_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.delete("/conversaciones/{conversacion_id}", status_code=204)
def borrar(conversacion_id: int, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    try:
        chat.borrar(db, usuario, conversacion_id)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return Response(status_code=204)
