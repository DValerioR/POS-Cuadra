from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.categorias import router as categorias_router
from app.api.health import router as health_router
from app.api.inventario import router as inventario_router
from app.api.negocios import router as negocios_router
from app.api.productos import router as productos_router
from app.api.turnos import router as turnos_router
from app.api.ventas import router as ventas_router
from app.api.ventas_en_espera import router as ventas_en_espera_router
from app.api.solicitudes import router as solicitudes_router
from app.api.avisos_inventario import router as avisos_inventario_router
from app.api.ia import router as ia_router
from app.api.entradas import router as entradas_router
from app.api.asistente import router as asistente_router
from app.api.faltantes import router as faltantes_router
from app.api.antibioticos import router as antibioticos_router
from app.api.pedidos import router as pedidos_router
from app.api.usuarios import router as usuarios_router
from app.api.reporte_ventas import router as reporte_ventas_router
from app.api.facturas import router as facturas_router
from app.api.ofertas import router as ofertas_router
from app.api.ofertas_venta import router as ofertas_venta_router
from app.api.terminal import router as terminal_router
from app.api.respaldos import router as respaldos_router
from app.api.encargos import router as encargos_router
from app.api.whatsapp import router as whatsapp_router
from app.api.sistema import router as sistema_router
from app.api.usos import router as usos_router
from app.api.web import estaticos, router as web_router
from app.services import respaldos

@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    # Respaldos automáticos mientras el servidor está prendido (nunca sobre la base de pruebas).
    parar = respaldos.iniciar_automaticos()
    yield
    if parar is not None:
        parar.set()


app = FastAPI(title="POS Farmacia", lifespan=ciclo_de_vida)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(negocios_router)
app.include_router(categorias_router)
app.include_router(productos_router)
app.include_router(inventario_router)
app.include_router(turnos_router)
app.include_router(ventas_router)
app.include_router(ventas_en_espera_router)
app.include_router(solicitudes_router)
app.include_router(avisos_inventario_router)
app.include_router(ia_router)
app.include_router(entradas_router)
app.include_router(asistente_router)
app.include_router(faltantes_router)
app.include_router(antibioticos_router)
app.include_router(pedidos_router)
app.include_router(usuarios_router)
app.include_router(reporte_ventas_router)
app.include_router(facturas_router)
app.include_router(ofertas_router)
app.include_router(ofertas_venta_router)
app.include_router(terminal_router)
app.include_router(respaldos_router)
app.include_router(encargos_router)
app.include_router(whatsapp_router)
app.include_router(sistema_router)
app.include_router(usos_router)

# Pantallas: al final, para que las rutas del API tengan prioridad.
app.mount("/static", estaticos, name="static")
app.include_router(web_router)
