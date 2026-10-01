"""WhatsApp: el webhook al que Meta manda los mensajes de los clientes (público,
protegido con la firma de Meta), la pantalla Conversaciones de WhatsApp
(personal), la configuración (administradores) y el simulador del demo.
Ver app/whatsapp/bot.py y docs/WHATSAPP.md."""

import hashlib
import hmac
import logging
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, object_session

from app.core import config
from app.core.auth import solo_admin, usuario_actual
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models import ConversacionWhatsApp, MensajeWhatsApp, Usuario
from app.services.errores import ERRORES_NEGOCIO, OperacionInvalida, a_http
from app.whatsapp import bot
from app.whatsapp import cliente as whatsapp

log = logging.getLogger(__name__)
router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

FOTO_MAXIMA = 8 * 1024 * 1024


# --- Webhook (Meta) ---------------------------------------------------------------

@router.get("/webhook")
def verificar_webhook(modo: str = Query("", alias="hub.mode"), clave: str = Query("", alias="hub.verify_token"),
                      reto: str = Query("", alias="hub.challenge")):
    """Meta lo llama una vez al dar de alta el webhook, con la clave que se le dio."""
    esperada = settings.whatsapp_verify_token
    if modo == "subscribe" and esperada and hmac.compare_digest(clave, esperada):
        return Response(reto, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Clave de verificación incorrecta")


def firma_valida(cuerpo: bytes, firma: str | None) -> bool:
    secreto = settings.whatsapp_app_secret
    if not secreto or not firma or not firma.startswith("sha256="):
        return False
    esperada = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(firma[7:], esperada)


def mensajes_del_aviso(datos: dict) -> list[dict]:
    """Los mensajes de clientes que trae un aviso de Meta (se ignoran los
    avisos de "entregado", "leído", etc.)."""
    salida = []
    for entrada in datos.get("entry", []):
        for cambio in entrada.get("changes", []):
            valor = cambio.get("value", {})
            nombres = {c.get("wa_id"): c.get("profile", {}).get("name") for c in valor.get("contacts", [])}
            for m in valor.get("messages", []):
                tipo = m.get("type")
                texto = None
                media = None
                if tipo == "text":
                    texto = m.get("text", {}).get("body")
                elif tipo == "image":
                    media = m.get("image", {}).get("id")
                    texto = m.get("image", {}).get("caption")
                elif tipo == "button":
                    texto = m.get("button", {}).get("text")
                elif tipo == "interactive":
                    i = m.get("interactive", {})
                    texto = (i.get("button_reply") or i.get("list_reply") or {}).get("title")
                else:
                    texto = f"[El cliente envió un mensaje de tipo «{tipo}», que el bot no puede ver]"
                salida.append({"telefono": m.get("from"), "nombre": nombres.get(m.get("from")), "wa_id": m.get("id"),
                               "texto": texto, "media_id": media})
    return salida


def procesar(mensaje: dict) -> None:
    """Contesta un mensaje en el fondo (fuera de la petición de Meta, que
    debe responderse rápido). Un mensaje a la vez por cliente."""
    with bot.candado(mensaje["telefono"]):
        db = SessionLocal()
        try:
            imagen = tipo = None
            if mensaje.get("media_id"):
                try:
                    imagen, tipo = whatsapp.cliente().descargar_media(mensaje["media_id"])
                    if len(imagen) > FOTO_MAXIMA:
                        imagen = None
                except whatsapp.ErrorWhatsApp as e:
                    log.warning("No se pudo descargar la foto: %s", e.mensaje)
                    mensaje["texto"] = (mensaje.get("texto") or "") + " [Mandó una foto que no se pudo descargar]"
            bot.recibir(db, settings.negocio_predeterminado, mensaje["telefono"], mensaje.get("nombre"),
                        mensaje.get("texto"), wa_id=mensaje.get("wa_id"), imagen=imagen, imagen_tipo=tipo)
        except Exception:
            log.exception("Falló el bot de WhatsApp")
            db.rollback()
        finally:
            db.close()


@router.post("/webhook")
async def recibir_webhook(request: Request, tareas: BackgroundTasks):
    cuerpo = await request.body()
    if not firma_valida(cuerpo, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="Firma inválida")
    try:
        datos = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON inválido")
    for m in mensajes_del_aviso(datos):
        if m["telefono"]:
            tareas.add_task(procesar, m)
    return {"ok": True}


# --- Conversaciones (personal) -----------------------------------------------------

def _conversacion_out(c: ConversacionWhatsApp) -> dict:
    ultimo = c.mensajes[-1] if c.mensajes else None
    return {
        "id": c.id, "telefono": c.telefono, "nombre": c.nombre, "estado": c.estado.value,
        "motivo_persona": c.motivo_persona, "persona_desde": c.persona_desde, "aviso_error": c.aviso_error,
        "atendida_por": (c_usuario.nombre_completo or c_usuario.nombre_usuario) if (c_usuario := _usuario(c)) else None,
        "ultimo_mensaje_at": c.ultimo_mensaje_at, "sin_leer": c.sin_leer, "puede_escribir": bot.puede_escribir(c),
        "ultimo": {"de": ultimo.de, "texto": ultimo.texto or ("Foto" if ultimo.imagen_tipo else "")} if ultimo else None,
    }


def _usuario(c: ConversacionWhatsApp) -> Usuario | None:
    return object_session(c).get(Usuario, c.atendida_por_id) if c.atendida_por_id else None


def _mensajes_out(c: ConversacionWhatsApp) -> list[dict]:
    db = object_session(c)
    nombres = {}
    salida = []
    for m in c.mensajes:
        quien = None
        if m.usuario_id:
            if m.usuario_id not in nombres:
                u = db.get(Usuario, m.usuario_id)
                nombres[m.usuario_id] = (u.nombre_completo or u.nombre_usuario) if u else None
            quien = nombres[m.usuario_id]
        salida.append({"id": m.id, "de": m.de, "texto": m.texto, "foto": bool(m.imagen_tipo), "quien": quien,
                       "error": m.error, "fecha": m.created_at})
    return salida


def _detalle(c: ConversacionWhatsApp) -> dict:
    return {**_conversacion_out(c), "mensajes": _mensajes_out(c)}


def _accion(db: Session, funcion, *args):
    try:
        resultado = funcion(db, *args)
    except ERRORES_NEGOCIO as e:
        db.rollback()
        raise a_http(e)
    db.commit()
    return resultado


@router.get("/conversaciones")
def listar_conversaciones(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    try:
        return [_conversacion_out(c) for c in bot.listar(db, usuario)]
    except ERRORES_NEGOCIO as e:
        raise a_http(e)


@router.get("/conversaciones/{conversacion_id}")
def ver_conversacion(conversacion_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """Abre la conversación (los mensajes quedan como leídos)."""
    c = _accion(db, bot.marcar_leida, usuario, conversacion_id)
    return _detalle(c)


@router.post("/conversaciones/{conversacion_id}/tomar")
def tomar(conversacion_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    return _detalle(_accion(db, bot.tomar, usuario, conversacion_id))


class Respuesta(BaseModel):
    texto: str = Field(min_length=1, max_length=bot.MAX_TEXTO)


@router.post("/conversaciones/{conversacion_id}/responder")
def responder(conversacion_id: int, datos: Respuesta, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    _accion(db, bot.responder, usuario, conversacion_id, datos.texto)
    return _detalle(bot.obtener(db, usuario, conversacion_id))


@router.post("/conversaciones/{conversacion_id}/regresar-al-bot")
def regresar_al_bot(conversacion_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    return _detalle(_accion(db, bot.regresar_al_bot, usuario, conversacion_id))


@router.get("/mensajes/{mensaje_id}/foto")
def foto(mensaje_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    m = db.get(MensajeWhatsApp, mensaje_id)
    if m is None or not m.imagen_tipo:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    try:
        bot.obtener(db, usuario, m.conversacion_id)
    except ERRORES_NEGOCIO as e:
        raise a_http(e)
    return Response(m.imagen, media_type=m.imagen_tipo, headers={"Cache-Control": "private, max-age=86400"})


# --- Configuración (administradores) ------------------------------------------------

VARIABLES = {
    "token": "WHATSAPP_TOKEN", "numero_id": "WHATSAPP_NUMERO_ID", "verify_token": "WHATSAPP_VERIFY_TOKEN",
    "app_secret": "WHATSAPP_APP_SECRET", "avisos_a": "WHATSAPP_AVISOS_A",
}


def _termina(valor: str | None) -> str | None:
    return valor[-4:] if valor else None


def estado_config() -> dict:
    return {
        "simulado": whatsapp._simulado is not None,
        "configurado": whatsapp.configurado(),
        "token": _termina(settings.whatsapp_token), "numero_id": settings.whatsapp_numero_id,
        "verify_token": bool(settings.whatsapp_verify_token), "app_secret": bool(settings.whatsapp_app_secret),
        "avisos_a": settings.whatsapp_avisos_a, "bot_activo": settings.whatsapp_bot_activo,
        "webhook_listo": bool(settings.whatsapp_verify_token and settings.whatsapp_app_secret),
        # Las que hay que dar de alta en Meta (categoría "Utilidad", idioma español de México).
        "plantillas": [{"nombre": p.nombre, "texto": p.texto} for p in whatsapp.PLANTILLAS.values()],
    }


@router.get("/configuracion")
def ver_configuracion(usuario: Usuario = Depends(solo_admin)):
    return estado_config()


class Configuracion(BaseModel):
    """Solo los campos que se mandan se cambian; "" quita el valor."""
    token: str | None = Field(default=None, max_length=1000)
    numero_id: str | None = Field(default=None, max_length=40)
    verify_token: str | None = Field(default=None, max_length=200)
    app_secret: str | None = Field(default=None, max_length=200)
    avisos_a: str | None = Field(default=None, max_length=30)
    bot_activo: bool | None = None


def _escribir(variable: str, valor: str | None) -> None:
    # En el demo (WhatsApp simulado) los cambios solo duran mientras corre: nunca tocan el .env real.
    if whatsapp._simulado is None:
        config.escribir_variable(variable, valor)


@router.put("/configuracion")
def guardar_configuracion(datos: Configuracion, usuario: Usuario = Depends(solo_admin)):
    cambios = datos.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        if campo == "bot_activo":
            continue
        valor = (valor or "").strip() or None
        if valor and campo != "avisos_a" and re.search(r"\s", valor):
            raise HTTPException(status_code=422, detail="No debe llevar espacios")
        if campo == "numero_id" and valor and not valor.isdigit():
            raise HTTPException(status_code=422, detail="El identificador del número son solo dígitos")
        if campo == "avisos_a" and valor:
            valor = whatsapp.numero(valor)
            if not valor:
                raise HTTPException(status_code=422, detail="El número para avisos debe tener 10 dígitos (o con lada de país)")
        _escribir(VARIABLES[campo], valor)
        setattr(settings, f"whatsapp_{campo}", valor)
    if "bot_activo" in cambios and cambios["bot_activo"] is not None:
        _escribir("WHATSAPP_BOT_ACTIVO", None if cambios["bot_activo"] else "false")
        settings.whatsapp_bot_activo = cambios["bot_activo"]
    return estado_config()


@router.post("/configuracion/probar-aviso")
def probar_aviso(usuario: Usuario = Depends(solo_admin)):
    """Manda la plantilla de "un cliente necesita atención" al número de avisos."""
    destino = whatsapp.numero(settings.whatsapp_avisos_a)
    if not destino:
        raise HTTPException(status_code=409, detail="Primero escribe el número para avisos")
    try:
        whatsapp.cliente().enviar_plantilla(destino, whatsapp.PLANTILLAS["atencion_cliente"],
                                            ["Prueba", "+520000000000", "Prueba del aviso desde el sistema"])
    except whatsapp.ErrorWhatsApp as e:
        raise HTTPException(status_code=409, detail=e.mensaje)
    return {"ok": True}


# --- Simulador (solo con WhatsApp simulado: demo y pruebas) ------------------------

class MensajeSimulado(BaseModel):
    telefono: str = Field(min_length=10, max_length=20)
    nombre: str | None = Field(default=None, max_length=60)
    texto: str = Field(min_length=1, max_length=bot.MAX_TEXTO)


def _solo_simulado() -> None:
    if whatsapp._simulado is None:
        raise HTTPException(status_code=404, detail="El simulador solo existe en el demo")


def _recibir_simulado(db: Session, usuario: Usuario, telefono: str, nombre: str | None, texto: str | None,
                      imagen: bytes | None = None, tipo: str | None = None) -> dict:
    _solo_simulado()
    numero = whatsapp.numero(telefono)
    if not numero:
        raise HTTPException(status_code=422, detail="Teléfono no válido")
    try:
        with bot.candado(numero):
            c = bot.recibir(db, usuario.negocio_id, numero, nombre, texto, imagen=imagen, imagen_tipo=tipo)
    except OperacionInvalida as e:
        raise a_http(e)
    db.refresh(c)
    return _detalle(c)


@router.post("/simular")
def simular(datos: MensajeSimulado, usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """Como si el cliente escribiera por WhatsApp (contesta el bot)."""
    return _recibir_simulado(db, usuario, datos.telefono, datos.nombre, datos.texto)


@router.post("/simular-foto")
async def simular_foto(request: Request, telefono: str, nombre: str | None = None,
                       usuario: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    from app.services import entradas

    datos = await request.body()
    tipo = entradas.tipo_de_archivo(datos)
    if not tipo or not tipo.startswith("image/"):
        raise HTTPException(status_code=422, detail="El archivo no es una foto")
    return _recibir_simulado(db, usuario, telefono, nombre, None, datos, tipo)
