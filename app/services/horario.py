"""Horario de atención del negocio (Datos del negocio → Horario).

Se guarda en `negocios.horario` como JSON:

    {"semana": {"lunes": [{"abre": "09:00", "cierra": "14:00"},
                          {"abre": "16:00", "cierra": "21:00"}],
                "domingo": [], ...},          # [] = cerrado ese día
     "especiales": [{"fecha": "2026-12-25", "turnos": [], "nota": "Navidad"}]}

Un día tiene hasta dos turnos (por si cierran a comer). Los días especiales
(festivos, inventario...) reemplazan al horario de la semana en esa fecha.
Lo usa el bot de WhatsApp: fuera de horario no se confirman encargos.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import settings

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _hora(texto: str) -> time:
    # "24:00" = medianoche al final del día.
    return time(23, 59, 59) if texto == "24:00" else time.fromisoformat(texto)


def turnos_del_dia(horario: dict | None, dia: date) -> list[dict] | None:
    """Los turnos de esa fecha ([] = cerrado). None si no hay horario capturado."""
    if not horario:
        return None
    for especial in horario.get("especiales", []):
        if especial["fecha"] == dia.isoformat():
            return especial["turnos"]
    return horario.get("semana", {}).get(DIAS[dia.weekday()], [])


def esta_abierto(horario: dict | None, cuando: datetime | None = None) -> bool | None:
    """¿Está abierto en ese momento (hora local del negocio)? None si no hay horario."""
    cuando = (cuando or datetime.now(ZoneInfo(settings.zona_horaria))).astimezone(ZoneInfo(settings.zona_horaria))
    turnos = turnos_del_dia(horario, cuando.date())
    if turnos is None:
        return None
    ahora = cuando.time()
    return any(_hora(t["abre"]) <= ahora < _hora(t["cierra"]) for t in turnos)


def _turnos_texto(turnos: list[dict]) -> str:
    if not turnos:
        return "cerrado"
    return " y ".join(f"de {t['abre']} a {t['cierra']}" for t in turnos)


def texto(horario: dict | None) -> str:
    """El horario en palabras, juntando los días seguidos con el mismo horario
    ("lunes a viernes de 09:00 a 21:00; sábado de 09:00 a 14:00; domingo cerrado")."""
    if not horario:
        return ""
    semana = horario.get("semana", {})
    grupos: list[tuple[int, int, str]] = []
    for i, dia in enumerate(DIAS):
        t = _turnos_texto(semana.get(dia, []))
        if grupos and grupos[-1][2] == t:
            grupos[-1] = (grupos[-1][0], i, t)
        else:
            grupos.append((i, i, t))
    partes = []
    for ini, fin, t in grupos:
        dias = DIAS[ini] if ini == fin else (f"{DIAS[ini]} y {DIAS[fin]}" if fin == ini + 1 else f"{DIAS[ini]} a {DIAS[fin]}")
        partes.append(f"{dias} {t}")
    return "; ".join(partes)
