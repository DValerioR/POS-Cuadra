"""Clave de la API de Claude (asistente de IA): guardarla, quitarla y probarla
desde el programa. Solo administradores (lo revisa el endpoint).

La clave vive en el .env como ANTHROPIC_API_KEY y en `settings`, que se
actualiza al momento: no hace falta reiniciar el servidor. Nunca se regresa
completa por el API; solo si está configurada y sus últimos 4 caracteres.
"""

import os
import re
import tempfile
from pathlib import Path

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


def _escribir_env(valor: str | None) -> None:
    """Pone, reemplaza o quita la línea ANTHROPIC_API_KEY del .env sin tocar
    las demás. Escribe a un archivo temporal y lo cambia de golpe, para que un
    corte a la mitad no deje el .env incompleto."""
    ruta: Path = config.ENV_PATH
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
    nuevas = [l for l in lineas if not re.match(rf"^\s*{VARIABLE}\s*=", l)]
    if valor is not None:
        nuevas.append(f"{VARIABLE}={valor}")
    contenido = "\n".join(nuevas) + "\n"
    fd, temporal = tempfile.mkstemp(dir=ruta.parent, prefix=".env.", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(contenido)
        os.replace(temporal, ruta)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise


def guardar(clave: str) -> dict:
    clave = (clave or "").strip()
    if not FORMATO.match(clave):
        raise OperacionInvalida(
            "Esa no parece una clave de la API de Claude: debe empezar con sk-ant- y no llevar espacios"
        )
    _escribir_env(clave)
    settings.anthropic_api_key = clave
    return estado()


def quitar() -> dict:
    _escribir_env(None)
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
