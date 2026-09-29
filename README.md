# POS Farmacia

Punto de venta para negocios, empezando por una farmacia familiar. Ver `CONTEXTO.md`
para el contexto completo de negocio y las decisiones de producto.

## Decisiones técnicas (etapa 1)

- **Backend**: FastAPI + SQLAlchemy 2.0 + Alembic (migraciones) + PostgreSQL
  nativo de Windows (servicio `postgresql-x64-17`, arranque automático).
  Se probó correrlo dentro de WSL2 primero, pero la red virtual de WSL
  mostró cortes intermitentes de conexión incluso en pruebas simples — no es
  confiable para un POS, así que se descartó a favor de la instalación nativa.
- **App de escritorio**: no se empaqueta nada aparte. El servidor corre en una
  computadora dedicada (`uvicorn app.main:app`) y en cada computadora se crea
  un acceso directo con `chrome.exe --app=http://IP-SERVIDOR:PUERTO` (modo app
  de Chrome/Edge), que abre la web sin barra de navegador y con su propio ícono.
- **Multi-negocio**: todas las tablas principales tienen `negocio_id` desde el
  día uno, aunque hoy solo exista un negocio (la farmacia).

## Estructura

```
app/
  core/       configuración y conexión a base de datos
  models/     modelos SQLAlchemy (tablas)
  api/        endpoints FastAPI
alembic/      migraciones de base de datos
```

## Cómo correrlo

1. Crear entorno virtual e instalar dependencias:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Copiar `.env.example` a `.env` y poner los datos reales de tu PostgreSQL local.
3. Crear las tablas en la base de datos:
   ```
   alembic revision --autogenerate -m "modelo inicial"
   alembic upgrade head
   ```
4. Levantar el servidor:
   ```
   uvicorn app.main:app --reload
   ```
5. Probar que responde: abrir `http://localhost:8000/health`, debe regresar `{"status": "ok"}`.

## Modelo de datos (etapa 1)

- `negocios` — un renglón por negocio cliente (separación multi-negocio), con
  su configuración (ej. `redondeo_precio_venta`: 1.00 = pesos enteros, vacío = sin redondeo).
- `usuarios` — login propio por persona, con rol (`admin`, `bodega`, `mostrador`).
- `categorias` — con margen % configurable (patente, similares, leches, ...) y
  `controla_lote` para decidir si sus productos piden lote/caducidad.
- `productos` — catálogo. `clave` (código de barras o clave interna, única por
  negocio), precio máximo al público, `factor_conversion` (unidades de venta
  por unidad de compra, para productos a granel), IVA/IEPS, mínimo/máximo, y
  `requiere_revision` + `motivo_revision` para lo que necesita ojo humano.
  `precio_venta` puede quedar vacío (el catálogo de PVWin no lo trae).
- `lotes` — existencia por lote y caducidad de cada producto (`caducidad = NULL`
  significa que aún no se ha capturado, para la migración gradual del inventario
  heredado de PVWin). Venta futura descontará por FEFO usando estas filas.
- `ajustes_inventario` — bitácora de cambios de existencia que no son venta ni
  entrada (importación, ajuste, merma, captura de caducidad), con cantidad
  con signo, motivo y usuario. Nunca se edita ni se borra.

## Endpoints disponibles

- `GET/PUT /negocios/{id}` — configuración del negocio.
- `GET/POST /categorias`, `GET/PUT/DELETE /categorias/{id}`
- `GET/POST /productos` (con búsqueda `?q=` por nombre parcial o clave; la
  clave se compara sin ceros a la izquierda), `GET/PUT/DELETE /productos/{id}`
  — "eliminar" un producto lo desactiva (`activo=false`), no lo borra. Al
  guardar, el precio de venta se redondea según la configuración del negocio.
- Todos requieren `negocio_id` (todavía sin auth, así que se manda explícito).

## Scripts

Los archivos reales de la farmacia van en `datos/` (está en `.gitignore`).

- Crear un usuario (pide la contraseña sin mostrarla):
  ```
  python -m app.scripts.crear_usuario --negocio 1 --usuario diego --nombre "Diego Valerio" --rol admin
  ```
- Importar catálogo y existencias de PVWin (reglas en `CONTEXTO.md`,
  "Importación desde PVWin"):
  ```
  python -m app.scripts.importar_pvwin --negocio 1 --usuario diego --catalogo "datos/Catalogo de articulos.xlsx" --inventario "datos/Reporte de inventario.xlsx" --simular
  ```
  `--simular` no guarda nada, solo genera el reporte. Quitarlo para guardar.
  `--reemplazar` borra productos, lotes y ajustes del negocio e importa de
  nuevo (solo antes de tener ventas reales; las categorías se conservan).
  Cada corrida deja un reporte Excel en `datos/` con lo que hizo, los
  productos a revisar y la lista de negativos para conteo físico.

## Pendiente para completar la etapa 1

- Reimportar cuando llegue el catálogo completo A-Z (el actual se cortó en la D).
- Autenticación (login) y aplicación de permisos por rol en los endpoints.
- CRUD de inventario (lotes/caducidades) — el catálogo (categorías/productos)
  ya está.
