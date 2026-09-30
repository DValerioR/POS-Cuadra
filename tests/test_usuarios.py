"""Pantalla de usuarios: alta, cambios, activar/desactivar, contraseñas y
la regla de que siempre quede un administrador activo."""

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PASSWORD


def por_usuario(lista, nombre):
    return next(u for u in lista if u["nombre_usuario"] == nombre)


def entrar(nombre, password, negocio_id):
    c = TestClient(app)
    return c, c.post("/auth/login", json={"negocio_id": negocio_id, "usuario": nombre, "password": password})


def test_alta_y_entrar(como_admin, negocio):
    r = como_admin.post("/cuentas", json={"nombre_usuario": "cajera1", "nombre_completo": "  Ana   López ",
                                          "rol": "mostrador", "password": "secreta1"})
    assert r.status_code == 201, r.text
    ana = por_usuario(r.json(), "cajera1")
    assert (ana["nombre_completo"], ana["rol"], ana["activo"], ana["ultimo_acceso"]) == ("Ana López", "mostrador", True, None)
    _, login = entrar("cajera1", "secreta1", negocio.id)
    assert login.status_code == 200
    assert por_usuario(como_admin.get("/cuentas").json(), "cajera1")["ultimo_acceso"] is not None


def test_validaciones_de_alta(como_admin, admin):
    base = {"nombre_completo": "X", "rol": "bodega", "password": "secreta1"}
    assert como_admin.post("/cuentas", json={**base, "nombre_usuario": admin.nombre_usuario.upper()}).status_code in (400, 409, 422)
    assert como_admin.post("/cuentas", json={**base, "nombre_usuario": "con espacio"}).status_code in (400, 409, 422)
    assert como_admin.post("/cuentas", json={**base, "nombre_usuario": "corto", "password": "123"}).status_code in (400, 409, 422)
    assert como_admin.post("/cuentas", json={**base, "nombre_usuario": "rolmal", "rol": "jefe"}).status_code in (400, 409, 422)


def test_desactivar_corta_la_sesion(como_admin, cliente_de, mostrador):
    cajero = cliente_de(mostrador)
    assert cajero.get("/auth/yo").status_code == 200
    r = como_admin.put(f"/cuentas/{mostrador.id}", json={"activo": False})
    assert por_usuario(r.json(), mostrador.nombre_usuario)["activo"] is False
    assert cajero.get("/auth/yo").status_code == 401
    assert entrar(mostrador.nombre_usuario, PASSWORD, mostrador.negocio_id)[1].status_code == 401
    como_admin.put(f"/cuentas/{mostrador.id}", json={"activo": True})
    assert entrar(mostrador.nombre_usuario, PASSWORD, mostrador.negocio_id)[1].status_code == 200


def test_siempre_queda_un_admin(como_admin, admin, crear_usuario, negocio):
    from app.models import RolUsuario
    assert como_admin.put(f"/cuentas/{admin.id}", json={"activo": False}).status_code in (400, 409, 422)
    assert como_admin.put(f"/cuentas/{admin.id}", json={"rol": "bodega"}).status_code in (400, 409, 422)
    otro = crear_usuario(negocio, RolUsuario.ADMIN, nombre="hija")
    assert como_admin.put(f"/cuentas/{otro.id}", json={"rol": "bodega"}).status_code == 200
    assert como_admin.put(f"/cuentas/{admin.id}", json={"nombre_completo": "Dueña"}).status_code == 200


def test_restablecer_y_cambiar_mi_password(como_admin, cliente_de, bodega):
    sesion = cliente_de(bodega)
    assert como_admin.put(f"/cuentas/{bodega.id}/password", json={"password": "nueva123"}).status_code == 200
    assert sesion.get("/auth/yo").status_code == 401  # se cerraron sus sesiones
    c, login = entrar(bodega.nombre_usuario, "nueva123", bodega.negocio_id)
    assert login.status_code == 200
    assert c.put("/cuentas/yo/password", json={"actual": "otra", "nueva": "mejor123"}).status_code in (400, 409, 422)
    assert c.put("/cuentas/yo/password", json={"actual": "nueva123", "nueva": "mejor123"}).status_code == 204
    assert entrar(bodega.nombre_usuario, "mejor123", bodega.negocio_id)[1].status_code == 200


def test_solo_admin(como_bodega, bodega):
    assert como_bodega.get("/cuentas").status_code == 403
    assert como_bodega.put(f"/cuentas/{bodega.id}", json={"rol": "admin"}).status_code == 403


def test_otro_negocio(como_admin, crear_usuario, otro_negocio):
    ajeno = crear_usuario(otro_negocio)
    assert como_admin.put(f"/cuentas/{ajeno.id}", json={"activo": False}).status_code == 404
    assert ajeno.nombre_usuario not in [u["nombre_usuario"] for u in como_admin.get("/cuentas").json()]
