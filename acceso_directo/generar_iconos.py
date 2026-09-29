"""Genera los íconos de la app (app/web/static/app/) a partir de
docs/referencia/icono.png. Solo hace falta volver a correrlo si cambia la
imagen:

    pip install pillow      (no lo necesita el POS, solo este script)
    python acceso_directo/generar_iconos.py

- Quita el blanco de fuera del cuadro redondeado (esquinas transparentes).
- Tamaños grandes (48+): la imagen completa, con "Cuadra".
- Tamaños chicos (16-32): solo la "C" con el ticket, que se lee mejor.
"""
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "app/web/static/app"
DESTINO.mkdir(parents=True, exist_ok=True)

img = Image.open(RAIZ / "docs/referencia/icono.png").convert("RGB")
W, H = img.size
px = img.load()

# Color del fondo oscuro (centro-arriba del cuadro, lejos de las letras).
fondo = px[W // 2, 60]


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


L_FONDO = lum(fondo)

# 1) Inundar desde las esquinas lo que sea claro (el blanco de afuera).
fuera = bytearray(W * H)
cola = deque([(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)])
while cola:
    x, y = cola.popleft()
    i = y * W + x
    if fuera[i] or lum(px[x, y]) < 200:
        continue
    fuera[i] = 1
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if 0 <= nx < W and 0 <= ny < H and not fuera[ny * W + nx]:
            cola.append((nx, ny))

# 2) Alfa: afuera = 0; el borde (vecinos de afuera, grises por el suavizado)
#    se vuelve fondo semitransparente según qué tan claro es.
salida = Image.new("RGBA", (W, H))
out = salida.load()
for y in range(H):
    for x in range(W):
        i = y * W + x
        c = px[x, y]
        if fuera[i]:
            out[x, y] = (*fondo, 0)
            continue
        borde = any(
            0 <= x + dx < W and 0 <= y + dy < H and fuera[(y + dy) * W + (x + dx)]
            for dx in (-3, 0, 3) for dy in (-3, 0, 3)
        )
        if borde:
            a = max(0.0, min(1.0, (255 - lum(c)) / (255 - L_FONDO)))
            out[x, y] = (*fondo, round(a * 255))
        else:
            out[x, y] = (*c, 255)

# Recortar al cuadro (por si la imagen trae margen) y dejarlo cuadrado.
caja = salida.getbbox()
completo = salida.crop(caja)
lado = max(completo.size)
cuadro = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
cuadro.paste(completo, ((lado - completo.width) // 2, (lado - completo.height) // 2))

# Versión chica: la "C" con el ticket sobre el mismo cuadro oscuro.
cx0, cy0, cx1, cy1 = 360, 220, 850, 760  # zona de la "C" en la imagen original
glifo = salida.crop((cx0, cy0, cx1, cy1))
lado_c = 1024
chico = Image.new("RGBA", (lado_c, lado_c), (0, 0, 0, 0))
ImageDraw.Draw(chico).rounded_rectangle((0, 0, lado_c - 1, lado_c - 1), radius=230, fill=(*fondo, 255))
escala = (lado_c * 0.70) / max(glifo.size)
glifo = glifo.resize((round(glifo.width * escala), round(glifo.height * escala)), Image.LANCZOS)
chico.alpha_composite(glifo, ((lado_c - glifo.width) // 2, (lado_c - glifo.height) // 2))


def version(tam):
    return (chico if tam <= 32 else cuadro).resize((tam, tam), Image.LANCZOS)


for tam in (16, 32, 48, 180, 192, 512):
    version(tam).save(DESTINO / f"icono-{tam}.png", optimize=True)
# Ícono "maskable" (Android/Chrome recortan en círculo): el cuadro con margen seguro.
mask = Image.new("RGBA", (512, 512), (*fondo, 255))
dentro = cuadro.resize((410, 410), Image.LANCZOS)
mask.alpha_composite(dentro, (51, 51))
mask.save(DESTINO / "icono-maskable-512.png", optimize=True)
# .ico para el acceso directo de Windows y favicon.ico, con varios tamaños.
tams = [16, 24, 32, 48, 64, 128, 256]
base = version(256)
base.save(DESTINO / "cuadra.ico", sizes=[(t, t) for t in tams],
          append_images=[version(t) for t in tams if t != 256])
print("fondo", fondo, "listo:", sorted(p.name for p in DESTINO.iterdir()))
