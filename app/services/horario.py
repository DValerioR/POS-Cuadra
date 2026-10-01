"""Horario de atención del negocio (Datos del negocio → Horario de atención).

Se guarda en `negocios.horario` como JSON:

    {"modo": "turnos",                        # o "corrido" (un solo horario al día)
     "turnos": ["Matutino", "Vespertino"],    # nombres (solo en modo turnos)
     "semana": {"lunes": [{"nombre": "Matutino", "abre": "08:00", "cierra": "15:00"},
                          {"nombre": "Vespertino", "abre": "15:00", "cierra": "22:00"}],
                "domingo": [{"nombre": "Matutino", "abre": "09:00", "cierra": "14:00"}],
                ...},                          # [] = no se abre ese día
     "especiales": [{"fecha": "2026-12-24", "abre": null, "cierra": "18:00",
                     "cerrado": false, "nota": "Nochebuena"}]}

Cada turno dice a qué hora se abre y se cierra (pueden encimarse para el
cambio de turno). El negocio está abierto mientras haya algún turno.

Los días especiales (festivos, inventario...) no cambian los turnos, sino
que les ponen reglas: "entramos más tarde" (`abre`: ningún turno empieza
antes de esa hora) y "salimos más temprano" (`cierra`: ninguno termina
después); un turno que queda fuera de esas horas no se abre ese día. También
se puede marcar el día completo como cerrado.

Lo usa el bot de WhatsApp: fuera de horario no se confirman encargos.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import settings

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _hora(texto: str) -> time:
    # "24:00" = medianoche al final del día.
    return time(23, 59, 59) if texto == "24:00" else time.fromisoformat(texto)


def especial_de(horario: dict | None, dia: date) -> dict | None:
    for especial in (horario or {}).get("especiales", []):
        if especial["fecha"] == dia.isoformat():
            return especial
    return None


def aplicar_reglas(turnos: list[dict], especial: dict | None) -> list[dict]:
    """Los turnos del día con las reglas del día especial aplicadas."""
    if not especial:
        return [dict(t) for t in turnos]
    if especial.get("cerrado"):
        return []
    salida = []
    for t in turnos:
        abre = max(t["abre"], especial["abre"]) if especial.get("abre") else t["abre"]
        cierra = min(t["cierra"], especial["cierra"]) if especial.get("cierra") else t["cierra"]
        if abre < cierra:
            salida.append({**t, "abre": abre, "cierra": cierra})
    return salida


def turnos_del_dia(horario: dict | None, dia: date) -> list[dict] | None:
    """Los turnos de esa fecha, ya con las reglas del día especial ([] = no
    se abre). None si no hay horario capturado."""
    if not horario:
        return None
    normales = horario.get("semana", {}).get(DIAS[dia.weekday()], [])
    return aplicar_reglas(normales, especial_de(horario, dia))


def _ahora(cuando: datetime | None) -> datetime:
    zona = ZoneInfo(settings.zona_horaria)
    return (cuando or datetime.now(zona)).astimezone(zona)


def esta_abierto(horario: dict | None, cuando: datetime | None = None) -> bool | None:
    """¿Está abierto en ese momento (hora local del negocio)? None si no hay horario."""
    cuando = _ahora(cuando)
    turnos = turnos_del_dia(horario, cuando.date())
    if turnos is None:
        return None
    ahora = cuando.time()
    return any(_hora(t["abre"]) <= ahora < _hora(t["cierra"]) for t in turnos)


def horas_de_atencion(turnos: list[dict]) -> list[tuple[str, str]]:
    """Lo que ve el cliente: los turnos juntos (8-15 y 15-22 = de 8 a 22)."""
    tramos: list[list[str]] = []
    for t in sorted(turnos, key=lambda t: t["abre"]):
        if tramos and t["abre"] <= tramos[-1][1]:
            tramos[-1][1] = max(tramos[-1][1], t["cierra"])
        else:
            tramos.append([t["abre"], t["cierra"]])
    return [(a, c) for a, c in tramos]


def _en_palabras(turnos: list[dict]) -> str:
    tramos = horas_de_atencion(turnos)
    if not tramos:
        return "cerrado"
    return " y ".join(f"de {a} a {c}" for a, c in tramos)


def texto(horario: dict | None) -> str:
    """El horario de la semana en palabras, juntando los días seguidos con las
    mismas horas ("lunes a viernes de 08:00 a 22:00; domingo cerrado")."""
    if not horario:
        return ""
    semana = horario.get("semana", {})
    grupos: list[tuple[int, int, str]] = []
    for i, dia in enumerate(DIAS):
        t = _en_palabras(semana.get(dia, []))
        if grupos and grupos[-1][2] == t:
            grupos[-1] = (grupos[-1][0], i, t)
        else:
            grupos.append((i, i, t))
    partes = []
    for ini, fin, t in grupos:
        dias = DIAS[ini] if ini == fin else (f"{DIAS[ini]} y {DIAS[fin]}" if fin == ini + 1 else f"{DIAS[ini]} a {DIAS[fin]}")
        partes.append(f"{dias} {t}")
    return "; ".join(partes)


def texto_del_dia(horario: dict | None, dia: date) -> str:
    """Las horas de una fecha en palabras ("de 10:00 a 18:00" o "cerrado")."""
    turnos = turnos_del_dia(horario, dia)
    return "" if turnos is None else _en_palabras(turnos)
