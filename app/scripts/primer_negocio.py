"""Deja lista una base nueva (la usa el instalador cuando no se restaura un
respaldo): crea el negocio y su primer administrador. La contraseña se pide
sin mostrarse. Si la base ya tiene un negocio, no hace nada.

Uso:
    python -m app.scripts.primer_negocio --nombre "Farmacia La Fe" --usuario diego --nombre-completo "Diego Valerio"
"""

import argparse
import sys
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.seguridad import hashear_password
from app.models import Negocio, RolUsuario, Usuario
from app.scripts.crear_usuario import pedir_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Crear el negocio y su primer administrador en una base nueva")
    parser.add_argument("--nombre", required=True, help="nombre del negocio (sale en las pantallas y el ticket)")
    parser.add_argument("--usuario", required=True, help="usuario del administrador para iniciar sesión")
    parser.add_argument("--nombre-completo", required=True, help="nombre completo del administrador")
    args = parser.parse_args()

    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Negocio)):
            print("La base ya tiene un negocio: no se cambió nada.")
            return
        nombre = " ".join(args.nombre.split())
        if not nombre:
            sys.exit("Falta el nombre del negocio.")
        negocio = Negocio(nombre=nombre, redondeo_precio_venta=Decimal(1))
        db.add(negocio)
        db.flush()
        print(f"Contraseña del administrador '{args.usuario}' (al menos 6 caracteres):")
        db.add(Usuario(negocio_id=negocio.id, nombre_usuario=args.usuario.strip(), nombre_completo=args.nombre_completo.strip(),
                       password_hash=hashear_password(pedir_password()), rol=RolUsuario.ADMIN))
        db.commit()
        print(f"Listo: negocio '{negocio.nombre}' (id {negocio.id}) con su administrador '{args.usuario}'.")


if __name__ == "__main__":
    main()
