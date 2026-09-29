"""Configuración común de las pruebas.

Las pruebas usan una base de datos aparte: la misma de .env con "_test" al
final del nombre (pos -> pos_test). Se crea sola si no existe, y al inicio
de cada corrida se borra su contenido y se reconstruye con las migraciones
de Alembic (así también se prueban las migraciones).

Cada prueba corre dentro de una transacción que se deshace al terminar, así
que las pruebas no se estorban entre sí y nunca tocan los datos reales.
"""

from collections.abc import Iterator
from pathlib import Path

import bcrypt
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings

# --- Apuntar todo a la base de prueba ANTES de importar la app -------------
_url_real = make_url(settings.database_url)
_url_prueba = _url_real.set(database=f"{_url_real.database}_test")
if not _url_prueba.database.endswith("_test"):  # candado: nunca borrar otra base
    raise RuntimeError("La base de pruebas debe terminar en _test")
settings.database_url = _url_prueba.render_as_string(hide_password=False)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Negocio, RolUsuario, Usuario  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PASSWORD = "secreta1"
# bcrypt es lento a propósito (costo 12, ~0.4 s por login). En las pruebas se
# usa costo 4: verificar toma el costo del propio hash, así que el login se
# prueba igual pero rápido. La app real sigue usando hashear_password.
_PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()


def _crear_base_si_no_existe() -> None:
    admin = create_engine(_url_real.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as con:
        existe = con.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": _url_prueba.database}
        ).scalar()
        if not existe:
            con.execute(text(f'CREATE DATABASE "{_url_prueba.database}"'))
    admin.dispose()


def _alembic_config() -> Config:
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    return config


@pytest.fixture(scope="session", autouse=True)
def base_de_prueba() -> Iterator[None]:
    assert engine.url.database.endswith("_test")
    _crear_base_si_no_existe()
    with engine.begin() as con:
        con.execute(text("DROP SCHEMA public CASCADE"))
        con.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(), "head")
    yield
    engine.dispose()


@pytest.fixture
def alembic_config() -> Config:
    return _alembic_config()


@pytest.fixture
def db() -> Iterator[Session]:
    """Sesión dentro de una transacción que se deshace al final. Los commit()
    del código solo cierran un savepoint, así que nada queda guardado."""
    conexion = engine.connect()
    transaccion = conexion.begin()
    # Misma configuración que SessionLocal (autoflush=False).
    sesion = Session(bind=conexion, join_transaction_mode="create_savepoint", autoflush=False)
    app.dependency_overrides[get_db] = lambda: sesion
    try:
        yield sesion
    finally:
        app.dependency_overrides.pop(get_db, None)
        sesion.close()
        transaccion.rollback()
        conexion.close()


# --- Datos de apoyo -------------------------------------------------------

@pytest.fixture
def negocio(db: Session) -> Negocio:
    n = Negocio(nombre="Farmacia de Prueba")
    db.add(n)
    db.commit()
    return n


@pytest.fixture
def otro_negocio(db: Session) -> Negocio:
    n = Negocio(nombre="Otro Negocio")
    db.add(n)
    db.commit()
    return n


@pytest.fixture
def crear_usuario(db: Session):
    def crear(negocio: Negocio, rol: RolUsuario = RolUsuario.ADMIN, nombre: str | None = None, activo: bool = True) -> Usuario:
        u = Usuario(
            negocio_id=negocio.id,
            nombre_usuario=nombre or f"{rol.value}{negocio.id}",
            nombre_completo=nombre or rol.value,
            password_hash=_PASSWORD_HASH,
            rol=rol,
            activo=activo,
        )
        db.add(u)
        db.commit()
        return u

    return crear


@pytest.fixture
def cliente(db: Session) -> TestClient:
    """Cliente sin sesión."""
    return TestClient(app)


@pytest.fixture
def cliente_de(db: Session):
    """cliente_de(usuario) -> TestClient con sesión iniciada como ese usuario."""
    def iniciar(usuario: Usuario) -> TestClient:
        c = TestClient(app)
        r = c.post("/auth/login", json={
            "negocio_id": usuario.negocio_id, "usuario": usuario.nombre_usuario, "password": PASSWORD,
        })
        assert r.status_code == 200, r.text
        return c

    return iniciar


@pytest.fixture
def admin(negocio, crear_usuario) -> Usuario:
    return crear_usuario(negocio, RolUsuario.ADMIN)


@pytest.fixture
def bodega(negocio, crear_usuario) -> Usuario:
    return crear_usuario(negocio, RolUsuario.BODEGA)


@pytest.fixture
def mostrador(negocio, crear_usuario) -> Usuario:
    return crear_usuario(negocio, RolUsuario.MOSTRADOR)


@pytest.fixture
def como_admin(cliente_de, admin) -> TestClient:
    return cliente_de(admin)


@pytest.fixture
def como_bodega(cliente_de, bodega) -> TestClient:
    return cliente_de(bodega)


@pytest.fixture
def como_mostrador(cliente_de, mostrador) -> TestClient:
    return cliente_de(mostrador)
