"""Errores de la API de Claude en español llano, sobre todo el de saldo agotado."""

import anthropic
import httpx
import pytest

from app.asistente import chat
from app.services import configuracion_ia, usos
from app.services.configuracion_ia import SALDO_AGOTADO, mensaje_error
from app.whatsapp import bot
from tests.test_asistente import api, clave  # noqa: F401  (fixtures)
from tests.test_bot_whatsapp import ia, recibir, wa  # noqa: F401  (fixtures)

PETICION = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def error_api(clase, status, mensaje):
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": mensaje}}
    return clase(mensaje, response=httpx.Response(status, request=PETICION), body=body)


SIN_CREDITO = error_api(anthropic.BadRequestError, 400, "Your credit balance is too low to access the Anthropic API. "
                        "Please go to Plans & Billing to upgrade or purchase credits.")
LIMITE_WORKSPACE = error_api(anthropic.BadRequestError, 400, "You have reached your specified workspace API usage limits. "
                             "You will regain access on 2026-11-01 at 00:00 UTC.")


@pytest.mark.parametrize("error, esperado", [
    (SIN_CREDITO, SALDO_AGOTADO),
    (LIMITE_WORKSPACE, SALDO_AGOTADO),
    (error_api(anthropic.AuthenticationError, 401, "invalid x-api-key"), "no es válida"),
    (error_api(anthropic.RateLimitError, 429, "rate limited"), "ocupada"),
    (error_api(anthropic.InternalServerError, 529, "Overloaded"), "tiene problemas"),
    (error_api(anthropic.BadRequestError, 400, "messages: image too large"), "respondió con un error (400)"),
    (anthropic.APIConnectionError(request=PETICION), "No hay conexión"),
])
def test_mensajes(error, esperado):
    assert esperado in mensaje_error(error)


def test_un_400_que_no_es_de_saldo_puede_explicarse():
    e = error_api(anthropic.BadRequestError, 400, "Could not process image")
    assert mensaje_error(e, "La API no aceptó el archivo") == "La API no aceptó el archivo (Could not process image)"
    assert mensaje_error(SIN_CREDITO, "La API no aceptó el archivo") == SALDO_AGOTADO


def test_asistente_sin_saldo(como_admin, api, monkeypatch):
    def sin_saldo(*a):
        raise SIN_CREDITO

    monkeypatch.setattr(chat, "_llamar", sin_saldo)
    r = como_admin.post("/asistente/preguntar", json={"texto": "hola"})
    assert r.status_code == 409 and r.json()["detail"] == SALDO_AGOTADO
    assert como_admin.get("/usos").json()["ia"]["usados"] == 0  # no se cuenta como uso


def test_bot_sin_saldo_pasa_a_persona_con_el_motivo(db, negocio, wa, ia, monkeypatch):
    monkeypatch.setattr(bot.horario, "esta_abierto", lambda h, cuando=None: True)

    def sin_saldo(*a):
        raise SIN_CREDITO

    monkeypatch.setattr(bot, "_llamar", sin_saldo)
    c = recibir(db, negocio, "¿Tienen paracetamol?")
    assert c.motivo_persona == "Se acabó el saldo de la IA"
    assert wa.enviados[-1]["texto"] == bot.MENSAJE_FALLA
    assert usos.usados(db, negocio.id, usos.TipoUso.IA) == 0
    assert configuracion_ia.es_saldo_agotado(SIN_CREDITO)
