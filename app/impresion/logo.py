"""El logo del negocio: quitarle el fondo blanco al subirlo y convertirlo en
puntos para la impresora térmica.

La impresora solo imprime puntos negros, así que el logo a color se pasa a
tres tonos: negro donde hay color fuerte u oscuro (letras, contornos), gris
claro (una trama de puntos) en los colores medios (fondos) y blanco en lo
claro. Así, en un logo con letras de color sobre un fondo de otro color, las
letras siguen leyéndose.
"""

from functools import lru_cache
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageDraw

MAGENTA = (255, 0, 255)


def fondo_transparente(datos: bytes) -> tuple[bytes, str] | None:
    """Si las cuatro esquinas son casi blancas (un logo sobre fondo blanco),
    regresa (PNG con ese fondo transparente, "image/png"); si no (una foto,
    un fondo de color), None para dejar la imagen como está."""
    try:
        imagen = Image.open(BytesIO(datos))
        imagen.load()
    except Exception:
        return None
    if getattr(imagen, "is_animated", False):
        return None
    rgba = imagen.convert("RGBA")
    base = rgba.convert("RGB")
    ancho, alto = base.size
    esquinas = [(0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1)]
    if not all(min(base.getpixel(e)) >= 235 for e in esquinas):
        return None
    for esquina in esquinas:
        if base.getpixel(esquina) != MAGENTA:
            ImageDraw.floodfill(base, esquina, MAGENTA, thresh=60)
    alfa = Image.new("L", base.size, 255)
    pix_base, pix_alfa = base.load(), alfa.load()
    for y in range(alto):
        for x in range(ancho):
            if pix_base[x, y] == MAGENTA:
                pix_alfa[x, y] = 0
    rgba.putalpha(alfa)
    salida = BytesIO()
    rgba.save(salida, "PNG", optimize=True)
    return salida.getvalue(), "image/png"


def _tinta(r: int, g: int, b: int) -> float:
    """0 = papel, 1 = negro: lo más fuerte entre qué tan colorido y qué tan oscuro."""
    croma = (max(r, g, b) - min(r, g, b)) / 255
    oscuro = 1 - (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return max(croma, oscuro)


@lru_cache(maxsize=8)
def _raster(huella: str, datos: bytes, ancho_papel: int, ancho_logo: int, alineacion: str) -> tuple[int, int, bytes]:
    imagen = Image.open(BytesIO(datos)).convert("RGBA")
    blanco = Image.new("RGBA", imagen.size, (255, 255, 255, 255))
    blanco.alpha_composite(imagen)
    ancho_logo = min(ancho_logo, ancho_papel)
    alto = max(1, round(imagen.height * ancho_logo / imagen.width))
    chica = blanco.convert("RGB").resize((ancho_logo, alto), Image.LANCZOS)
    inicio = {"derecha": ancho_papel - ancho_logo, "centro": (ancho_papel - ancho_logo) // 2}.get(alineacion, 0)
    bytes_renglon = (ancho_papel + 7) // 8
    bits = bytearray(bytes_renglon * alto)
    pix = chica.load()
    for y in range(alto):
        for x in range(ancho_logo):
            tinta = _tinta(*pix[x, y])
            negro = tinta >= 0.62 or (tinta >= 0.28 and x % 2 == 0 and y % 2 == 0)
            if negro:
                columna = inicio + x
                bits[y * bytes_renglon + columna // 8] |= 0x80 >> (columna % 8)
    return bytes_renglon, alto, bytes(bits)


def raster_para_ticket(datos: bytes, columnas: int, alineacion: str = "derecha") -> tuple[int, int, bytes]:
    """(bytes por renglón, alto en puntos, bits) del logo para ESC/POS.
    48 columnas = papel de 80 mm (576 puntos); 32 = 58 mm (384 puntos)."""
    ancho_papel = 576 if columnas >= 42 else 384
    ancho_logo = 240 if ancho_papel == 576 else 180
    return _raster(sha256(datos).hexdigest(), datos, ancho_papel, ancho_logo, alineacion)


def vista_previa_png(datos: bytes, columnas: int = 48) -> bytes:
    """El logo tal como sale en el ticket (los mismos puntos), en PNG."""
    bytes_renglon, alto, bits = raster_para_ticket(datos, columnas, alineacion="izquierda")
    ancho_logo = 240 if columnas >= 42 else 180
    imagen = Image.frombytes("1", (bytes_renglon * 8, alto), bytes(b ^ 0xFF for b in bits)).crop((0, 0, ancho_logo, alto))
    salida = BytesIO()
    imagen.save(salida, "PNG")
    return salida.getvalue()
