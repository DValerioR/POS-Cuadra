"""IA simulada para el servidor de demostración (`--ia-simulada`): permite ver
el chat del asistente, probar sus consultas y las sugerencias de pedido del
reporte de faltantes y las ofertas sugeridas sin clave ni costo.

No es inteligente: elige una consulta por palabras clave de la pregunta y
responde listando lo que regresó. Nunca se usa fuera del demo.
"""

import json
from datetime import timedelta

from app.asistente import chat
from app.asistente.consultas import hoy
from app.services import configuracion_ia, ofertas, sugerencias_pedido


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


def _sugerencias(cliente, texto):
    """Promedio de las últimas 4 semanas × 3 semanas, menos la existencia."""
    sugerencias = []
    for linea in texto.splitlines()[2:]:
        pid, _, existencia, _, _, _, ventas = [c.strip() for c in linea.split("|")]
        semanas = [int(v) for v in ventas.split(",") if v]
        promedio = sum(semanas[-4:]) / 4
        cantidad = max(0, round(promedio * 3 - float(existencia)))
        motivo = f"Vende ~{promedio:.1f} por semana (simulado)" if promedio else "Sin ventas recientes (simulado)"
        sugerencias.append({"producto_id": int(pid), "cantidad": cantidad, "motivo": motivo})
    return json.dumps({"sugerencias": sugerencias})


def _ofertas(cliente, texto):
    """Lo que caduca: 25% de descuento (el código lo sube al mínimo si hace
    falta); lo que sobra sin receta: 3x2; lo demás: 10% de descuento."""
    propuestas = []
    for linea in texto.splitlines()[2:]:
        c = [x.strip() for x in linea.split("|")]
        pid, receta, precio, razones = int(c[0]), c[3], float(c[6]), c[12]
        if "Caduca" in razones:
            tipo, nuevo, motivo = "descuento", precio * 0.75, "Caduca pronto (simulado)"
        elif "Sobreinventario" in razones and receta == "no":
            tipo, nuevo, motivo = "3x2", 0, "Hay de más (simulado)"
        else:
            tipo, nuevo, motivo = "descuento", precio * 0.9, "Se mueve poco (simulado)"
        propuestas.append({"producto_id": pid, "tipo": tipo, "precio_oferta": round(nuevo, 2), "paquete_con_id": 0,
                           "motivo": motivo})
    return json.dumps({"ofertas": propuestas})


def activar() -> None:
    chat._llamar = _llamar
    sugerencias_pedido._llamar = _sugerencias
    ofertas._llamar = _ofertas
    configuracion_ia.cliente = lambda: object()
    configuracion_ia.estado = lambda: {"configurada": True, "termina_en": "DEMO", "modelo": "IA simulada"}
