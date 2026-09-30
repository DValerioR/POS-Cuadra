"""Terminal Mercado Pago Point (con la terminal simulada): token en el .env,
terminal de cada caja, cobro que espera a la terminal, venta ligada al cobro,
cobros cancelados, rechazados y pagados que se quedaron sin venta."""

from decimal import Decimal as D

import pytest

from app.core import config
from app.core.config import settings
from app.pagos import mercadopago as mp
from tests.test_ventas import caja, r, shampoo, vender  # noqa: F401  (fixtures)

TOKEN = "APP_USR-1234567890123456-093012-" + "a" * 32 + "-WXYZ"


@pytest.fixture(autouse=True)
def terminal_simulada(tmp_path, monkeypatch):
    ruta = tmp_path / ".env"
    ruta.write_text("DATABASE_URL=postgresql+psycopg://x\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_PATH", ruta)
    monkeypatch.setattr(settings, "mercadopago_token", None)
    simulada = mp.activar_simulado()
    yield simulada
    mp.desactivar_simulado()


@pytest.fixture
def con_terminal(como_admin, caja):  # noqa: F811
    assert como_admin.put("/terminal/caja", json={"caja_id": caja.id, "terminal_id": "SIMULADA__TERMINAL1"}).status_code == 200
    return caja


def esperar(cliente, cobro):
    """Consulta el cobro hasta que termina (la terminal simulada tarda dos consultas)."""
    for _ in range(5):
        cobro = cliente.get(f"/terminal/cobros/{cobro['id']}").json()
        if cobro["terminado"]:
            return cobro
    raise AssertionError("el cobro no terminó")


def test_token_en_el_env_y_solo_admin(como_admin, como_mostrador, terminal_simulada):
    assert como_mostrador.put("/terminal/token", json={"token": TOKEN}).status_code == 403
    assert como_admin.put("/terminal/token", json={"token": "sk-ant-otra"}).status_code == 409
    r1 = como_admin.put("/terminal/token", json={"token": f" {TOKEN} "})
    assert r1.status_code == 200 and r1.json()["termina_en"] == "WXYZ"
    assert TOKEN not in r1.text
    assert f"MERCADOPAGO_TOKEN={TOKEN}" in config.ENV_PATH.read_text(encoding="utf-8")
    assert settings.mercadopago_token == TOKEN
    assert como_admin.delete("/terminal/token").json()["configurado"] is False
    assert "MERCADOPAGO_TOKEN" not in config.ENV_PATH.read_text(encoding="utf-8")


def test_terminales_y_caja(como_admin, caja, db, negocio):  # noqa: F811
    lista = como_admin.get("/terminal/terminales").json()
    assert [t["id"] for t in lista] == ["SIMULADA__TERMINAL1", "SIMULADA__TERMINAL2"]
    assert lista[0]["nombre"] == "SIMULADA · serie TERMINAL1"
    assert como_admin.post("/terminal/modo-pdv", json={"terminal_id": "SIMULADA__TERMINAL2"}).status_code == 200
    assert como_admin.get("/terminal/terminales").json()[1]["modo"] == "PDV"

    assert como_admin.put("/terminal/caja", json={"caja_id": caja.id, "terminal_id": "SIMULADA__TERMINAL1"}).status_code == 200
    assert como_admin.get("/terminal/terminales").json()[0]["caja"] == "Mostrador 1"
    # Una terminal es de una sola caja.
    from app.models import Caja
    otra = Caja(negocio_id=negocio.id, nombre="Mostrador 2")
    db.add(otra)
    db.commit()
    r1 = como_admin.put("/terminal/caja", json={"caja_id": otra.id, "terminal_id": "SIMULADA__TERMINAL1"})
    assert r1.status_code == 409 and "Mostrador 1" in r1.json()["detail"]


def test_cobro_pagado_y_venta(como_mostrador, con_terminal, shampoo, db):  # noqa: F811
    c = como_mostrador.post("/terminal/cobros", json={"caja_id": con_terminal.id, "monto": "232.00"})
    assert c.status_code == 201, c.text
    cobro = c.json()
    assert cobro["estado"] == "created" and not cobro["terminado"]
    # Sin pagar todavía, la venta no se puede registrar con ese cobro.
    v = como_mostrador.post("/ventas", json={"caja_id": con_terminal.id, "renglones": [r(shampoo, 2)],
                                             "tarjeta": "232", "cobro_terminal_id": cobro["id"]})
    assert v.status_code == 409  # la primera consulta solo la lleva a la terminal
    cobro = esperar(como_mostrador, cobro)
    assert cobro["pagado"] and cobro["tarjeta"] == "visa ****4242"

    # Monto distinto: no.
    v = como_mostrador.post("/ventas", json={"caja_id": con_terminal.id, "renglones": [r(shampoo, 1)],
                                             "tarjeta": "116", "cobro_terminal_id": cobro["id"]})
    assert v.status_code == 409 and "232.00" in v.json()["detail"]
    v = como_mostrador.post("/ventas", json={"caja_id": con_terminal.id, "renglones": [r(shampoo, 2)],
                                             "tarjeta": "232", "cobro_terminal_id": cobro["id"]})
    assert v.status_code == 201, v.text
    assert como_mostrador.get(f"/terminal/cobros/{cobro['id']}").json()["venta_id"] == v.json()["id"]
    # Ya usado: no sirve para otra venta.
    v2 = como_mostrador.post("/ventas", json={"caja_id": con_terminal.id, "renglones": [r(shampoo, 2)],
                                              "tarjeta": "232", "cobro_terminal_id": cobro["id"]})
    assert v2.status_code == 409


def test_pagado_sin_venta_se_reutiliza(como_mostrador, con_terminal, terminal_simulada):
    cobro = como_mostrador.post("/terminal/cobros", json={"caja_id": con_terminal.id, "monto": "100.00"}).json()
    cobro = esperar(como_mostrador, cobro)
    assert cobro["pagado"]
    # Se cerró la pantalla antes de registrar la venta: se avisa y se reutiliza.
    assert [x["id"] for x in como_mostrador.get(f"/terminal/cobros/sin-venta?caja_id={con_terminal.id}").json()] == [cobro["id"]]
    otra = como_mostrador.post("/terminal/cobros", json={"caja_id": con_terminal.id, "monto": "100.00"}).json()
    assert otra["id"] == cobro["id"]
    assert len(terminal_simulada.ordenes) == 1  # no se le cobró dos veces


def test_esperando_no_deja_mandar_otro_monto(como_mostrador, con_terminal):
    cobro = como_mostrador.post("/terminal/cobros", json={"caja_id": con_terminal.id, "monto": "50.00"}).json()
    otra = como_mostrador.post("/terminal/cobros", json={"caja_id": con_terminal.id, "monto": "80.00"})
    assert otra.status_code == 409 and "50.00" in otra.json()["detail"]
    assert cobro["estado"] == "created"


def test_en_la_terminal_se_cancela_ahi(como_mostrador, con_terminal):
    cobro = como_mostrador.post("/terminal/cobros", json={"caja_id": con_terminal.id, "monto": "50.00"}).json()
    # La terminal simulada lo recibe en la primera consulta (la que hace cancelar).
    r1 = como_mostrador.post(f"/terminal/cobros/{cobro['id']}/cancelar")
    assert r1.status_code == 409 and "botón rojo" in r1.json()["detail"]


@pytest.mark.parametrize("final, mensaje", [(mp.FALLIDA, "rechazó"), (mp.EXPIRADA, "expiró"), (mp.CANCELADA, "canceló")])
def test_cobro_que_no_se_paga(como_mostrador, con_terminal, terminal_simulada, final, mensaje):
    terminal_simulada.siguiente = final
    cobro = esperar(como_mostrador, como_mostrador.post(
        "/terminal/cobros", json={"caja_id": con_terminal.id, "monto": "70.00"}).json())
    assert not cobro["pagado"] and mensaje in cobro["mensaje"]
    # Terminado sin pago: se puede mandar otro monto.
    terminal_simulada.siguiente = mp.PAGADA
    assert como_mostrador.post("/terminal/cobros", json={"caja_id": con_terminal.id, "monto": "90.00"}).status_code == 201


def test_sin_terminal_o_sin_turno(como_mostrador, como_admin, caja, db):  # noqa: F811
    r1 = como_mostrador.post("/terminal/cobros", json={"caja_id": caja.id, "monto": "10.00"})
    assert r1.status_code == 409 and "no tiene terminal" in r1.json()["detail"]
    # Sin terminal, la tarjeta se sigue registrando a mano.
    from app.models import Turno
    como_admin.put("/terminal/caja", json={"caja_id": caja.id, "terminal_id": "SIMULADA__TERMINAL1"})
    turno = db.query(Turno).filter_by(caja_id=caja.id).one()
    from datetime import datetime, timezone
    turno.cerrado_en = datetime.now(timezone.utc)
    db.commit()
    r2 = como_mostrador.post("/terminal/cobros", json={"caja_id": caja.id, "monto": "10.00"})
    assert r2.status_code == 409 and "turno" in r2.json()["detail"]


def test_monto_se_registra_exacto(como_mostrador, con_terminal, terminal_simulada):
    como_mostrador.post("/terminal/cobros", json={"caja_id": con_terminal.id, "monto": "12.5"})
    (orden,) = terminal_simulada.ordenes.values()
    assert orden.orden.monto == D("12.50")
