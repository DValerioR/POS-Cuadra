from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import RolUsuario, Sesion
from tests.conftest import PASSWORD


def login(cliente, usuario, password=PASSWORD, negocio_id=None):
    return cliente.post("/auth/login", json={
        "negocio_id": negocio_id or usuario.negocio_id,
        "usuario": usuario.nombre_usuario,
        "password": password,
    })


def test_health_no_requiere_sesion(cliente):
    assert cliente.get("/health").status_code == 200


@pytest.mark.parametrize("ruta", ["/productos", "/categorias", "/negocio", "/inventario/ajustes", "/auth/yo"])
def test_sin_sesion_da_401(cliente, ruta):
    assert cliente.get(ruta).status_code == 401


def test_login_correcto_deja_cookie_httponly(cliente, admin):
    r = login(cliente, admin)
    assert r.status_code == 200
    assert r.json()["usuario"]["nombre_usuario"] == admin.nombre_usuario
    assert "httponly" in r.headers["set-cookie"].lower()
    assert cliente.get("/auth/yo").json()["id"] == admin.id


def test_password_incorrecta(cliente, admin):
    r = login(cliente, admin, password="mala")
    assert r.status_code == 401
    assert r.json()["detail"] == "Usuario o contraseña incorrectos"


def test_usuario_inexistente_da_el_mismo_error(cliente, negocio):
    r = cliente.post("/auth/login", json={"negocio_id": negocio.id, "usuario": "nadie", "password": PASSWORD})
    assert r.status_code == 401
    assert r.json()["detail"] == "Usuario o contraseña incorrectos"


def test_usuario_dado_de_baja_no_entra(cliente, negocio, crear_usuario):
    baja = crear_usuario(negocio, RolUsuario.ADMIN, nombre="baja", activo=False)
    assert login(cliente, baja).status_code == 401


def test_usuario_no_entra_a_otro_negocio(cliente, admin, otro_negocio):
    assert login(cliente, admin, negocio_id=otro_negocio.id).status_code == 401


def test_token_bearer(cliente, admin):
    token = login(cliente, admin).json()["token"]
    otro = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert otro.get("/auth/yo").status_code == 200


def test_token_falso(cliente):
    otro = TestClient(app, headers={"Authorization": "Bearer inventado"})
    assert otro.get("/auth/yo").status_code == 401


def test_encabezado_tiene_prioridad_sobre_cookie(como_admin):
    assert como_admin.get("/auth/yo", headers={"Authorization": "Bearer malo"}).status_code == 401


def test_solo_se_guarda_el_hash_del_token(cliente, admin, db):
    token = login(cliente, admin).json()["token"]
    sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == admin.id))
    assert sesion.token_hash != token
    assert len(sesion.token_hash) == 64  # SHA-256 en hexadecimal


def test_logout_invalida_el_token(cliente, admin):
    token = login(cliente, admin).json()["token"]
    assert cliente.post("/auth/logout").status_code == 204
    otro = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert otro.get("/auth/yo").status_code == 401


def test_sesion_vencida(como_admin, admin, db):
    sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == admin.id))
    sesion.expira = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert como_admin.get("/auth/yo").status_code == 401


def test_desactivar_usuario_corta_su_sesion(como_bodega, bodega, db):
    bodega.activo = False
    db.commit()
    assert como_bodega.get("/auth/yo").status_code == 401


def test_docs_muestra_boton_authorize(cliente):
    spec = cliente.get("/openapi.json").json()
    assert "HTTPBearer" in spec["components"]["securitySchemes"]
