"""Pantallas del POS: HTML + Alpine.js servidos por el mismo FastAPI, sin
compilar nada. Las páginas son archivos estáticos; los datos los piden al
API con la cookie de sesión (si no hay sesión, el JS manda a /login)."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parent.parent / "web"
PAGINAS = {"login", "venta", "turno", "devoluciones"}

router = APIRouter(include_in_schema=False)
estaticos = StaticFiles(directory=WEB / "static")


@router.get("/")
def inicio():
    return RedirectResponse("/venta")


@router.get("/{pagina}")
def pagina(pagina: str):
    if pagina not in PAGINAS:
        return RedirectResponse("/venta")
    # Sin caché: al actualizar el sistema, las computadoras ven la versión nueva.
    return FileResponse(WEB / "paginas" / f"{pagina}.html", headers={"Cache-Control": "no-cache"})
