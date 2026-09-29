"""Imagen de la pantalla de inicio: la sube el administrador y se guarda en
la base, por negocio."""

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


def subir(cliente, datos, tipo="application/octet-stream"):
    return cliente.put("/negocio/logo", content=datos, headers={"Content-Type": tipo})


def test_sin_imagen(como_admin):
    assert como_admin.get("/negocio").json()["logo_url"] is None
    assert como_admin.get("/negocio/logo").status_code == 404


@pytest.mark.parametrize("datos, tipo", [(PNG, "image/png"), (JPG, "image/jpeg"), (GIF, "image/gif"), (WEBP, "image/webp")])
def test_subir_y_ver(como_admin, datos, tipo):
    r = subir(como_admin, datos)
    assert r.status_code == 200
    url = r.json()["logo_url"]
    assert url.startswith("/negocio/logo?v=")
    imagen = como_admin.get(url)
    assert imagen.status_code == 200
    assert imagen.content == datos
    # El tipo sale de los bytes, no de lo que diga el navegador.
    assert imagen.headers["content-type"] == tipo


def test_cada_imagen_cambia_la_direccion(como_admin):
    primera = subir(como_admin, PNG).json()["logo_url"]
    segunda = subir(como_admin, JPG).json()["logo_url"]
    assert primera != segunda
    assert como_admin.get(segunda).content == JPG


@pytest.mark.parametrize("datos", [b"", b"hola", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', b"%PDF-1.4"])
def test_solo_imagenes(como_admin, datos):
    r = subir(como_admin, datos, "image/png")
    assert r.status_code == 422
    assert como_admin.get("/negocio").json()["logo_url"] is None


def test_maximo_5_mb(como_admin):
    assert subir(como_admin, PNG + b"\x00" * (5 * 1024 * 1024)).status_code == 413
    assert subir(como_admin, PNG + b"\x00" * (5 * 1024 * 1024 - len(PNG))).status_code == 200


def test_quitar(como_admin):
    subir(como_admin, PNG)
    r = como_admin.delete("/negocio/logo")
    assert r.status_code == 200
    assert r.json()["logo_url"] is None
    assert como_admin.get("/negocio/logo").status_code == 404


def test_solo_el_admin_la_cambia(como_admin, como_mostrador, como_bodega):
    subir(como_admin, PNG)
    for cliente in (como_mostrador, como_bodega):
        assert subir(cliente, JPG).status_code == 403
        assert cliente.delete("/negocio/logo").status_code == 403
        # Pero todos la ven en su pantalla de inicio.
        assert cliente.get("/negocio/logo").content == PNG


def test_sin_sesion(cliente):
    assert cliente.get("/negocio/logo").status_code == 401
    assert subir(cliente, PNG).status_code == 401


def test_cada_negocio_tiene_la_suya(como_admin, otro_negocio, crear_usuario, cliente_de):
    subir(como_admin, PNG)
    otro = cliente_de(crear_usuario(otro_negocio))
    assert otro.get("/negocio/logo").status_code == 404
    assert otro.get("/negocio").json()["logo_url"] is None


def test_put_negocio_no_cambia_la_imagen(como_admin):
    url = subir(como_admin, PNG).json()["logo_url"]
    como_admin.put("/negocio", json={"logo_url": "https://otro-sitio/x.png", "ticket_pie": "Gracias"})
    assert como_admin.get("/negocio").json()["logo_url"] == url
