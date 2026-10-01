"""Script del instalador para una base nueva: crea el negocio y su administrador."""

import sys

from sqlalchemy import delete, func, select

from app.core.seguridad import verificar_password
from app.models import Negocio, Usuario
from app.scripts import primer_negocio


def correr(db, monkeypatch, *argumentos):
    monkeypatch.setattr(primer_negocio, "SessionLocal", lambda: _SinCerrar(db))
    monkeypatch.setattr(primer_negocio, "pedir_password", lambda: "secreta123")
    monkeypatch.setattr(sys, "argv", ["primer_negocio", *argumentos])
    primer_negocio.main()


class _SinCerrar:
    """La sesión de la prueba, usada como `with SessionLocal() as db`."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False


def test_base_nueva(db, monkeypatch, capsys):
    db.execute(delete(Usuario))
    db.execute(delete(Negocio))
    correr(db, monkeypatch, "--nombre", " Farmacia  La Fe ", "--usuario", "diego", "--nombre-completo", "Diego Valerio")
    n = db.scalar(select(Negocio))
    u = db.scalar(select(Usuario))
    assert n.nombre == "Farmacia La Fe" and u.rol.value == "admin" and u.negocio_id == n.id
    assert verificar_password("secreta123", u.password_hash)


def test_si_ya_hay_negocio_no_cambia_nada(db, negocio, monkeypatch, capsys):
    antes = db.scalar(select(func.count()).select_from(Negocio))
    correr(db, monkeypatch, "--nombre", "Otra", "--usuario", "x", "--nombre-completo", "X")
    assert db.scalar(select(func.count()).select_from(Negocio)) == antes
    assert "no se cambió nada" in capsys.readouterr().out
