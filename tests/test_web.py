"""Las pantallas se sirven y no tapan las rutas del API."""

import pytest

from tests.conftest import PASSWORD


@pytest.mark.parametrize("pagina", ["login", "inicio", "venta", "turno", "devoluciones", "notificaciones", "inventario", "catalogo", "mercancia", "faltantes", "pedidos", "tableta", "usuarios", "cajas-impresoras", "reporte-ventas"])
def test_paginas(cliente, pagina):
    r = cliente.get(f"/{pagina}")
    assert r.status_code == 200
    assert "alpine-3.17.4.min.js" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_raiz_lleva_al_inicio(cliente):
    r = cliente.get("/", follow_redirects=False)
    assert r.headers["location"] == "/inicio"


def test_pagina_desconocida_redirige(cliente):
    assert cliente.get("/no-existe", follow_redirects=False).headers["location"] == "/inicio"


@pytest.mark.parametrize("archivo", ["js/api.js", "js/inicio.js", "js/notificaciones.js", "js/inventario.js", "js/catalogo.js", "js/entradas.js", "js/venta.js", "js/devoluciones.js", "css/pos.css", "iconos.svg", "vendor/alpine-3.17.4.min.js",
                                     "app/icono-32.png", "app/icono-192.png", "app/icono-512.png"])
def test_estaticos(cliente, archivo):
    assert cliente.get(f"/static/{archivo}").status_code == 200


def test_icono_y_manifiesto(cliente):
    r = cliente.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/x-icon"
    m = cliente.get("/static/app/manifest.webmanifest")
    assert m.headers["content-type"].startswith("application/manifest+json")
    manifiesto = m.json()
    assert manifiesto["name"] == "Cuadra"
    for icono in manifiesto["icons"]:
        assert cliente.get(icono["src"]).status_code == 200


def test_api_sigue_teniendo_prioridad(cliente):
    assert cliente.get("/productos").status_code == 401  # API, no la página
    assert cliente.get("/health").json() == {"status": "ok"}


def test_login_sin_negocio_usa_el_predeterminado(cliente, admin, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "negocio_predeterminado", admin.negocio_id)
    r = cliente.post("/auth/login", json={"usuario": f"  {admin.nombre_usuario} ", "password": PASSWORD})
    assert r.status_code == 200
