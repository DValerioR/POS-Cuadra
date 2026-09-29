"""Respaldo de la base de datos con pg_dump.

Uso:
    python -m app.scripts.respaldar [--carpeta backups] [--conservar 30]

Guarda el respaldo en backups/<Negocio>/pos_AAAAMMDD_HHMMSS.dump (formato
propio de PostgreSQL), una carpeta por negocio (ej. backups/FarmaciaLaFe).
Todos los negocios comparten la misma base, así que cada respaldo trae la
base completa. Después de crearlo se revisa que se pueda leer
(pg_restore --list) y se borran los más viejos, dejando los últimos
`--conservar` de cada negocio.

Para restaurar (borra lo que haya en la base de destino):
    pg_restore --clean --if-exists --no-owner -d pos backups/FarmaciaLaFe/pos_....dump

Lo programa una tarea de Windows (ver README.md, "Respaldos").
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings

RAIZ = Path(__file__).resolve().parents[2]
BINARIOS = [Path(r"C:\Program Files\PostgreSQL") / v / "bin" for v in ("18", "17", "16", "15")]


def _programa(nombre: str) -> str:
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado
    for carpeta in BINARIOS:
        ruta = carpeta / f"{nombre}.exe"
        if ruta.exists():
            return str(ruta)
    sys.exit(f"No se encontró {nombre}; instala las herramientas de PostgreSQL o agrégalas al PATH.")


def carpeta_de(nombre: str) -> str:
    """'Farmacia La Fe' -> 'FarmaciaLaFe' (sin acentos, espacios ni signos)."""
    sin_acentos = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    limpio = "".join(p[:1].upper() + p[1:] for p in re.split(r"[^A-Za-z0-9]+", sin_acentos) if p)
    return limpio or "Negocio"


def main() -> None:
    parser = argparse.ArgumentParser(description="Respaldar la base de datos del POS")
    parser.add_argument("--carpeta", type=Path, default=RAIZ / "backups")
    parser.add_argument("--conservar", type=int, default=30, help="respaldos que se dejan por negocio")
    args = parser.parse_args()

    url = make_url(settings.database_url)
    with create_engine(url).connect() as con:
        negocios = [n for (n,) in con.execute(text("SELECT nombre FROM negocios ORDER BY id"))]
    if not negocios:
        sys.exit("La base no tiene negocios; no hay nada que respaldar.")

    # La contraseña va por variable de entorno, no en la línea de comandos.
    entorno = {**os.environ, "PGPASSWORD": url.password or ""}
    conexion = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres"]
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    pg_dump, pg_restore = _programa("pg_dump"), _programa("pg_restore")

    temporal = args.carpeta / f".pos_{sello}.dump"
    args.carpeta.mkdir(parents=True, exist_ok=True)
    resultado = subprocess.run([pg_dump, *conexion, "-Fc", "-f", str(temporal), url.database],
                               env=entorno, capture_output=True, text=True)
    if resultado.returncode != 0:
        temporal.unlink(missing_ok=True)
        sys.exit(f"pg_dump falló: {resultado.stderr.strip()}")
    revision = subprocess.run([pg_restore, "--list", str(temporal)], capture_output=True, text=True)
    if revision.returncode != 0 or "TABLE DATA" not in revision.stdout:
        temporal.unlink(missing_ok=True)
        sys.exit(f"El respaldo no se pudo leer: {revision.stderr.strip()}")

    for negocio in negocios:
        destino = args.carpeta / carpeta_de(negocio)
        destino.mkdir(parents=True, exist_ok=True)
        archivo = destino / f"{url.database}_{sello}.dump"
        shutil.copy2(temporal, archivo)
        viejos = sorted(destino.glob(f"{url.database}_*.dump"))[: -args.conservar or None]
        for v in viejos:
            v.unlink()
        print(f"Respaldo listo: {archivo} ({archivo.stat().st_size / 1_048_576:.1f} MB); borrados {len(viejos)} viejos")
    temporal.unlink()


if __name__ == "__main__":
    main()
