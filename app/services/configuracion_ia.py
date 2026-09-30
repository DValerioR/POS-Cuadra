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
    return {"ok": True, "mensaje": f"La clave funciona. Modelo: {modelo.display_name}."}
