"""Horario de atención del negocio (Datos del negocio → Horario)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services import horario

MX = ZoneInfo("America/Mexico_City")
SEMANA = {
    "lunes": [{"abre": "09:00", "cierra": "14:00"}, {"abre": "16:00", "cierra": "21:00"}],
    "martes": [{"abre": "09:00", "cierra": "14:00"}, {"abre": "16:00", "cierra": "21:00"}],
    "miércoles": [{"abre": "09:00", "cierra": "14:00"}, {"abre": "16:00", "cierra": "21:00"}],
    "jueves": [{"abre": "09:00", "cierra": "14:00"}, {"abre": "16:00", "cierra": "21:00"}],
    "viernes": [{"abre": "09:00", "cierra": "14:00"}, {"abre": "16:00", "cierra": "21:00"}],
    "sábado": [{"abre": "09:00", "cierra": "15:00"}],
    "domingo": [],
}
HORARIO = {"semana": SEMANA, "especiales": [{"fecha": "2026-12-25", "turnos": [], "nota": "Navidad"}]}


def test_guardar_y_leer_horario(como_admin):
    r = como_admin.put("/negocio", json={"horario": HORARIO})
    assert r.status_code == 200, r.text
    assert r.json()["horario"]["semana"]["lunes"][1] == {"abre": "16:00", "cierra": "21:00"}
    assert como_admin.get("/negocio").json()["horario"]["especiales"][0]["fecha"] == "2026-12-25"
    # Cambiar otro dato no borra el horario.
    assert como_admin.put("/negocio", json={"ticket_pie": "Gracias"}).json()["horario"] is not None


def test_horario_mal_capturado(como_admin):
    malo = {"semana": {**SEMANA, "lunes": [{"abre": "21:00", "cierra": "09:00"}]}}
    r = como_admin.put("/negocio", json={"horario": malo})
    assert r.status_code == 422 and "después" in r.text
    encimados = {"semana": {**SEMANA, "lunes": [{"abre": "09:00", "cierra": "15:00"}, {"abre": "14:00", "cierra": "21:00"}]}}
    assert "enciman" in como_admin.put("/negocio", json={"horario": encimados}).text
    assert como_admin.put("/negocio", json={"horario": {"semana": {"lunes": [{"abre": "9", "cierra": "21:00"}]}}}).status_code == 422


def test_solo_admin_cambia_horario(como_mostrador):
    assert como_mostrador.put("/negocio", json={"horario": HORARIO}).status_code == 403


def test_esta_abierto():
    assert horario.esta_abierto(HORARIO, datetime(2026, 9, 28, 10, 0, tzinfo=MX))  # lunes 10:00
    assert not horario.esta_abierto(HORARIO, datetime(2026, 9, 28, 15, 0, tzinfo=MX))  # a la hora de comer
    assert not horario.esta_abierto(HORARIO, datetime(2026, 9, 28, 21, 0, tzinfo=MX))  # ya cerró
    assert not horario.esta_abierto(HORARIO, datetime(2026, 9, 27, 12, 0, tzinfo=MX))  # domingo
    assert not horario.esta_abierto(HORARIO, datetime(2026, 12, 25, 10, 0, tzinfo=MX))  # Navidad (viernes)
    assert horario.esta_abierto(None) is None


def test_texto_del_horario():
    assert horario.texto(HORARIO) == (
        "lunes a viernes de 09:00 a 14:00 y de 16:00 a 21:00; sábado de 09:00 a 15:00; domingo cerrado")
