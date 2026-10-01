"""Mensajes por WhatsApp con la API oficial de WhatsApp Business (Cloud API de Meta).

Regla de WhatsApp: si el cliente no escribió en las últimas 24 horas (casi
siempre, con un encargo que tarda días), la farmacia solo puede escribirle con
una PLANTILLA aprobada por Meta. Por eso los avisos de encargos usan las
plantillas de PLANTILLAS (hay que darlas de alta, con este mismo texto, en el
administrador de WhatsApp de Meta; ver docs/WHATSAPP.md).

Dos clientes con los mismos métodos: `ClienteReal` (httpx, Graph API) y
`ClienteSimulado` (en memoria, para el demo y las pruebas; no manda nada).
"""

import re
from dataclasses import dataclass, field

import httpx

from app.core.config import settings

URL = "https://graph.facebook.com/v21.0"
IDIOMA = "es_MX"


@dataclass(frozen=True)
class Plantilla:
    nombre: str  # como se registró en Meta
    texto: str  # con {{1}}, {{2}}... (para mostrar lo que se envió)


# Redacción formal, igual que el bot. {{1}} cliente, {{2}} producto y el último,
# la farmacia; en "no disponible", {{3}} es el motivo (frase formal) y {{4}} la farmacia.
PLANTILLAS = {
    "encargo_pedido": Plantilla(
        "encargo_pedido",
        "Estimado(a) {{1}}, le informamos que su encargo de {{2}} ya fue solicitado a nuestro proveedor. "
        "Le avisaremos por este medio en cuanto llegue a {{3}}. Gracias por su preferencia.",
    ),
    "encargo_disponible": Plantilla(
        "encargo_disponible",
        "Estimado(a) {{1}}, le informamos que su encargo de {{2}} ya se encuentra disponible en {{3}}. "
        "Puede pasar a recogerlo en nuestro horario de atención. Gracias por su preferencia.",
    ),
    "encargo_no_disponible": Plantilla(
        "encargo_no_disponible",
        "Estimado(a) {{1}}, lamentamos informarle que no fue posible encargar {{2}}, {{3}}. "
        "Si lo desea, con gusto le sugerimos una alternativa. Atentamente, {{4}}.",
    ),
    # Al WhatsApp del personal (la tableta) cuando un cliente necesita a una
    # persona: {{1}} cliente, {{2}} su número, {{3}} motivo.
    "atencion_cliente": Plantilla(
        "atencion_cliente",
        "Un cliente necesita atención en WhatsApp: {{1}} ({{2}}). Motivo: {{3}}. "
        "Contéstele desde el sistema, en Ventas → Conversaciones de WhatsApp.",
    ),
}


class ErrorWhatsApp(Exception):
    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


def numero(telefono: str | None) -> str | None:
    """Teléfono en el formato de WhatsApp (solo dígitos, con lada de país).
    Un número de México de 10 dígitos se completa con 52."""
    digitos = re.sub(r"\D", "", telefono or "")
    if len(digitos) == 10:
        return "52" + digitos
    if len(digitos) == 13 and digitos.startswith("521"):  # formato viejo de celulares de México
        return "52" + digitos[3:]
    return digitos if 11 <= len(digitos) <= 15 else None


def texto(plantilla: Plantilla, parametros: list[str]) -> str:
    t = plantilla.texto
    for i, valor in enumerate(parametros, 1):
        t = t.replace("{{%d}}" % i, valor)
    return t


class ClienteReal:
    def __init__(self, token: str, numero_id: str):
        self._numero_id = numero_id
        self._http = httpx.Client(base_url=URL, timeout=20.0, headers={"Authorization": f"Bearer {token}"})

    def enviar_plantilla(self, telefono: str, plantilla: Plantilla, parametros: list[str]) -> str:
        cuerpo = {
            "messaging_product": "whatsapp", "to": telefono, "type": "template",
            "template": {"name": plantilla.nombre, "language": {"code": IDIOMA}, "components": [
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in parametros]},
            ]},
        }
        return self._enviar(cuerpo)

    def enviar_texto(self, telefono: str, texto: str) -> str:
        """Texto libre: solo se puede dentro de las 24 h desde que el cliente escribió."""
        cuerpo = {"messaging_product": "whatsapp", "to": telefono, "type": "text",
                  "text": {"body": texto, "preview_url": True}}
        return self._enviar(cuerpo)

    def _enviar(self, cuerpo: dict) -> str:
        try:
            r = self._http.post(f"/{self._numero_id}/messages", json=cuerpo)
        except httpx.HTTPError:
            raise ErrorWhatsApp("No hay conexión con WhatsApp. ¿Hay internet?")
        if r.status_code >= 400:
            raise ErrorWhatsApp(_error(r))
        return r.json()["messages"][0]["id"]

    def descargar_media(self, media_id: str) -> tuple[bytes, str]:
        """La foto (u otro archivo) que mandó el cliente: (bytes, tipo)."""
        try:
            info = self._http.get(f"/{media_id}")
            if info.status_code >= 400:
                raise ErrorWhatsApp(_error(info))
            datos = self._http.get(info.json()["url"])
        except httpx.HTTPError:
            raise ErrorWhatsApp("No hay conexión con WhatsApp. ¿Hay internet?")
        if datos.status_code >= 400:
            raise ErrorWhatsApp(_error(datos))
        return datos.content, info.json().get("mime_type", "")


def _error(r: httpx.Response) -> str:
    try:
        detalle = r.json().get("error", {}).get("message")
    except ValueError:
        detalle = None
    return f"WhatsApp no aceptó el mensaje ({r.status_code})" + (f": {detalle}" if detalle else "")


@dataclass
class ClienteSimulado:
    """No manda nada: guarda lo que se habría enviado. `falla` hace que el siguiente envío falle."""

    enviados: list[dict] = field(default_factory=list)
    falla: str | None = None

    def enviar_plantilla(self, telefono: str, plantilla: Plantilla, parametros: list[str]) -> str:
        if self.falla:
            mensaje, self.falla = self.falla, None
            raise ErrorWhatsApp(mensaje)
        self.enviados.append({"telefono": telefono, "plantilla": plantilla.nombre, "parametros": parametros})
        return f"wamid.SIMULADO{len(self.enviados)}"

    def enviar_texto(self, telefono: str, texto: str) -> str:
        if self.falla:
            mensaje, self.falla = self.falla, None
            raise ErrorWhatsApp(mensaje)
        self.enviados.append({"telefono": telefono, "texto": texto})
        return f"wamid.SIMULADO{len(self.enviados)}"

    def descargar_media(self, media_id: str) -> tuple[bytes, str]:
        raise ErrorWhatsApp("El WhatsApp simulado no descarga fotos")


_simulado: ClienteSimulado | None = None


def activar_simulado() -> ClienteSimulado:
    global _simulado
    _simulado = ClienteSimulado()
    return _simulado


def desactivar_simulado() -> None:
    global _simulado
    _simulado = None


def configurado() -> bool:
    return _simulado is not None or bool(settings.whatsapp_token and settings.whatsapp_numero_id)


def cliente() -> "ClienteReal | ClienteSimulado":
    if _simulado is not None:
        return _simulado
    if not configurado():
        raise ErrorWhatsApp("WhatsApp todavía no está configurado")
    return ClienteReal(settings.whatsapp_token, settings.whatsapp_numero_id)
