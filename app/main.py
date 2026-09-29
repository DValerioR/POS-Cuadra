from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.categorias import router as categorias_router
from app.api.health import router as health_router
from app.api.inventario import router as inventario_router
from app.api.negocios import router as negocios_router
from app.api.productos import router as productos_router
from app.api.turnos import router as turnos_router

app = FastAPI(title="POS Farmacia")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(negocios_router)
app.include_router(categorias_router)
app.include_router(productos_router)
app.include_router(inventario_router)
app.include_router(turnos_router)
