"""Pantallas del POS: HTML + Alpine.js servidos por el mismo FastAPI, sin
compilar nada. Las páginas son archivos estáticos; los datos los piden al
API con la cookie de sesión (si no hay sesión, el JS manda a /login).

Todo empieza en /inicio (el "núcleo"): desde ahí se entra a cada función."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parent.parent / "web"
PAGINAS = {"login", "inicio", "venta", "turno", "devoluciones", "notificaciones", "inventario", "catalogo", "mercancia", "faltantes", "pedidos", "tableta", "usuarios", "cajas-impresoras", "reporte-ventas", "negocio-datos", "facturas", "factura-imprimir"}

router = APIRouter(include_in_schema=False)
mimetypes.add_type("application/manifest+json", ".webmanifest")  # Windows no lo conoce
estaticos = StaticFiles(directory=WEB / "static")


@router.get("/")
def inicio():
    return RedirectResponse("/inicio")


@router.get("/favicon.ico")
def favicon():
    """Ícono de Cuadra (también lo descarga el script del acceso directo)."""
    return FileResponse(WEB / "static" / "app" / "cuadra.ico", media_type="image/x-icon")


@router.get("/certificado")
def certificado():
    """La autoridad del certificado de la red local, para instalarla en la
    tableta y que Chrome confíe en el servidor HTTPS (ver certificado_local)."""
    ca = Path("certificados") / "ca.crt"
    if not ca.exists():
        return RedirectResponse("/inicio")
    return FileResponse(ca, media_type="application/x-x509-ca-cert", filename="cuadra-red-local.crt")


@router.get("/{pagina}")
def pagina(pagina: str):
    if pagina not in PAGINAS:
        return RedirectResponse("/inicio")
    # Sin caché: al actualizar el sistema, las computadoras ven la versión nueva.
    return FileResponse(WEB / "paginas" / f"{pagina}.html", headers={"Cache-Control": "no-cache"})
