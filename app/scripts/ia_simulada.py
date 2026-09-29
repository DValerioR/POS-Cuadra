"""IA simulada para el servidor de demostración (`--ia-simulada`): permite ver
el chat del asistente y probar sus consultas sin clave ni costo.

No es inteligente: elige una consulta por palabras clave de la pregunta y
responde listando lo que regresó. Nunca se usa fuera del demo.
"""

import json
from datetime import timedelta

from app.asistente import chat
from app.asistente.consultas import hoy
from app.services import configuracion_ia


class _Bloque:
    def __init__(self, **datos):
        self.__dict__.update(datos)
        self._datos = datos

    def to_dict(self):
        return dict(self._datos)


class _Respuesta:
    def __init__(self, bloques, stop_reason):
        self.content = bloques
        self.stop_reason = stop_reason
        self.usage = type("Uso", (), {"input_tokens": 0, "output_tokens": 0})()


def _elegir(pregunta: str) -> tuple[str, dict] | None:
    p = pregunta.lower()
    h = hoy()
    if "caduc" in p:
        return "por_caducar", {"meses": 3}
    if "pendiente" in p:
        return "pendientes", {}
    if "vendido" in p:
        return "productos_mas_vendidos", {"desde": (h - timedelta(days=h.weekday())).isoformat(), "hasta": h.isoformat(),
                                          "orden": "piezas", "limite": 5}
    if "vend" in p:
        return "resumen_ventas", {"desde": h.isoformat(), "hasta": None, "agrupar_por": None}
    if "catálogo" in p or "catalogo" in p:
        return "estado_del_catalogo", {}
    return None


def _texto(resultado: dict) -> str:
    lineas = ["Esto es lo que encontré (respuesta simulada del demo):"]
    for clave, valor in resultado.items():
        nombre = clave.replace("_", " ")
        if isinstance(valor, list):
            lineas.append(f"- **{nombre}**: {len(valor)}")
            for fila in valor[:5]:
                if isinstance(fila, dict):
                    lineas.append("  " + ", ".join(f"{k}: {v}" for k, v in list(fila.items())[:4]))
        else:
            lineas.append(f"- **{nombre}**: {valor}")
    return "\n".join(lineas)


def _llamar(cliente, sistema, mensajes):
    ultimo = mensajes[-1]["content"]
    if ultimo and ultimo[0].get("type") == "tool_result":
        return _Respuesta([_Bloque(type="text", text=_texto(json.loads(ultimo[0]["content"])))], "end_turn")
    pregunta = ultimo[0]["text"].split("]\n", 1)[-1]
    eleccion = _elegir(pregunta)
    if eleccion is None:
        return _Respuesta([_Bloque(type="text", text=(
            "Soy la IA simulada del demo: solo sé contestar sobre ventas de hoy, lo más vendido, "
            "caducidades, pendientes y el catálogo."))], "end_turn")
    nombre, entrada = eleccion
    return _Respuesta([_Bloque(type="tool_use", id="demo-1", name=nombre, input=entrada)], "tool_use")


def activar() -> None:
    chat._llamar = _llamar
    configuracion_ia.cliente = lambda: object()
    configuracion_ia.estado = lambda: {"configurada": True, "termina_en": "DEMO", "modelo": "IA simulada"}
