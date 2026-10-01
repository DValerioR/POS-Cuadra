"""IA simulada para el servidor de demostración (`--ia-simulada`): permite ver
el chat del asistente, probar sus consultas y las sugerencias de pedido del
reporte de faltantes y las ofertas sugeridas sin clave ni costo.

No es inteligente: elige una consulta por palabras clave de la pregunta y
responde listando lo que regresó. Nunca se usa fuera del demo.
"""

import json
import re
from datetime import timedelta

from app.asistente import chat
from app.asistente.consultas import hoy
from app.services import buscador, configuracion_ia, ofertas, sugerencias_pedido


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


def _foto(datos, tipo):
    """No ve la foto: "lee" el nombre de un producto del demo con un error de
    escritura (c por s, v por b), para ver el buscador tolerante."""
    import random

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import Producto

    with SessionLocal() as db:
        nombres = list(db.scalars(select(Producto.nombre).where(Producto.activo.is_(True)).limit(60)))
    palabra = random.choice(nombres).split()[0] if nombres else "PARACETAMOL"
    leido = palabra.lower().replace("c", "s").replace("v", "b").replace("z", "s")
    return json.dumps({"tipo": "caja_o_frasco", "nota": "Lectura simulada del demo (no se vio la foto).",
                       "medicamentos": [{"nombre_comercial": leido, "sustancia_activa": None, "concentracion": None,
                                         "presentacion": None, "laboratorio": None}]})


# --- Bot de WhatsApp simulado ---------------------------------------------------
# Elige la herramienta por palabras clave y arma la respuesta con lo que
# regresó (datos reales del demo). Sirve para ver el flujo, no la redacción.

_PERSONA = ("persona", "humano", "alguien", "encargad", "queja", "factura", "asesor")
_INFO = ("horario", "abren", "cierran", "abierto", "a qué hora", "a que hora", "dónde", "donde", "ubicaci",
         "direcci", "pago", "tarjeta", "teléfono", "telefono")
_RELLENO = (r"\b(hola|buen(os|as)? (d[ií]as|tardes|noches)|tienen|tiene|hay|precio|de|del|el|la|los|las|"
            r"cu[aá]nto|cuesta|me|da|quiero|busco|un|una|por favor|favor)\b")
_DISPONIBLE = {"hay": "sí tenemos", "pocas": "nos quedan pocas piezas", "no_hay": "por el momento no tenemos",
               "por_encargo": "es por encargo"}


def _bot_texto(mensajes) -> str:
    texto = next(b["text"] for b in mensajes[-1]["content"] if b.get("type") == "text")
    return texto.split("]\n", 1)[-1] if texto.startswith("[Hoy es") else texto


def _bot_elegir(mensajes):
    texto = _bot_texto(mensajes)
    t = texto.lower()
    if any(p in t for p in _PERSONA):
        return "pasar_a_persona", {"motivo": f"El cliente pidió: {texto[:120]}"}
    foto = re.search(r"Se leyó: ([^.;]+)", texto)
    if foto:
        return "buscar_producto", {"texto": foto.group(1)}
    if "envió una foto" in t:
        return None
    if any(p in t for p in _INFO):
        return "informacion_farmacia", {}
    if re.match(r"^\s*(s[ií]\b|claro|enc[aá]rg)", t):
        anteriores = [m for m in mensajes[:-1] if m["role"] == "assistant"]
        previo = next((b["text"] for b in anteriores[-1]["content"] if b.get("type") == "text"), "") if anteriores else ""
        nombre = re.search(r"\*([^*]+)\*", previo)
        cliente = re.search(r"Cliente: ([^\]]+)\]", mensajes[-1]["content"][0]["text"])
        if nombre and "encargu" in previo:
            return "registrar_encargo", {"descripcion": nombre.group(1), "cantidad": 1,
                                         "nombre_cliente": cliente.group(1) if cliente else "Cliente"}
    buscado = re.sub(_RELLENO, " ", t, flags=re.I)
    buscado = " ".join(re.sub(r"[¿?¡!.,]", " ", buscado).split())
    if len(buscado) < 3:
        return None
    return "buscar_producto", {"texto": buscado}


def _bot_respuesta(nombre: str, r: dict) -> str:
    if nombre == "buscar_producto":
        lista = r.get("resultados") or []
        if not lista:
            return ("Una disculpa, no encontramos ese producto en nuestro catálogo. ¿Podría indicarnos el nombre "
                    "exacto o enviarnos una foto de la caja o la receta?")
        if lista[0]["coincidencia"] == "parecido":
            opciones = "\n".join(f"• *{p['nombre']}*" for p in lista[:3])
            return f"No encontramos ese nombre exacto. ¿Se refiere a alguno de estos?\n{opciones}"
        lineas = []
        for p in lista[:3]:
            extra = (f" ({p['oferta']})" if p["oferta"] else "") + (" Requiere receta médica." if p["requiere_receta"] else "")
            lineas.append(f"• *{p['nombre']}*: {p['precio']}, {_DISPONIBLE[p['disponibilidad']]}.{extra}")
        texto = "Con gusto le informo:\n" + "\n".join(lineas)
        if lista[0]["disponibilidad"] in ("no_hay", "por_encargo"):
            texto += f"\n\n¿Desea que le encarguemos *{lista[0]['nombre']}*? Responda «sí, encárguelo»."
        return texto
    if nombre == "informacion_farmacia":
        partes = [f"Nuestro horario es: {r['horario_semana']}."]
        if r["abierta_ahora"] is not None:
            partes.append("En este momento estamos abiertos." if r["abierta_ahora"] else "En este momento estamos cerrados.")
        if r["direccion"]:
            partes.append(f"Nos encontramos en {r['direccion']}." + (f" Ubicación: {r['ubicacion']}" if r["ubicacion"] else ""))
        if r["formas_de_pago"]:
            partes.append("Aceptamos: " + ", ".join(r["formas_de_pago"]).lower() + ".")
        if r["telefono"]:
            partes.append(f"Teléfono: {r['telefono']}.")
        return "\n".join(partes)
    if nombre == "registrar_encargo":
        if r.get("registrado"):
            return (f"Su encargo de *{r['encargo']}* quedó registrado. Nuestro personal lo solicitará al proveedor "
                    "y le avisaremos por este medio.")
        if r.get("motivo") == "fuera_de_horario":
            return ("Le informamos que la confirmación del pedido no puede ser procesada fuera del horario laboral. "
                    f"Nuestro horario es: {r['horario_semana']}. Con gusto le atendemos en ese horario.")
        return "Una disculpa, no fue posible registrar su encargo. Una persona de nuestro equipo le atenderá."
    if nombre == "pasar_a_persona":
        if r.get("farmacia_abierta_ahora") is False:
            return "Con gusto. En este momento estamos fuera de horario; una persona de nuestro equipo le atenderá en cuanto abramos."
        return "Con gusto. En breve le atenderá una persona de nuestro equipo."
    return "Gracias por escribirnos."


def _llamar_bot(cliente, sistema, mensajes):
    ultimo = mensajes[-1]["content"]
    if ultimo and ultimo[0].get("type") == "tool_result":
        uso = next(b for b in mensajes[-2]["content"] if b.get("type") == "tool_use")
        return _Respuesta([_Bloque(type="text", text=_bot_respuesta(uso["name"], json.loads(ultimo[0]["content"])))], "end_turn")
    eleccion = _bot_elegir(mensajes)
    if eleccion is None:
        return _Respuesta([_Bloque(type="text", text=(
            "¡Buen día! Gracias por escribir a la farmacia (bot simulado del demo). ¿En qué podemos ayudarle? "
            "Puede preguntar por un producto, nuestro horario o ubicación."))], "end_turn")
    nombre, entrada = eleccion
    return _Respuesta([_Bloque(type="tool_use", id="demo-bot", name=nombre, input=entrada)], "tool_use")


def activar() -> None:
    from app.whatsapp import bot

    bot._llamar = _llamar_bot
    chat._llamar = _llamar
    buscador._llamar_foto = _foto
    sugerencias_pedido._llamar = _sugerencias
    ofertas._llamar = _ofertas
    configuracion_ia.cliente = lambda: object()
    configuracion_ia.estado = lambda: {"configurada": True, "termina_en": "DEMO", "modelo": "IA simulada"}
