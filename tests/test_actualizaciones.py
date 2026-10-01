"""Actualizaciones automáticas: cuándo se puede instalar, el estado que ve la
pantalla y la versión que revisan las pantallas abiertas."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.scripts import puede_actualizar
from app.services import actualizaciones

MX = ZoneInfo("America/Mexico_City")
TURNOS = {"modo": "corrido", "turnos": [], "especiales": [],
          "semana": {d: [{"nombre": "", "abre": "08:00", "cierra": "22:00"}] for d in
                     ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]}}


def test_solo_con_la_farmacia_cerrada():
    assert not puede_actualizar.puede([TURNOS], datetime(2026, 10, 1, 12, 0, tzinfo=MX))  # abierta
    assert not puede_actualizar.puede([TURNOS], datetime(2026, 10, 1, 7, 45, tzinfo=MX))  # abre en 15 minutos
    assert puede_actualizar.puede([TURNOS], datetime(2026, 10, 1, 23, 0, tzinfo=MX))  # cerrada
    # Sin horario capturado: solo de 1 a 5 de la mañana.
    assert puede_actualizar.puede([None], datetime(2026, 10, 1, 3, 0, tzinfo=MX))
    assert not puede_actualizar.puede([None], datetime(2026, 10, 1, 23, 0, tzinfo=MX))


def test_estado_para_la_pantalla(como_admin, como_mostrador, tmp_path, monkeypatch):
    archivo = tmp_path / "actualizacion.json"
    archivo.write_text(json.dumps({"estado": "error", "mensaje": "La actualización falló", "disponible": "abc1234",
                                   "cambios": ["Algo nuevo"], "historial": [{"de": "a", "a": "b", "resultado": "error"}]}),
                       encoding="utf-8")
    monkeypatch.setattr(actualizaciones, "ESTADO", archivo)
    monkeypatch.setattr(actualizaciones, "tarea_instalada", lambda: True)
    e = como_admin.get("/sistema/actualizaciones").json()
    assert e["estado"] == "error" and e["disponible"] == "abc1234" and e["automaticas"] is True
    assert como_admin.get("/notificaciones/pendientes").json()["actualizacion"] == 1  # avisa en la campana
    assert como_mostrador.get("/sistema/actualizaciones").status_code == 403


def test_instalar_ahora_sin_tarea(como_admin, monkeypatch):
    monkeypatch.setattr(actualizaciones, "tarea_instalada", lambda: False)
    r = como_admin.post("/sistema/actualizaciones/instalar-ahora")
    assert r.status_code == 409 and "instaló el servidor" in r.json()["detail"]


def test_version_publica(cliente):
    assert cliente.get("/sistema/version").json()["version"] == actualizaciones.VERSION
