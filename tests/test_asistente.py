"""Asistente de IA: las consultas (que son las que dan los números) y el ciclo
del chat con la API simulada."""

import json
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.asistente import chat, consultas
from app.asistente.herramientas import HERRAMIENTAS
from app.core import config
from app.core.config import settings
from app.models import Lote, MensajeAsistente, Turno
from tests.test_devoluciones import devolver, pieza
from tests.test_ventas import amoxicilina, caja, producto, r, shampoo, vender  # noqa: F401  (fixtures)

HOY = consultas.hoy().isoformat()


# --- Consultas ------------------------------------------------------------------------

def test_herramientas_y_consultas_coinciden():
    assert {h["name"] for h in HERRAMIENTAS} == set(consultas.CONSULTAS)
    for h in HERRAMIENTAS:
        esquema = h["input_schema"]
        assert h["strict"] is True
        assert esquema["additionalProperties"] is False
        assert set(esquema["required"]) == set(esquema["properties"])


def test_resumen_ventas(como_admin, caja, shampoo, negocio, db):
    v1 = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()  # 116 efectivo
    vender(como_admin, caja, [r(shampoo, 2)], tarjeta="232")  # 232 tarjeta
    devolver(como_admin, v1, caja, [pieza(v1, 0, 1)])  # regresa 116 en efectivo
    res = consultas.resumen_ventas(db, negocio.id, HOY, None, "caja")
    assert (res["numero_de_ventas"], res["vendido_con_impuestos"]) == (2, "348.00")
    assert (res["cobrado_en_efectivo"], res["cobrado_con_tarjeta"]) == ("116.00", "232.00")
    assert (res["regresado_en_devoluciones_efectivo"], res["neto_cobrado"]) == ("116.00", "232.00")
    assert res["grupos"] == [{"grupo": "Mostrador 1", "ventas": 2, "vendido": "348.00"}]
    ayer = (consultas.hoy() - timedelta(days=1)).isoformat()
    assert consultas.resumen_ventas(db, negocio.id, ayer)["numero_de_ventas"] == 0


@pytest.mark.parametrize("desde, hasta", [("ayer", None), ("2026-09-10", "2026-09-01"), ("2020-01-01", "2026-01-01")])
def test_fechas_invalidas(db, negocio, desde, hasta):
    with pytest.raises(consultas.ConsultaInvalida):
        consultas.resumen_ventas(db, negocio.id, desde, hasta)


def test_mas_vendidos_y_busqueda(como_admin, caja, shampoo, amoxicilina, negocio, db):
    vender(como_admin, caja, [r(shampoo, 3), r(amoxicilina, 1)], efectivo="500")
    top = consultas.productos_mas_vendidos(db, negocio.id, HOY)["productos"]
    assert [(p["nombre"], p["piezas"]) for p in top] == [("SHAMPOO 400ML", "3"), ("AMOXICILINA 500MG", "1")]
    [p] = consultas.buscar_productos(db, negocio.id, "shamp")["productos"]
    assert (p["precio_venta"], p["iva"], p["existencia"]) == ("116.00", "16%", "17")
    lotes = consultas.existencia_producto(db, negocio.id, amoxicilina.id)
    assert lotes["existencia_total"] == "16"
    with pytest.raises(consultas.ConsultaInvalida):
        consultas.existencia_producto(db, negocio.id, 99999)


def test_sin_movimiento_por_caducar_y_catalogo(como_admin, caja, shampoo, negocio, db):
    quieto = producto(db, negocio, "SIN VENTAS", "10", [(4, consultas.hoy() + timedelta(days=20), "Q")], costo=D(5))
    vender(como_admin, caja, [r(shampoo, 1)], efectivo="116")
    nombres = [p["nombre"] for p in consultas.productos_sin_movimiento(db, negocio.id, 30)["productos"]]
    assert "SIN VENTAS" in nombres and "SHAMPOO 400ML" not in nombres
    [lote] = consultas.por_caducar(db, negocio.id, 1)["lotes"]
    assert (lote["nombre"], lote["piezas"]) == ("SIN VENTAS", "4")
    assert consultas.estado_del_catalogo(db, negocio.id)["productos_activos"] == 2
    assert quieto.id


def test_cortes_devoluciones_y_pendientes(como_admin, caja, shampoo, negocio, db):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    devolver(como_admin, v, caja, [pieza(v, 0, 1)])
    [t] = consultas.cortes_de_caja(db, negocio.id, HOY)["turnos"]
    assert (t["caja"], t["cerrado"]) == ("Mostrador 1", "sigue abierto")
    [d] = consultas.devoluciones(db, negocio.id, HOY)["devoluciones"]
    assert (d["tipo"], d["efectivo_regresado"]) == ("devolucion", "116.00")
    p = consultas.pendientes(db, negocio.id)
    assert p["turnos_abiertos"] == ["Mostrador 1"]
    assert consultas.entradas_de_mercancia(db, negocio.id, HOY)["entradas"] == []


# --- Chat (API simulada) ---------------------------------------------------------------

class Bloque:
    def __init__(self, **datos):
        self.__dict__.update(datos)
        self._datos = datos

    def to_dict(self):
        return dict(self._datos)


class Respuesta:
    def __init__(self, bloques, stop_reason):
        self.content = bloques
        self.stop_reason = stop_reason
        self.usage = type("U", (), {"input_tokens": 100, "output_tokens": 20})()


@pytest.fixture
def clave(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-api03-" + "x" * 40)


@pytest.fixture
def api(monkeypatch, clave):
    """Guion de respuestas; registra lo que se mandó en cada llamada."""
    estado = {"guion": [], "enviado": []}

    def falsa(cliente, sistema, mensajes):
        estado["enviado"].append({"sistema": sistema, "mensajes": json.loads(json.dumps(mensajes, default=str))})
        return estado["guion"].pop(0)

    monkeypatch.setattr(chat, "_llamar", falsa)
    return estado


def consulta_y_respuesta(texto_final="Hoy vendieron $116.00."):
    return [
        Respuesta([Bloque(type="tool_use", id="t1", name="resumen_ventas", input={"desde": HOY, "hasta": None, "agrupar_por": None})], "tool_use"),
        Respuesta([Bloque(type="text", text=texto_final)], "end_turn"),
    ]


def test_pregunta_con_consulta(como_admin, caja, shampoo, api, db):
    vender(como_admin, caja, [r(shampoo, 1)], efectivo="116")
    api["guion"] = consulta_y_respuesta()
    res = como_admin.post("/asistente/preguntar", json={"texto": "¿Cuánto vendimos hoy?"})
    assert res.status_code == 200
    datos = res.json()
    assert (datos["respuesta"], datos["consultas"]) == ("Hoy vendieron $116.00.", ["resumen_ventas"])
    primera, segunda = api["enviado"]
    assert "Farmacia" in primera["sistema"] or "negocio" in primera["sistema"]
    assert primera["mensajes"][0]["content"][0]["text"].startswith("[Hoy es ")
    # El resultado de la consulta que recibió la IA trae el total exacto calculado por la base.
    resultado = segunda["mensajes"][-1]["content"][0]
    assert resultado["type"] == "tool_result" and resultado["is_error"] is False
    assert json.loads(resultado["content"])["vendido_con_impuestos"] == "116.00"
    assert db.query(MensajeAsistente).count() == 4  # pregunta, llamada, resultado, respuesta


def test_la_conversacion_se_reenvia_igual(como_admin, api):
    api["guion"] = consulta_y_respuesta("Primera.") + [Respuesta([Bloque(type="text", text="Segunda.")], "end_turn")]
    c = como_admin.post("/asistente/preguntar", json={"texto": "uno"}).json()["conversacion_id"]
    como_admin.post("/asistente/preguntar", json={"texto": "dos", "conversacion_id": c})
    anterior = api["enviado"][1]["mensajes"] + [{"role": "assistant", "content": [{"type": "text", "text": "Primera."}]}]
    assert api["enviado"][2]["mensajes"][: len(anterior)] == anterior  # historia sin cambios
    visibles = como_admin.get(f"/asistente/conversaciones/{c}").json()
    assert [(m["rol"], m["texto"]) for m in visibles] == [
        ("usuario", "uno"), ("asistente", "Primera."), ("usuario", "dos"), ("asistente", "Segunda."),
    ]
    assert visibles[1]["consultas"] == ["resumen_ventas"]
    assert [x["titulo"] for x in como_admin.get("/asistente/conversaciones").json()] == ["uno"]


def test_consulta_con_parametros_malos_se_le_explica(como_admin, api):
    api["guion"] = [
        Respuesta([Bloque(type="tool_use", id="t1", name="resumen_ventas", input={"desde": "ayer", "hasta": None, "agrupar_por": None})], "tool_use"),
        Respuesta([Bloque(type="text", text="Listo.")], "end_turn"),
    ]
    como_admin.post("/asistente/preguntar", json={"texto": "x"})
    resultado = api["enviado"][1]["mensajes"][-1]["content"][0]
    assert resultado["is_error"] is True
    assert "AAAA-MM-DD" in json.loads(resultado["content"])["error"]


def test_si_falla_la_api_no_se_guarda_nada(como_admin, api, db, monkeypatch):
    import anthropic
    import httpx2

    def sin_conexion(*a):
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))

    monkeypatch.setattr(chat, "_llamar", sin_conexion)
    r_ = como_admin.post("/asistente/preguntar", json={"texto": "hola"})
    assert r_.status_code == 409
    assert "conexión" in r_.json()["detail"]
    assert como_admin.get("/asistente/conversaciones").json() == []


def test_demasiadas_vueltas(como_admin, api):
    llamada = Respuesta([Bloque(type="tool_use", id="t", name="pendientes", input={})], "tool_use")
    api["guion"] = [llamada] * chat.MAX_VUELTAS
    assert como_admin.post("/asistente/preguntar", json={"texto": "x"}).status_code == 409


def test_solo_admin_y_sus_conversaciones(como_admin, como_mostrador, como_bodega, api, crear_usuario, negocio, cliente_de):
    api["guion"] = [Respuesta([Bloque(type="text", text="Hola.")], "end_turn")]
    c = como_admin.post("/asistente/preguntar", json={"texto": "hola"}).json()["conversacion_id"]
    for cliente in (como_mostrador, como_bodega):
        assert cliente.post("/asistente/preguntar", json={"texto": "x"}).status_code == 403
    otro_admin = cliente_de(crear_usuario(negocio, nombre="otro"))
    assert otro_admin.get(f"/asistente/conversaciones/{c}").status_code == 404
    assert otro_admin.post("/asistente/preguntar", json={"texto": "x", "conversacion_id": c}).status_code == 404
    assert como_admin.delete(f"/asistente/conversaciones/{c}").status_code == 204
    assert como_admin.get("/asistente/conversaciones").json() == []


def test_sin_clave(como_admin, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    r_ = como_admin.post("/asistente/preguntar", json={"texto": "hola"})
    assert r_.status_code == 409
    assert "Asistente de IA" in r_.json()["detail"]
