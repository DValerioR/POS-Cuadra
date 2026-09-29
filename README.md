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
- `GET/PUT/DELETE /negocio/logo` — imagen de la pantalla de inicio (verla: todos; cambiarla: admin).
- `GET/POST /categorias`, `GET/PUT/DELETE /categorias/{id}`
- `GET/POST /productos` (con búsqueda `?q=` por nombre parcial o clave; la
  clave se compara sin ceros a la izquierda; `?clave=` solo por clave exacta,
  para el lector de código de barras; `?solo_revision=true` para los
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

### Ventas (etapa 2)

- `POST /ventas` con `{caja_id, renglones: [{producto_id, cantidad, lote_id?,
  caducidad?, numero_lote?}], tarjeta, efectivo_recibido}` — admin y mostrador.
  - Requiere turno abierto en la caja. Todo o nada: si algo falla no se guarda.
  - Lotes: con `lote_id` sale de ese lote; sin él, FEFO. Con `caducidad`
    (caja en mano sin caducidad registrada) se captura y se vende de ahí.
  - Cobro: lo que no cubre `tarjeta` se paga en efectivo y se calcula el
    cambio (pago mixto automático). Transferencia preparada pero desactivada.
  - Precios con impuestos incluidos; se guarda el desglose (IEPS sobre el
    subtotal, IVA sobre subtotal + IEPS). Precio e impuestos se copian a la
    venta, así que cambiar el precio después no altera ventas pasadas.
  - Folio consecutivo por negocio. Las ventas se serializan con un bloqueo
    del negocio para que dos cajas nunca vendan la misma pieza.
  - Responde `avisos` (ej. producto que requiere receta) y de qué lote salió
    cada pieza (`renglones[].lotes`).
- `GET /ventas/{id}` — detalle (para reimprimir). `GET /ventas` — historial, solo admin (`?folio=` busca por el número del ticket).
- `POST /ventas/{id}/cancelar` con `{caja_id, motivo}` — cancela toda la venta.
- `POST /ventas/{id}/devoluciones` con `{caja_id, motivo, piezas: [{renglon_id,
  cantidad, lote_id?}]}` — devuelve algunas piezas.
  - Solo admin, motivo obligatorio. Las piezas regresan siempre al lote del
    que salieron (con `lote_id` se indica cuál, si la venta salió de varios).
  - El dinero se regresa por el método con que se pagó (mixto: primero
    tarjeta) y sale del turno abierto de `caja_id`: si la venta es de un turno
    ya cerrado, ese corte no cambia.
  - Nunca se devuelve más de lo vendido ni más dinero del cobrado.
- `POST /ventas/{id}/cambio` con `{caja_id, motivo, devueltas: [...], nuevos:
  [...], tarjeta, efectivo_recibido}` — cambio de producto (solo admin). Lo
  devuelto regresa a su lote y su valor es saldo a favor (pago
  `saldo_a_favor`) en una venta nueva; si lo nuevo cuesta más el cliente
  paga la diferencia, si cuesta menos se le regresa en efectivo. Todo o nada.
- Corte de turno: fondo + cobrado en el turno − reembolsado en el turno.

### Tickets e impresión (etapa 2)

- Al cobrar se imprime el ticket y, si hubo efectivo, se abre el cajón. Si
  la impresora falla, la venta **se guarda igual** y la respuesta trae
  `impresion.error`.
- `GET /ventas/{id}/ticket` — el ticket en texto (para verlo sin impresora).
- `POST /ventas/{id}/imprimir` — reimpresión (marcada como tal, sin cajón).
- `POST /cajas/{id}/prueba-impresion` — ticket de prueba (admin).
- Cada caja configura su impresora (`PUT /cajas/{id}`): `impresora_modo`
  `red` (Ethernet, `IP:9100`) o `agente` (USB, `http://IP-PC:9110` + token);
  `impresora_columnas` (48 = papel de 80 mm). El token nunca se regresa.
- Encabezado y pie del ticket: `ticket_encabezado` / `ticket_pie` en `PUT /negocio`.
- ESC/POS propio en `app/impresion/escpos.py` (sin python-escpos: solo se
  necesita texto, corte y cajón). Acentos con la tabla PC850.
- Agente para impresoras USB: `agente_impresion/` (ver su `LEEME.md`).

## Pantallas

HTML + Alpine.js servidos por el mismo FastAPI (`app/web/`), sin Node.js ni
compilación; Alpine.js está guardado en `app/web/static/vendor/` para que
funcione sin internet.

- `/login` — inicio de sesión (usa el negocio predeterminado, `NEGOCIO_PREDETERMINADO` en `.env`).
  Después de entrar lleva a `/inicio`, o directo a `/venta` si esa
  computadora tiene activado "Entrar directo a Vender" (Configuración).
- `/inicio` — pantalla de inicio o "núcleo", como la de PVWin: menús por tema
  (Alt o F10 y flechas), accesos rápidos F1–F4, la imagen del negocio al
  centro y barra de estado (usuario, caja, turno, fecha y hora, conexión).
  Cada rol ve solo lo suyo; lo que aún no existe sale como "Próximamente".
  La lista de funciones vive en un solo lugar: `SECCIONES` en `api.js`.
  La imagen del centro la sube el administrador (Configuración → Imagen de
  inicio) y se guarda en la base (`GET/PUT/DELETE /negocio/logo`, PNG, JPG,
  GIF o WEBP de hasta 5 MB); sin imagen se muestra el nombre del negocio.
- `/venta` — venta en mostrador. La primera vez pregunta qué caja es la
  computadora (se recuerda en el navegador) y pide abrir turno si no hay.
  Buscar o escanear (F2), flechas + Enter para agregar, lote sugerido por
  FEFO con opción de elegir el lote entregado, caducidad opcional para
  piezas sin caducidad, aviso de receta, cobro en efectivo/tarjeta/mixto con
  cambio en vivo (F12), y reintento de impresión si el ticket falla.
- `/turno` — corte de caja: lo esperado, captura de lo contado con la
  diferencia en vivo, y cierre.
- `/devoluciones` — devoluciones, cancelaciones y cambios de producto (solo admin).

Todas las pantallas llevan la barra superior con "Inicio" y se probaron a
1920×1080, 1366×768, 1200×700, 683 de ancho y 600 de alto: sin
desplazamiento a los lados y con la acción principal (Cobrar, Cerrar turno)
siempre a la vista.

En cada computadora de mostrador: acceso directo a
`chrome.exe --app=http://IP-DEL-SERVIDOR:8000/`.

Para ver las pantallas sin tocar datos reales: `python -m app.scripts.servidor_demo`
(http://127.0.0.1:8001, usuario `demo` / `demo1234`, sobre la base de pruebas).

## Pruebas automáticas

```
pytest
```

Corre todas las pruebas (~190, unos 10 segundos). Antes de cada commit
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
- Los usuarios de prueba usan bcrypt de costo 4 para que el login sea
  rápido; una prueba aparte verifica que la app use costo 12.
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
