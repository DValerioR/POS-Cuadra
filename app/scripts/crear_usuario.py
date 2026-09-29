"""Crea un usuario desde la terminal. La contraseña se pide sin mostrarse.

Uso:
    python -m app.scripts.crear_usuario --negocio 1 --usuario diego --nombre "Diego Valerio" --rol admin
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.seguridad import MAX_BYTES_PASSWORD, hashear_password
from app.models import Negocio, RolUsuario, Usuario


def pedir_password() -> str:
    while True:
        password = getpass.getpass("Contraseña: ")
        if len(password) < 6:
            print("Debe tener al menos 6 caracteres.")
            continue
        if len(password.encode("utf-8")) > MAX_BYTES_PASSWORD:
            print(f"Debe tener como máximo {MAX_BYTES_PASSWORD} bytes.")
            continue
        if getpass.getpass("Repite la contraseña: ") != password:
            print("No coinciden, intenta de nuevo.")
            continue
        return password


def main() -> None:
    parser = argparse.ArgumentParser(description="Crear un usuario del POS")
    parser.add_argument("--negocio", type=int, required=True)
    parser.add_argument("--usuario", required=True, help="nombre de usuario para iniciar sesión")
    parser.add_argument("--nombre", required=True, help="nombre completo")
    parser.add_argument("--rol", required=True, choices=[r.value for r in RolUsuario])
    args = parser.parse_args()

    with SessionLocal() as db:
        if db.get(Negocio, args.negocio) is None:
            sys.exit(f"No existe el negocio {args.negocio}.")
        existe = db.scalar(
            select(Usuario).where(Usuario.negocio_id == args.negocio, Usuario.nombre_usuario == args.usuario)
        )
        if existe:
            sys.exit(f"Ya existe el usuario '{args.usuario}' en ese negocio.")

        usuario = Usuario(
            negocio_id=args.negocio,
            nombre_usuario=args.usuario,
            nombre_completo=args.nombre,
            password_hash=hashear_password(pedir_password()),
            rol=RolUsuario(args.rol),
        )
        db.add(usuario)
        db.commit()
        print(f"Usuario '{usuario.nombre_usuario}' creado con rol {usuario.rol.value} (id {usuario.id}).")


if __name__ == "__main__":
    main()
