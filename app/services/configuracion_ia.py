"""Clave de la API de Claude (asistente de IA): guardarla, quitarla y probarla
desde el programa. Solo administradores (lo revisa el endpoint).

La clave vive en el .env como ANTHROPIC_API_KEY y en `settings`, que se
actualiza al momento: no hace falta reiniciar el servidor. Nunca se regresa
completa por el API; solo si está configurada y sus últimos 4 caracteres.
"""

import re

import anthropic

from app.core import config
from app.core.config import settings
from app.services.errores import OperacionInvalida

VARIABLE = "ANTHROPIC_API_KEY"
# Formato de las claves de Anthropic. Además evita que un salto de línea o un
# "=" pegados por error metan otra variable en el .env.
FORMATO = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,300}$")


def estado() -> dict:
    clave = settings.anthropic_api_key
    return {"configurada": bool(clave), "termina_en": clave[-4:] if clave else None, "modelo": settings.modelo_ia}


def guardar(clave: str) -> dict:
    clave = (clave or "").strip()
    if not FORMATO.match(clave):
        raise OperacionInvalida(
            "Esa no parece una clave de la API de Claude: debe empezar con sk-ant- y no llevar espacios"
        )
    config.escribir_variable(VARIABLE, clave)
    settings.anthropic_api_key = clave
    return estado()


def quitar() -> dict:
    config.escribir_variable(VARIABLE, None)
    settings.anthropic_api_key = None
    return estado()


def cliente() -> anthropic.Anthropic:
    if not settings.anthropic_api_key:
        raise OperacionInvalida("Falta la clave de la API de Claude (Configuración → Asistente de IA)")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120.0, max_retries=2)


def probar() -> dict:
    """Confirma que la clave sirve y que hay internet, consultando el modelo
    que se usa (no gasta tokens)."""
    try:
        modelo = cliente().models.retrieve(settings.modelo_ia)
    except anthropic.AuthenticationError:
        return {"ok": False, "mensaje": "La clave no es válida o fue revocada."}
    except anthropic.PermissionDeniedError:
        return {"ok": False, "mensaje": "La clave no tiene permiso para usar la API."}
    except anthropic.NotFoundError:
        return {"ok": False, "mensaje": f"La cuenta no tiene acceso al modelo {settings.modelo_ia}."}
    except anthropic.APIConnectionError:
        return {"ok": False, "mensaje": "No hay conexión con la API de Claude. ¿El servidor tiene internet?"}
    except anthropic.APIStatusError as e:
        return {"ok": False, "mensaje": f"La API respondió con un error ({e.status_code}). Intenta más tarde."}
    return {"ok": True, "mensaje": f"La clave funciona. Modelo: {modelo.display_name}. "
                                   "Esta prueba no revisa el saldo; ese se ve en console.anthropic.com."}


# --- Errores de la API en español llano ---------------------------------------

SALDO_AGOTADO = ("Se acabó el saldo de la IA. Vender y todo lo demás funciona igual; "
                 "avisa a tu proveedor de Cuadra para que lo recargue.")
# Así responde Anthropic cuando la cuenta se queda sin crédito ("Your credit
# balance is too low...") o el workspace llega a su límite de gasto ("You
# have reached your specified ... API usage limits"). Llega como un 400, igual
# que una solicitud mal hecha, así que se distingue por el texto.
_TEXTOS_SALDO = ("credit balance", "usage limit", "spend limit", "plans & billing", "purchase credits")


def es_saldo_agotado(e: Exception) -> bool:
    if not isinstance(e, (anthropic.BadRequestError, anthropic.PermissionDeniedError)):
        return False
    texto = f"{e.message} {e.body}".lower()
    return any(t in texto for t in _TEXTOS_SALDO)


def mensaje_error(e: anthropic.APIError, solicitud_invalida: str | None = None) -> str:
    """El mensaje para la persona que estaba usando la función. Con
    `solicitud_invalida` se cambia el de un 400 que no es de saldo (por
    ejemplo, un archivo que la API no aceptó)."""
    if es_saldo_agotado(e):
        return SALDO_AGOTADO
    if isinstance(e, anthropic.AuthenticationError):
        return "La clave de la API de Claude no es válida; revísala en Configuración → Asistente de IA"
    if isinstance(e, anthropic.PermissionDeniedError):
        return "La clave de la API de Claude no tiene permiso para esto; revísala en Configuración → Asistente de IA"
    if isinstance(e, anthropic.RateLimitError):
        return "La API de Claude está ocupada; intenta en un minuto"
    if isinstance(e, anthropic.APIConnectionError):
        return "No hay conexión con la API de Claude; revisa el internet del servidor"
    if isinstance(e, anthropic.BadRequestError) and solicitud_invalida:
        return f"{solicitud_invalida} ({e.message})"
    if isinstance(e, anthropic.APIStatusError) and e.status_code in (500, 529):
        return "La IA de Claude tiene problemas en este momento; intenta en unos minutos"
    if isinstance(e, anthropic.APIStatusError):
        return f"La API de Claude respondió con un error ({e.status_code}); intenta más tarde"
    return "La API de Claude no respondió; intenta más tarde"
