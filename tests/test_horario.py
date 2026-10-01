"""Horario de atención del negocio (Datos del negocio → Horario de atención):
horario corrido o por turnos y días especiales con reglas."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services import horario

MX = ZoneInfo("America/Mexico_City")


def _turnos(mat=("08:00", "15:00"), ves=("15:00", "22:00")):
    return [{"nombre": "Matutino", "abre": mat[0], "cierra": mat[1]},
            {"nombre": "Vespertino", "abre": ves[0], "cierra": ves[1]}]


SEMANA = {d: _turnos() for d in ["lunes", "martes", "miércoles", "jueves", "viernes"]}
SEMANA["sábado"] = _turnos(ves=("15:00", "20:00"))
SEMANA["domingo"] = [{"nombre": "Matutino", "abre": "09:00", "cierra": "14:00"}]
HORARIO = {
    "modo": "turnos", "turnos": ["Matutino", "Vespertino"], "semana": SEMANA,
    "especiales": [
        {"fecha": "2026-12-24", "abre": None, "cierra": "18:00", "cerrado": False, "nota": "Nochebuena"},
        {"fecha": "2026-11-16", "abre": "10:00", "cierra": "14:00", "cerrado": False, "nota": "Revolución"},
        {"fecha": "2027-01-01", "abre": None, "cierra": None, "cerrado": True, "nota": None},
    ],
}


def test_guardar_y_leer_horario(como_admin):
    r = como_admin.put("/negocio", json={"horario": HORARIO})
    assert r.status_code == 200, r.text
    h = r.json()["horario"]
    assert h["semana"]["lunes"][1] == {"nombre": "Vespertino", "abre": "15:00", "cierra": "22:00"}
    assert [e["fecha"] for e in h["especiales"]] == ["2026-11-16", "2026-12-24", "2027-01-01"]  # ordenados
    # Cambiar otro dato no borra el horario.
    assert como_admin.put("/negocio", json={"ticket_pie": "Gracias"}).json()["horario"] is not None


def test_horario_corrido(como_admin):
    corrido = {"modo": "corrido", "semana": {"lunes": [{"abre": "08:00", "cierra": "22:00"}]}}
    h = como_admin.put("/negocio", json={"horario": corrido}).json()["horario"]
    assert h["turnos"] == [] and h["semana"]["lunes"] == [{"nombre": "", "abre": "08:00", "cierra": "22:00"}]
    assert h["semana"]["martes"] == []
    dos = {"modo": "corrido", "semana": {"lunes": [{"abre": "08:00", "cierra": "14:00"}, {"abre": "16:00", "cierra": "22:00"}]}}
    assert "un solo horario" in como_admin.put("/negocio", json={"horario": dos}).text


def test_horario_mal_capturado(como_admin):
    def error(h):
        r = como_admin.put("/negocio", json={"horario": h})
        assert r.status_code == 422
        return r.text

    al_reves = {**HORARIO, "semana": {**SEMANA, "lunes": _turnos(mat=("15:00", "08:00"))}}
    assert "después" in error(al_reves)
    turno_inventado = {**HORARIO, "semana": {"lunes": [{"nombre": "Nocturno", "abre": "22:00", "cierra": "24:00"}]}}
    assert "no existe" in error(turno_inventado)
    assert "mismo nombre" in error({**HORARIO, "turnos": ["Matutino", "matutino"]})
    sin_regla = {**HORARIO, "especiales": [{"fecha": "2026-12-24"}]}
    assert "entran o salen" in error(sin_regla)
    assert error({**HORARIO, "semana": {"lunes": [{"nombre": "Matutino", "abre": "8", "cierra": "15:00"}]}})


def test_solo_admin_cambia_horario(como_mostrador):
    assert como_mostrador.put("/negocio", json={"horario": HORARIO}).status_code == 403


def test_turnos_y_reglas_de_dias_especiales():
    # Día normal (lunes): los dos turnos.
    assert horario.turnos_del_dia(HORARIO, date(2026, 9, 28)) == _turnos()
    # Nochebuena (jueves): salen a las 18:00; el vespertino cierra antes.
    assert horario.turnos_del_dia(HORARIO, date(2026, 12, 24)) == _turnos(ves=("15:00", "18:00"))
    # 16 de noviembre (lunes): entran a las 10 y salen a las 14; el vespertino no se abre.
    assert horario.turnos_del_dia(HORARIO, date(2026, 11, 16)) == [{"nombre": "Matutino", "abre": "10:00", "cierra": "14:00"}]
    assert horario.turnos_del_dia(HORARIO, date(2027, 1, 1)) == []
    assert horario.turnos_del_dia(None, date(2026, 9, 28)) is None


def test_esta_abierto():
    assert horario.esta_abierto(HORARIO, datetime(2026, 9, 28, 8, 0, tzinfo=MX))  # lunes al abrir
    assert horario.esta_abierto(HORARIO, datetime(2026, 9, 28, 15, 0, tzinfo=MX))  # cambio de turno
    assert not horario.esta_abierto(HORARIO, datetime(2026, 9, 28, 22, 0, tzinfo=MX))  # ya cerró
    assert not horario.esta_abierto(HORARIO, datetime(2026, 9, 27, 15, 0, tzinfo=MX))  # domingo en la tarde
    assert not horario.esta_abierto(HORARIO, datetime(2026, 12, 24, 19, 0, tzinfo=MX))  # Nochebuena: salieron temprano
    assert not horario.esta_abierto(HORARIO, datetime(2026, 11, 16, 9, 0, tzinfo=MX))  # entraron más tarde
    assert horario.esta_abierto(None) is None


def test_texto_para_el_cliente():
    # Los turnos se juntan: el cliente ve a qué hora abre y cierra la farmacia.
    assert horario.texto(HORARIO) == (
        "lunes a viernes de 08:00 a 22:00; sábado de 08:00 a 20:00; domingo de 09:00 a 14:00")
    assert horario.texto_del_dia(HORARIO, date(2026, 12, 24)) == "de 08:00 a 18:00"
    assert horario.texto_del_dia(HORARIO, date(2027, 1, 1)) == "cerrado"
