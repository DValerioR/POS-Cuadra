"""Cómo llega el ticket a la impresora. Cada caja elige su modo:

- RED: la impresora está en la red (Ethernet); el servidor le manda los
  bytes directo al puerto 9100 (estándar "raw" de las impresoras de tickets).
- AGENTE: la impresora está por USB en la computadora de mostrador; ahí
  corre agente_impresion/agente.py, que recibe los bytes por HTTP y se los
  pasa a Windows. El servidor se autentica con un token compartido.
- NINGUNA: no se imprime (útil mientras se configura).

Cambiar de USB a Ethernet es solo cambiar la configuración de la caja.
"""

import socket
import urllib.error
import urllib.request

from app.models import Caja, ModoImpresora

TIEMPO_ESPERA = 5  # segundos; más que eso y la venta espera demasiado


class ErrorImpresion(Exception):
    pass


def _enviar_red(direccion: str, datos: bytes) -> None:
    host, _, puerto = direccion.partition(":")
    try:
        with socket.create_connection((host, int(puerto or 9100)), timeout=TIEMPO_ESPERA) as conexion:
            conexion.sendall(datos)
    except OSError as e:
        raise ErrorImpresion(f"No se pudo conectar con la impresora en {direccion}: {e}") from e


def _enviar_agente(url: str, token: str | None, datos: bytes) -> None:
    peticion = urllib.request.Request(
        url.rstrip("/") + "/imprimir",
        data=datos,
        method="POST",
        headers={"Content-Type": "application/octet-stream", "X-Token": token or ""},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIEMPO_ESPERA) as respuesta:
            respuesta.read()
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="replace")
        raise ErrorImpresion(f"El agente de impresión respondió {e.code}: {detalle}") from e
    except (urllib.error.URLError, OSError) as e:
        raise ErrorImpresion(f"No se pudo conectar con el agente de impresión en {url}: {e}") from e


def enviar(caja: Caja, datos: bytes) -> bool:
    """Manda los bytes a la impresora de la caja. Regresa False si la caja no
    tiene impresora configurada; lanza ErrorImpresion si falla el envío."""
    if caja.impresora_modo == ModoImpresora.NINGUNA or not caja.impresora_direccion:
        return False
    if caja.impresora_modo == ModoImpresora.RED:
        _enviar_red(caja.impresora_direccion, datos)
    else:
        _enviar_agente(caja.impresora_direccion, caja.impresora_token, datos)
    return True
