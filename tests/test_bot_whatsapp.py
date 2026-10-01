"""Bot de WhatsApp: webhook de Meta, respuestas con herramientas de solo
consulta, encargos (no fuera de horario), pasar a una persona y la pantalla
Conversaciones. La IA se reemplaza por respuestas preparadas."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from app.api import whatsapp as api_whatsapp
from app.core.config import settings
from app.models import (ConversacionWhatsApp, Encargo, EstadoConversacion, Lote, MensajeWhatsApp, Producto)
from app.services import buscador
from app.whatsapp import bot
from app.whatsapp import cliente as whatsapp

TEL = "5213312345678"  # como lo manda WhatsApp (formato viejo de celular, también se acepta)


class _Bloque:
    def __init__(self, **datos):
        self.__dict__.update(datos)
        self._datos = datos

    def to_dict(self):
        return dict(self._datos)


class _Respuesta:
    def __init__(self, bloques, stop_reason):
        self.content, self.stop_reason = bloques, stop_reason


def usar(nombre, **entrada):
    return _Respuesta([_Bloque(type="tool_use", id=f"t-{nombre}", name=nombre, input=entrada)], "tool_use")


def decir(texto):
    return _Respuesta([_Bloque(type="text", text=texto)], "end_turn")


@pytest.fixture
def ia(monkeypatch):
    """Guion de la IA: cada llamada toma la siguiente respuesta; guarda lo que recibió."""
    guion = {"respuestas": [], "llamadas": []}

    def llamar(cliente, sistema, mensajes):
        guion["llamadas"].append(json.loads(json.dumps(mensajes, default=str)))
        return guion["respuestas"].pop(0)

    monkeypatch.setattr(bot, "_llamar", llamar)
    monkeypatch.setattr(bot.configuracion_ia, "cliente", lambda: object())
    return guion


@pytest.fixture
def wa(monkeypatch):
    simulado = whatsapp.activar_simulado()
    monkeypatch.setattr(settings, "whatsapp_avisos_a", "523861112233")
    monkeypatch.setattr(settings, "whatsapp_bot_activo", True)
    yield simulado
    whatsapp.desactivar_simulado()


@pytest.fixture
def abierto(monkeypatch):
    monkeypatch.setattr(bot.horario, "esta_abierto", lambda h, cuando=None: True)


@pytest.fixture
def catalogo(db, negocio):
    buscador.olvidar_catalogo()
    p = {
        "para": Producto(negocio_id=negocio.id, nombre="PARACETAMOL 500 MG TABLETAS C/10", precio_venta=D(35)),
        "amoxi": Producto(negocio_id=negocio.id, nombre="AMOXICILINA 500 MG CAPSULAS C/12", precio_venta=D(89),
                          requiere_receta=True),
        "raro": Producto(negocio_id=negocio.id, nombre="SITAGLIPTINA 100 MG C/28", precio_venta=D(640), encargo=True),
    }
    db.add_all(p.values())
    db.flush()
    db.add(Lote(negocio_id=negocio.id, producto_id=p["para"].id, cantidad=D(40)))
    db.add(Lote(negocio_id=negocio.id, producto_id=p["amoxi"].id, cantidad=D(2)))
    db.commit()
    yield p
    buscador.olvidar_catalogo()


def recibir(db, negocio, texto, **extra):
    return bot.recibir(db, negocio.id, TEL, "María López", texto, **extra)


# --- Herramientas -------------------------------------------------------------------

def test_buscar_producto_sin_cantidades(db, negocio, catalogo):
    r = bot.buscar_producto(db, negocio.id, "paracetamol")["resultados"][0]
    assert r["precio"] == "$35.00" and r["disponibilidad"] == "hay" and r["coincidencia"] == "exacta"
    assert "existencia" not in r and "costo" not in r  # nunca cantidades ni costos
    amoxi = bot.buscar_producto(db, negocio.id, "amoxicilina")["resultados"][0]
    assert amoxi["disponibilidad"] == "pocas" and amoxi["requiere_receta"] is True
    assert bot.buscar_producto(db, negocio.id, "sitagliptina")["resultados"][0]["disponibilidad"] == "por_encargo"


def test_buscar_mal_escrito_da_parecidos(db, negocio, catalogo):
    r = bot.buscar_producto(db, negocio.id, "parasetamol")["resultados"]
    assert r[0]["nombre"].startswith("PARACETAMOL") and r[0]["coincidencia"] == "parecido"


def test_informacion_farmacia(db, negocio):
    negocio.direccion, negocio.telefono, negocio.formas_pago = "Iturbide 2", "386 744 0175", ["Efectivo"]
    db.commit()
    info = bot.informacion_farmacia(db, negocio.id)
    assert info["direccion"] == "Iturbide 2" and info["formas_de_pago"] == ["Efectivo"]
    assert info["horario_semana"] == "sin capturar" and info["abierta_ahora"] is None


# --- Conversación con el bot ---------------------------------------------------------

def test_el_bot_contesta_con_lo_que_consulto(db, negocio, catalogo, wa, ia):
    ia["respuestas"] = [usar("buscar_producto", texto="paracetamol"), decir("Sí tenemos *PARACETAMOL*, $35.00.")]
    c = recibir(db, negocio, "¿Tienen paracetamol?", wa_id="wamid.1")
    assert c.estado == EstadoConversacion.BOT
    assert [m.de for m in c.mensajes] == ["cliente", "bot"]
    assert wa.enviados[-1] == {"telefono": TEL, "texto": "Sí tenemos *PARACETAMOL*, $35.00."}
    # La IA recibió la fecha, si está abierta y el nombre del cliente; luego el resultado de la consulta.
    primero = ia["llamadas"][0][-1]["content"][0]["text"]
    assert primero.startswith("[Hoy es") and "María López" in primero and primero.endswith("¿Tienen paracetamol?")
    resultado = json.loads(ia["llamadas"][1][-1]["content"][0]["content"])
    assert resultado["resultados"][0]["disponibilidad"] == "hay"


def test_mensaje_repetido_no_se_contesta_dos_veces(db, negocio, wa, ia):
    ia["respuestas"] = [decir("¡Buen día!")]
    assert recibir(db, negocio, "Hola", wa_id="wamid.X") is not None
    assert recibir(db, negocio, "Hola", wa_id="wamid.X") is None
    assert len(wa.enviados) == 1


def test_encargo_por_whatsapp(db, negocio, catalogo, wa, ia, abierto):
    ia["respuestas"] = [usar("registrar_encargo", producto_id=catalogo["raro"].id, cantidad=2, nombre_cliente="María López"),
                        decir("Su encargo quedó registrado.")]
    recibir(db, negocio, "Sí, encárguelo, dos cajas")
    e = db.query(Encargo).one()
    assert (e.canal, e.telefono, e.cantidad, e.creado_por_id) == ("whatsapp", TEL, D(2), None)


def test_fuera_de_horario_no_se_confirma_el_encargo(db, negocio, catalogo, wa, ia, monkeypatch):
    monkeypatch.setattr(bot.horario, "esta_abierto", lambda h, cuando=None: False)
    ia["respuestas"] = [usar("registrar_encargo", producto_id=catalogo["raro"].id, cantidad=1, nombre_cliente="María"),
                        decir("La confirmación no puede procesarse fuera del horario laboral.")]
    recibir(db, negocio, "Sí, encárguelo")
    assert db.query(Encargo).count() == 0
    assert json.loads(ia["llamadas"][1][-1]["content"][0]["content"])["motivo"] == "fuera_de_horario"


def test_pasar_a_persona_avisa_y_el_bot_se_calla(db, negocio, wa, ia, como_mostrador):
    ia["respuestas"] = [usar("pasar_a_persona", motivo="Quiere hablar con el farmacéutico"),
                        decir("En breve le atenderá una persona de nuestro equipo.")]
    c = recibir(db, negocio, "Quiero hablar con una persona")
    assert c.estado == EstadoConversacion.ESPERA and c.motivo_persona == "Quiere hablar con el farmacéutico"
    aviso = next(e for e in wa.enviados if e.get("plantilla") == "atencion_cliente")
    assert aviso["telefono"] == "523861112233" and aviso["parametros"][0] == "María López"
    assert bot.contar_pendientes(db, negocio.id) == 1

    # Mientras espera, el bot no contesta: los mensajes quedan sin leer.
    enviados = len(wa.enviados)
    recibir(db, negocio, "¿Hola?")
    assert len(wa.enviados) == enviados and c.sin_leer == 2

    # El personal la toma y contesta desde Conversaciones.
    r = como_mostrador.post(f"/whatsapp/conversaciones/{c.id}/responder", json={"texto": "Buenas tardes, le atiende Ana."})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "persona" and wa.enviados[-1]["texto"] == "Buenas tardes, le atiende Ana."
    assert bot.contar_pendientes(db, negocio.id) == 0

    r = como_mostrador.post(f"/whatsapp/conversaciones/{c.id}/regresar-al-bot")
    assert r.json()["estado"] == "bot"


def test_sin_numero_de_avisos_queda_anotado(db, negocio, wa, ia, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_avisos_a", None)
    ia["respuestas"] = [usar("pasar_a_persona", motivo="Factura"), decir("En breve le atenderán.")]
    c = recibir(db, negocio, "Necesito factura")
    assert c.estado == EstadoConversacion.ESPERA and "número para avisos" in c.aviso_error


def test_si_falla_la_ia_pasa_a_una_persona(db, negocio, wa, monkeypatch):
    def falla():
        raise bot.OperacionInvalida("Falta la clave de la API de Claude")

    monkeypatch.setattr(bot.configuracion_ia, "cliente", falla)
    c = recibir(db, negocio, "¿Tienen paracetamol?")
    assert c.mensajes[0].de == "cliente"  # el mensaje del cliente no se pierde
    assert c.estado == EstadoConversacion.ESPERA and wa.enviados[-1]["texto"] == bot.MENSAJE_FALLA


def test_bot_apagado_todo_llega_a_conversaciones(db, negocio, wa, ia, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_bot_activo", False)
    c = recibir(db, negocio, "Hola")
    assert c.estado == EstadoConversacion.ESPERA and ia["llamadas"] == []


def test_no_se_escribe_pasadas_24_horas(db, negocio, wa, ia, como_mostrador):
    ia["respuestas"] = [decir("¡Buen día!")]
    c = recibir(db, negocio, "Hola")
    c.ultimo_cliente_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db.commit()
    r = como_mostrador.post(f"/whatsapp/conversaciones/{c.id}/responder", json={"texto": "Hola"})
    assert r.status_code == 409 and "24 horas" in r.json()["detail"]


def test_conversacion_con_persona_regresa_sola_al_bot(db, negocio, wa, ia):
    ia["respuestas"] = [usar("pasar_a_persona", motivo="X"), decir("En breve."), decir("¡Buen día!")]
    c = recibir(db, negocio, "Quiero una persona")
    c.ultimo_mensaje_at = datetime.now(timezone.utc) - timedelta(hours=13)
    db.commit()
    c = recibir(db, negocio, "Hola de nuevo")
    assert c.estado == EstadoConversacion.BOT and wa.enviados[-1]["texto"] == "¡Buen día!"


def test_foto_se_lee_y_se_le_pasa_a_la_ia(db, negocio, catalogo, wa, ia, monkeypatch):
    monkeypatch.setattr(buscador, "_llamar_foto", lambda datos, tipo: json.dumps({"tipo": "caja_o_frasco", "nota": None,
        "medicamentos": [{"nombre_comercial": "Paracetamol", "sustancia_activa": None, "concentracion": "500 mg",
                          "presentacion": None, "laboratorio": None}]}))
    ia["respuestas"] = [decir("Es *PARACETAMOL 500 MG*, $35.00.")]
    c = recibir(db, negocio, None, imagen=b"\x89PNG\r\n\x1a\n" + b"0" * 50, imagen_tipo="image/png")
    assert [m.de for m in c.mensajes] == ["cliente", "sistema", "bot"]
    assert "PARACETAMOL 500 MG TABLETAS C/10" in c.mensajes[1].texto
    assert "[El cliente envió una foto" in ia["llamadas"][0][-1]["content"][0]["text"]


# --- Webhook de Meta --------------------------------------------------------------

AVISO = {"entry": [{"changes": [{"value": {
    "contacts": [{"wa_id": TEL, "profile": {"name": "María López"}}],
    "messages": [{"from": TEL, "id": "wamid.A", "type": "text", "text": {"body": "Hola"}},
                 {"from": TEL, "id": "wamid.B", "type": "image", "image": {"id": "MEDIA1", "caption": "esta"}},
                 {"from": TEL, "id": "wamid.C", "type": "sticker", "sticker": {}}],
}}]}]}


def test_mensajes_del_aviso():
    m = api_whatsapp.mensajes_del_aviso(AVISO)
    assert [x["wa_id"] for x in m] == ["wamid.A", "wamid.B", "wamid.C"]
    assert m[0]["nombre"] == "María López" and m[1]["media_id"] == "MEDIA1" and m[1]["texto"] == "esta"
    assert "sticker" in m[2]["texto"]
    assert api_whatsapp.mensajes_del_aviso({"entry": [{"changes": [{"value": {"statuses": [{}]}}]}]}) == []


def test_webhook_verificacion(cliente, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_verify_token", "clave123")
    ok = cliente.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "clave123", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert cliente.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "otra",
                                                    "hub.challenge": "42"}).status_code == 403


def test_webhook_exige_la_firma_de_meta(cliente, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_app_secret", "secreto")
    procesados = []
    monkeypatch.setattr(api_whatsapp, "procesar", procesados.append)
    cuerpo = json.dumps(AVISO).encode()
    assert cliente.post("/whatsapp/webhook", content=cuerpo).status_code == 403
    malo = {"X-Hub-Signature-256": "sha256=" + "0" * 64}
    assert cliente.post("/whatsapp/webhook", content=cuerpo, headers=malo).status_code == 403
    firma = "sha256=" + hmac.new(b"secreto", cuerpo, hashlib.sha256).hexdigest()
    r = cliente.post("/whatsapp/webhook", content=cuerpo, headers={"X-Hub-Signature-256": firma})
    assert r.status_code == 200 and [p["wa_id"] for p in procesados] == ["wamid.A", "wamid.B", "wamid.C"]


# --- Pantallas ----------------------------------------------------------------------

def test_permisos(como_admin, como_mostrador, wa):
    assert como_mostrador.get("/whatsapp/conversaciones").status_code == 200
    assert como_mostrador.get("/whatsapp/configuracion").status_code == 403
    assert como_admin.get("/whatsapp/configuracion").json()["simulado"] is True


def test_simulador_solo_en_el_demo(como_admin):
    whatsapp.desactivar_simulado()
    r = como_admin.post("/whatsapp/simular", json={"telefono": "3312345678", "texto": "Hola"})
    assert r.status_code == 404


def test_simulador_del_demo(db, como_admin, wa, ia):
    ia["respuestas"] = [decir("¡Buen día!")]
    r = como_admin.post("/whatsapp/simular", json={"telefono": "3312345678", "nombre": "Prueba", "texto": "Hola"})
    assert r.status_code == 200, r.text
    assert [m["de"] for m in r.json()["mensajes"]] == ["cliente", "bot"] and r.json()["telefono"] == "523312345678"


def test_configuracion_en_el_demo_no_toca_el_env(como_admin, wa, monkeypatch):
    escritas = []
    monkeypatch.setattr(api_whatsapp.config, "escribir_variable", lambda v, x: escritas.append(v))
    r = como_admin.put("/whatsapp/configuracion", json={"avisos_a": "386 111 2233", "bot_activo": False})
    assert r.status_code == 200 and r.json()["avisos_a"] == "523861112233" and r.json()["bot_activo"] is False
    assert escritas == []


def test_informacion_para_clientes_en_datos_del_negocio(como_admin):
    r = como_admin.put("/negocio", json={"direccion": " Iturbide  Norte 2 ", "telefono": "386 744 0175",
                                         "ubicacion_url": "https://maps.app.goo.gl/abc", "formas_pago": ["Efectivo", " "]})
    assert r.status_code == 200, r.text
    assert r.json()["direccion"] == "Iturbide Norte 2" and r.json()["formas_pago"] == ["Efectivo"]
    assert como_admin.put("/negocio", json={"ubicacion_url": "maps.google.com"}).status_code == 422
