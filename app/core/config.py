import os
import re
import tempfile
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# El .env de la raíz del proyecto (también lo actualiza la pantalla de la
# clave de IA; ver services/configuracion_ia.py).
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_PATH, env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://usuario:password@localhost:5432/pos"
    # Cuánto dura una sesión desde que se inicia (aprox. un turno).
    horas_sesion: int = 12
    # Solo True si el servidor se sirve por HTTPS; en la red local es HTTP.
    cookie_segura: bool = False
    # Para mostrar fechas (tickets, reportes); en la base todo se guarda en UTC.
    zona_horaria: str = "America/Mexico_City"
    # Negocio que usa la pantalla de inicio de sesión cuando no se indica otro
    # (en la farmacia hay uno solo).
    negocio_predeterminado: int = 1
    # Clave de la API de Claude para leer facturas en PDF o imagen. Se captura
    # desde el programa (Configuración → Asistente de IA). Sin ella, esa
    # opción queda desactivada y lo demás funciona igual.
    anthropic_api_key: str | None = None
    modelo_ia: str = "claude-opus-5-5"
    # PAC para timbrar facturas. "simulado" = de prueba, sin validez fiscal
    # (ver app/facturacion/pac.py); vacío = facturación apagada.
    pac: str = "simulado"
    # Token de acceso de Mercado Pago (terminal Point para cobrar con
    # tarjeta). Se captura desde Configuración → Terminal Mercado Pago.
    mercadopago_token: str | None = None


settings = Settings()


def escribir_variable(variable: str, valor: str | None) -> None:
    """Pone, reemplaza o quita una línea VARIABLE=valor del .env sin tocar las
    demás (claves que se capturan desde el programa). Escribe a un archivo
    temporal y lo cambia de golpe, para que un corte a la mitad no deje el
    .env incompleto."""
    lineas = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    nuevas = [l for l in lineas if not re.match(rf"^\s*{variable}\s*=", l)]
    if valor is not None:
        nuevas.append(f"{variable}={valor}")
    contenido = "\n".join(nuevas) + "\n"
    fd, temporal = tempfile.mkstemp(dir=ENV_PATH.parent, prefix=".env.", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(contenido)
        os.replace(temporal, ENV_PATH)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise
