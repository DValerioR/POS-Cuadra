"""Actualizaciones automáticas (ver instalador\\actualizar.ps1).

La tarea de Windows "Cuadra - actualizar" revisa GitHub cada 30 minutos e
instala la versión nueva cuando la farmacia está cerrada; deja lo que pasó en
datos/actualizacion.json. Aquí se lee ese estado para la pantalla
Configuración → Actualizaciones y la campana, se dice qué versión está
corriendo (para que las pantallas abiertas sepan que hay que recargar) y se
pide "Instalar ahora".
"""

import json
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ESTADO = RAIZ / "datos" / "actualizacion.json"
BANDERA = RAIZ / "datos" / "actualizar_ahora"
TAREA = "Cuadra - actualizar"


def _version_de_git() -> str | None:
    """El commit que está corriendo, leído de .git sin llamar a git."""
    git = RAIZ / ".git"
    try:
        cabeza = (git / "HEAD").read_text().strip()
        if not cabeza.startswith("ref:"):
            return cabeza[:7]
        ref = cabeza.split(" ", 1)[1]
        archivo = git / ref
        if archivo.exists():
            return archivo.read_text().strip()[:7]
        for linea in (git / "packed-refs").read_text().splitlines():
            if linea.endswith(" " + ref):
                return linea[:7]
    except OSError:
        pass
    return None


# Se lee al arrancar: es la versión de este proceso (si el código cambia, el servidor se reinicia).
VERSION = _version_de_git() or "desarrollo"


def tarea_instalada() -> bool:
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", TAREA], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def estado() -> dict:
    try:
        datos = json.loads(ESTADO.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        datos = {}
    return {
        "version": VERSION,
        "automaticas": tarea_instalada(),
        "estado": datos.get("estado"),  # al_dia | pendiente | instalando | ok | error
        "mensaje": datos.get("mensaje"),
        "disponible": datos.get("disponible"),
        "cambios": [c for c in (datos.get("cambios") or []) if c],
        "ultima_revision": datos.get("ultima_revision"),
        "instalada_el": datos.get("instalada_el"),
        "historial": [h for h in (datos.get("historial") or []) if h][:10],
        "pedida": BANDERA.exists(),
    }


def necesita_atencion() -> bool:
    """La última actualización falló (se avisa en la campana)."""
    return estado()["estado"] == "error"


def instalar_ahora() -> dict:
    """Pide a la tarea que busque e instale ya, sin esperar a que cierre la farmacia."""
    if not tarea_instalada():
        raise RuntimeError("Las actualizaciones automáticas solo funcionan en la computadora donde se instaló el servidor.")
    BANDERA.parent.mkdir(exist_ok=True)
    BANDERA.write_text("1")
    r = subprocess.run(["schtasks", "/Run", "/TN", TAREA], capture_output=True, timeout=15)
    if r.returncode != 0:
        raise RuntimeError("No se pudo iniciar la tarea de actualización.")
    return estado()
