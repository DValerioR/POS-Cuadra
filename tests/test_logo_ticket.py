"""El logo del negocio: fondo transparente al subirlo, conversión a puntos
para la impresora y el logo en el ticket."""

from io import BytesIO

from PIL import Image, ImageDraw

from app.impresion.escpos import GS
from app.impresion.logo import fondo_transparente, raster_para_ticket
from app.models import ModoImpresora
from tests.test_impresion import configurar, impresora_red  # noqa: F401  (fixtures)
from tests.test_ventas import caja, r, shampoo, vender  # noqa: F401  (fixtures)


def logo_de_prueba(fondo=(255, 255, 255)) -> bytes:
    """Óvalo azul con una barra naranja (como el logo de La Fe) sobre `fondo`."""
    img = Image.new("RGB", (300, 200), fondo)
    d = ImageDraw.Draw(img)
    d.ellipse((10, 10, 290, 190), fill=(95, 128, 196), outline=(230, 120, 30), width=6)
    d.rectangle((80, 80, 220, 120), fill=(230, 120, 30))
    salida = BytesIO()
    img.save(salida, "JPEG")
    return salida.getvalue()


def test_fondo_transparente():
    png, tipo = fondo_transparente(logo_de_prueba())
    img = Image.open(BytesIO(png))
    assert tipo == "image/png" and img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0 and img.getpixel((150, 100))[3] == 255  # esquina transparente, centro no
    assert fondo_transparente(logo_de_prueba(fondo=(40, 40, 40))) is None  # foto / fondo de color: se deja igual
    assert fondo_transparente(b"no es imagen") is None


def test_raster_centrado():
    bytes_renglon, alto, bits = raster_para_ticket(logo_de_prueba(), 42)
    assert bytes_renglon == 64 and alto == 112 and len(bits) == 64 * 112  # 512 puntos; logo de 168 × 112 (alto máximo)
    renglon = bits[56 * 64:57 * 64]  # a media altura: la barra naranja sale en negro, al centro
    assert not any(renglon[:15]) and not any(renglon[-15:]) and any(renglon[27:37])
    assert raster_para_ticket(logo_de_prueba(), 32)[0] == 48  # papel de 58 mm
    assert raster_para_ticket(logo_de_prueba(), 48)[0] == 72  # 48 columnas puestas a mano: 576 puntos


def test_logo_al_subir_y_en_el_ticket(como_admin, db, negocio, caja, shampoo, impresora_red):
    r_subir = como_admin.put("/negocio/marca", content=logo_de_prueba(), headers={"Content-Type": "image/jpeg"})
    assert r_subir.status_code == 200
    n = r_subir.json()
    assert n["marca_url"].startswith("/negocio/marca?v=") and n["logo_url"] is None  # la imagen de inicio no cambia
    assert como_admin.get(n["marca_url"]).headers["content-type"] == "image/png"
    assert como_admin.get("/negocio/marca-ticket").headers["content-type"] == "image/png"

    configurar(db, caja, ModoImpresora.RED, impresora_red.direccion)
    vender(como_admin, caja, [r(shampoo, 1)], efectivo="200")
    assert GS + b"v0" not in impresora_red.ultimo()  # sin la casilla, no va el logo
    assert como_admin.put("/negocio", json={"ticket_logo": True}).json()["ticket_logo"] is True
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="200").json()
    assert GS + b"v0" in impresora_red.ultimo()
    assert "[logo]" in como_admin.get(f"/ventas/{v['id']}/ticket").text


def test_imagen_de_inicio_y_logo_son_independientes(como_admin):
    marca = como_admin.put("/negocio/marca", content=logo_de_prueba(), headers={"Content-Type": "image/jpeg"}).json()["marca_url"]
    inicio = como_admin.put("/negocio/logo", content=logo_de_prueba(fondo=(40, 40, 40)), headers={"Content-Type": "image/jpeg"}).json()
    assert inicio["marca_url"] == marca and inicio["logo_url"].startswith("/negocio/logo?v=")
    assert como_admin.delete("/negocio/logo").json()["marca_url"] == marca
    sin_marca = como_admin.delete("/negocio/marca").json()
    assert sin_marca["marca_url"] is None
    assert como_admin.get("/negocio/marca").status_code == 404
