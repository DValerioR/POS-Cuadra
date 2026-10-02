"""Conexión con el PAC (Facturapi): guardar, quitar y probar la clave desde
el programa. Solo administradores (lo revisa el endpoint).

La clave vive en el .env como FACTURAPI_KEY y con ella PAC=facturapi; se
usa al momento, sin reiniciar el servidor. Al quitarla se regresa a
PAC=simulado (facturas de prueba). Nunca se regresa completa por el API.
"""

import re

from app.core import config
from app.core.config import settings
from app.facturacion.pac import PacFacturapi
from app.services.errores import OperacionInvalida

# Claves secretas de Facturapi: sk_test_... (pruebas) o sk_live_... (reales).
# El formato también evita que un salto de línea o un "=" metan otra variable en el .env.
FORMATO = re.compile(r"^sk_(test|live)_[A-Za-z0-9_\-]{10,300}$")


def estado() -> dict:
    clave = settings.facturapi_key if settings.pac == "facturapi" else None
    return {
        "pac": settings.pac or None,
        "configurada": bool(clave),
        "termina_en": clave[-4:] if clave else None,
        "de_prueba": settings.pac != "facturapi" or not clave or clave.startswith("sk_test_"),
    }


def guardar(clave: str) -> dict:
    clave = (clave or "").strip()
    if not FORMATO.match(clave):
        raise OperacionInvalida(
            "Esa no parece una clave secreta de Facturapi: debe empezar con sk_test_ o sk_live_ y no llevar espacios"
        )
    config.escribir_variable("FACTURAPI_KEY", clave)
    config.escribir_variable("PAC", "facturapi")
    settings.facturapi_key, settings.pac = clave, "facturapi"
    return estado()


def quitar() -> dict:
    config.escribir_variable("FACTURAPI_KEY", None)
    config.escribir_variable("PAC", "simulado")
    settings.facturapi_key, settings.pac = None, "simulado"
    return estado()


def probar() -> dict:
    if settings.pac != "facturapi" or not settings.facturapi_key:
        raise OperacionInvalida("Todavía no hay clave de Facturapi")
    return PacFacturapi(settings.facturapi_key).probar()
