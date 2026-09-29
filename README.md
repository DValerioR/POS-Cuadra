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

## Sesión y permisos

Todo (salvo `/health` y `/auth/login`) requiere sesión. El negocio y el
usuario salen de la sesión: no se mandan en las peticiones, y un usuario
nunca ve datos de otro negocio (responden 404).

- `POST /auth/login` con `{negocio_id, usuario, password}` — deja una cookie
  `httpOnly` que dura 12 horas (`HORAS_SESION` en `.env`). También regresa el
  token para usarlo como `Authorization: Bearer <token>` desde `/docs` o scripts.
- `POST /auth/logout` — cierra la sesión (el token deja de servir al instante).
- `GET /auth/yo` — usuario de la sesión.
- Las sesiones viven en la tabla `sesiones` (solo el hash del token), así que
  desactivar a un usuario corta sus sesiones abiertas.

Permisos por rol: consultar es para todos; crear/editar productos, categorías
y configuración del negocio es solo `admin`; ajustes y mermas son `admin` y
`bodega`; capturar caducidades es para todos. La lógica está en `app/core/auth.py`
(`usuario_actual`, `requiere_rol`, `solo_admin`).

## Endpoints disponibles

- `GET/PUT /negocio` — configuración del negocio de la sesión.
- `GET/POST /categorias`, `GET/PUT/DELETE /categorias/{id}`
- `GET/POST /productos` (con búsqueda `?q=` por nombre parcial o clave; la
  clave se compara sin ceros a la izquierda; `?solo_revision=true` para los
  marcados por el importador; paginado con `limite`/`desplazamiento`, 50 por
  defecto), `GET/PUT/DELETE /productos/{id}`
  — "eliminar" un producto lo desactiva (`activo=false`), no lo borra. Al
  guardar, el precio de venta se redondea según la configuración del negocio.
- Inventario por lote:
  - `GET /inventario/productos/{id}` — existencia total y lotes en orden FEFO
    (primero el que caduca antes; los "sin caducidad" al final).
  - `POST /inventario/captura-caducidad` — pasa piezas del lote sin caducidad
    a un lote real (si ya existe uno con esa caducidad y número, se suman).
    Cualquier rol, porque mostrador captura al vender.
  - `POST /inventario/ajustes` — ajuste (+/-) o merma (-) con motivo; solo
    admin y bodega. Sin `lote_id` usa el lote sin caducidad (sirve para el
    conteo físico de productos importados en cero).
  - `GET /inventario/ajustes` — bitácora, filtrable por producto, tipo y fecha.
  - `GET /inventario/avance-caducidades` — % de piezas con caducidad capturada
    y productos pendientes (los de más piezas primero). Solo cuenta productos
    cuya categoría controla lote.
  - La lógica vive en `app/services/inventario.py` (las ventas usarán `lotes_fefo`).

### Cajas y turnos (etapa 2)

- `GET /cajas`, `POST /cajas`, `PUT /cajas/{id}` — puntos de cobro (una por
  computadora de mostrador). Crear y editar: solo admin.
- `POST /turnos` con `{caja_id, tipo: "manana"|"tarde", fondo_inicial}` — abre
  turno (admin y mostrador). Solo un turno abierto por caja (lo garantiza un
  índice único parcial en la base de datos, aunque dos computadoras lo
  intenten a la vez).
- `GET /turnos/abierto?caja_id=` — turno abierto de la caja, o `null`.
- `GET /turnos/{id}/corte` — lo que se espera en efectivo y tarjeta ahora.
- `POST /turnos/{id}/cerrar` con lo contado — congela lo esperado y guarda la
  diferencia (negativa = faltante) y quién cerró.
- `GET /turnos` — historial de cortes, solo admin.
- Hoy lo esperado es solo el fondo; al agregar ventas se suman en
  `totales_del_turno` (`app/services/turnos.py`).

## Pruebas automáticas

```
pytest
```

Corre todas las pruebas (~90, unos 12 segundos). Antes de cada commit
deben pasar todas.

- Usan una base de datos aparte: la de `.env` con `_test` al final (`pos_test`).
  Se crea sola; tu usuario de PostgreSQL necesita permiso para crear bases.
  Hay un candado que impide correrlas contra una base que no termine en `_test`.
- Al empezar, `pos_test` se reconstruye con las migraciones de Alembic, y
  una prueba verifica que los modelos coincidan con las migraciones (si
  cambias un modelo y olvidas `alembic revision --autogenerate`, falla).
- Cada prueba corre en una transacción que se deshace al final: no se
  estorban entre sí y nunca tocan los datos reales.
- El importador se prueba con Excel pequeños generados al vuelo con el
  formato de PVWin (los archivos reales de `datos/` no están en git).
- Útiles: `pytest tests/test_inventario.py` (un archivo), `pytest -k merma`
  (por nombre), `pytest -x` (detenerse en el primer fallo).

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

## Pendiente

- Reimportar cuando llegue el catálogo completo A-Z (el actual se cortó en la D).
