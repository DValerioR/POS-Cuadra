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
from app.api.pedidos import router as pedidos_router
from app.api.usuarios import router as usuarios_router
from app.api.reporte_ventas import router as reporte_ventas_router
from app.api.facturas import router as facturas_router
from app.api.ofertas import router as ofertas_router
from app.api.ofertas_venta import router as ofertas_venta_router
from app.api.web import estaticos, router as web_router

app = FastAPI(title="POS Farmacia")

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
app.include_router(pedidos_router)
app.include_router(usuarios_router)
app.include_router(reporte_ventas_router)
app.include_router(facturas_router)
app.include_router(ofertas_router)
app.include_router(ofertas_venta_router)

# Pantallas: al final, para que las rutas del API tengan prioridad.
app.mount("/static", estaticos, name="static")
app.include_router(web_router)
