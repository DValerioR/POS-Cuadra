"""Respaldos de la base de datos.

Un respaldo es un archivo de pg_dump en formato "custom" (.dump) que guarda
todo: productos, ventas, usuarios... Se restaura con pg_restore (ver
docs/RESPALDOS.md). Cada respaldo:
- se escribe en `settings.carpeta_respaldos` (por omisión datos/respaldos);
- si hay `carpeta_respaldos_copia` (una USB, una carpeta de Drive/OneDrive),
  se copia también ahí;
- los automáticos se van borrando: solo se guardan los últimos
  `respaldos_a_conservar`. Los hechos a mano no se borran solos.

Automático: mientras el servidor está prendido, cada 30 minutos revisa si el
último respaldo tiene más de 24 horas y, si es así, hace uno. Nunca corre
sobre la base de pruebas (la que termina en "_test"), así que las pruebas y el
demo no lo activan. El resultado del último intento queda en estado.json en
la carpeta, y si falló o hace más de un día que no hay respaldo, la campana de
notificaciones lo avisa.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core import config
from app.core.config import settings
from app.services.errores import NoEncontrado, OperacionInvalida

log = logging.getLogger(__name__)

NOMBRE = re.compile(r"^pos_\d{8}_\d{6}_(auto|manual)\.dump$")
CADA = timedelta(hours=24)
REVISAR_CADA_SEGUNDOS = 30 * 60
ATRASO_AVISO = timedelta(hours=26)  # un poco más de un día: margen para el horario de la farmacia
_candado = threading.Lock()


def carpeta() -> Path:
    ruta = Path(settings.carpeta_respaldos)
    if not ruta.is_absolute():
        ruta = config.ENV_PATH.parent / ruta  # relativa a la raíz del proyecto, no a donde se arrancó
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _pg_dump() -> str:
    """Ruta de pg_dump: la del .env (PG_BIN), la del PATH o la instalación de PostgreSQL más nueva."""
    if settings.pg_bin:
        candidato = Path(settings.pg_bin) / ("pg_dump.exe" if os.name == "nt" else "pg_dump")
        if candidato.exists():
            return str(candidato)
    en_path = shutil.which("pg_dump")
    if en_path:
        return en_path
    instalaciones = sorted(Path(r"C:\Program Files\PostgreSQL").glob("*/bin/pg_dump.exe"),
                           key=lambda p: int(p.parent.parent.name) if p.parent.parent.name.isdigit() else 0)
    if instalaciones:
        return str(instalaciones[-1])
    raise OperacionInvalida("No se encontró pg_dump (PostgreSQL). Indica su carpeta con PG_BIN en el .env.")


def _leer_estado() -> dict:
    try:
        return json.loads((carpeta() / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_estado(**cambios) -> None:
    estado = {**_leer_estado(), **cambios}
    (carpeta() / "estado.json").write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")


def archivos() -> list[dict]:
    """Respaldos en la carpeta, el más nuevo primero."""
    lista = []
    for f in carpeta().iterdir():
        if NOMBRE.match(f.name):
            st = f.stat()
            lista.append({"nombre": f.name, "tamano": st.st_size, "automatico": f.name.endswith("_auto.dump"),
                          "fecha": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
    return sorted(lista, key=lambda x: x["nombre"], reverse=True)


def hacer(automatico: bool = False) -> dict:
    """Hace un respaldo ahora. Regresa el archivo creado. Solo uno a la vez."""
    if not _candado.acquire(blocking=False):
        raise OperacionInvalida("Ya se está haciendo un respaldo; espera a que termine")
    try:
        _guardar_estado(ultimo_intento=_ahora().isoformat())
        try:
            archivo = _pg_dump_a_archivo(automatico)
        except OperacionInvalida as e:
            _guardar_estado(error=e.args[0])
            raise
        copia_error = _copiar(archivo)
        if automatico:
            _limpiar()
        _guardar_estado(ultimo_ok=_ahora().isoformat(), ultimo_archivo=archivo.name, error=None, copia_error=copia_error)
        log.info("Respaldo hecho: %s", archivo)
        return {"nombre": archivo.name, "tamano": archivo.stat().st_size, "copia_error": copia_error}
    finally:
        _candado.release()


def _pg_dump_a_archivo(automatico: bool) -> Path:
    url = make_url(settings.database_url)
    nombre = f"pos_{datetime.now():%Y%m%d_%H%M%S}_{'auto' if automatico else 'manual'}.dump"
    destino = carpeta() / nombre
    temporal = destino.with_suffix(".tmp")
    entorno = {**os.environ, "PGPASSWORD": url.password or ""}
    try:
        r = subprocess.run(
            [_pg_dump(), "-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres",
             "-d", url.database, "-F", "c", "-f", str(temporal)],
            env=entorno, capture_output=True, text=True, timeout=30 * 60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        temporal.unlink(missing_ok=True)
        raise OperacionInvalida(f"No se pudo hacer el respaldo: {e}")
    if r.returncode != 0 or not temporal.exists() or temporal.stat().st_size == 0:
        temporal.unlink(missing_ok=True)
        detalle = (r.stderr or "").strip().splitlines()[-1:] or ["sin detalle"]
        raise OperacionInvalida(f"pg_dump falló: {detalle[0]}")
    temporal.replace(destino)  # que un corte a la mitad no deje un respaldo incompleto con nombre bueno
    return destino


def _copiar(archivo: Path) -> str | None:
    """Copia a la carpeta extra, si hay. Si falla (USB desconectada...), lo dice pero el respaldo queda."""
    if not settings.carpeta_respaldos_copia:
        return None
    try:
        destino = Path(settings.carpeta_respaldos_copia)
        destino.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archivo, destino / archivo.name)
        return None
    except OSError as e:
        return f"No se pudo copiar a {settings.carpeta_respaldos_copia}: {e.strerror or e}"


def _limpiar() -> None:
    automaticos = [a for a in archivos() if a["automatico"]]
    for viejo in automaticos[max(settings.respaldos_a_conservar, 1):]:
        (carpeta() / viejo["nombre"]).unlink(missing_ok=True)


def ruta_de(nombre: str) -> Path:
    """Ruta de un respaldo por su nombre (solo nombres de respaldo: nada de rutas)."""
    if not NOMBRE.match(nombre) or not (carpeta() / nombre).exists():
        raise NoEncontrado("Respaldo no encontrado")
    return carpeta() / nombre


def estado() -> dict:
    e = _leer_estado()
    ultimo_ok = datetime.fromisoformat(e["ultimo_ok"]) if e.get("ultimo_ok") else None
    atrasado = ultimo_ok is None or _ahora() - ultimo_ok > ATRASO_AVISO
    return {
        "ultimo_ok": e.get("ultimo_ok"), "ultimo_archivo": e.get("ultimo_archivo"), "ultimo_intento": e.get("ultimo_intento"),
        "error": e.get("error"), "copia_error": e.get("copia_error"),
        "atrasado": atrasado, "necesita_atencion": bool(e.get("error")) or atrasado,
        "automaticos": automaticos_activos(), "carpeta": str(carpeta().resolve()),
        "copia": settings.carpeta_respaldos_copia, "conservar": settings.respaldos_a_conservar,
        "archivos": archivos(),
    }


# --- Automático -------------------------------------------------------------------------


def automaticos_activos() -> bool:
    return settings.respaldos_automaticos and not (make_url(settings.database_url).database or "").endswith("_test")


def toca_respaldo() -> bool:
    e = _leer_estado()
    if not e.get("ultimo_ok"):
        return True
    return _ahora() - datetime.fromisoformat(e["ultimo_ok"]) >= CADA


def _ciclo(parar: threading.Event) -> None:
    parar.wait(60)  # que el servidor termine de arrancar
    while not parar.is_set():
        try:
            if toca_respaldo():
                hacer(automatico=True)
        except Exception:  # noqa: BLE001 — el hilo no debe morir; el error queda en estado.json
            log.exception("Falló el respaldo automático")
        parar.wait(REVISAR_CADA_SEGUNDOS)


def iniciar_automaticos() -> threading.Event | None:
    """Arranca el hilo de respaldos automáticos (si aplica). Regresa el evento para detenerlo."""
    if not automaticos_activos():
        return None
    parar = threading.Event()
    threading.Thread(target=_ciclo, args=(parar,), name="respaldos", daemon=True).start()
    return parar
