# Contexto del proyecto: Punto de venta con asistente de IA

Este documento resume todas las decisiones tomadas antes de empezar a programar. Léelo completo antes de proponer estructura, modelo de datos o código.

## Qué es

Un punto de venta (POS) para negocios, desarrollado en Python, que empieza funcionando en una farmacia familiar real (Farmacia La Fe) y que después se venderá a otros negocios. La primera versión es solo para farmacia, pero el diseño debe permitir crecer a otros giros (restaurantes, abarrotes) mediante un núcleo común y módulos por giro. Los módulos de otros giros NO se construyen todavía.

Desde el inicio, todos los datos deben estar separados por negocio (por ejemplo, un `negocio_id` en las tablas principales), y el nombre, logo, márgenes y categorías deben ser configurables, no fijos en el código.

## Quién lo desarrolla

El desarrollador está estudiando programación, sabe SQL básico y un poco de MongoDB. Explica las decisiones técnicas con claridad, avanza por etapas pequeñas que funcionen de verdad y evita complejidad innecesaria. El proyecto se versiona con Git desde el primer día.

## Infraestructura

La farmacia tiene una sola sucursal con cuatro computadoras Windows: dos en bodega para inventario y dos en mostrador para ventas, además de una tableta Android. El sistema debe funcionar en red local, sin depender de internet y sin pagar servidores.

El sistema actual (PVWin) tiene el problema de que el servidor vive dentro del programa de la computadora principal, y si alguien lo cierra, las demás dejan de funcionar. Esto no debe repetirse: el servidor corre como servicio independiente que arranca solo con el equipo, idealmente en una computadora dedicada.

La arquitectura acordada es una aplicación web en red local que en las computadoras se ve como aplicación de escritorio (con su ícono, sin navegador visible), y que en la tableta se abre desde el navegador. La tableta tendrá una vista sencilla para consultar existencias y precios y para capturar lotes y caducidades.

Stack decidido e implementado (ver README.md): FastAPI, SQLAlchemy 2.0, Alembic para migraciones y PostgreSQL 17 instalado de forma nativa en Windows (servicio `postgresql-x64-17` con arranque automático). Se probó PostgreSQL dentro de WSL2 y se descartó por cortes intermitentes de red. La "app de escritorio" es un acceso directo con `chrome.exe --app=http://IP-SERVIDOR:PUERTO` en cada computadora, sin empaquetado aparte. Las pantallas se hacen con HTML y JavaScript sencillo servidos por el mismo FastAPI, con Alpine.js para lo interactivo: sin Node.js ni paso de compilación, y con las librerías guardadas dentro del proyecto para que funcione sin internet. Se descartó React por la complejidad extra. MongoDB queda descartado.

Criterio de diseño de las pantallas: atractivas pero muy sencillas, que cualquier persona las entienda sin explicación. Letra y botones grandes, una acción principal clara por pantalla, opciones como botones grandes en lugar de listas desplegables, textos en español llano y la misma barra superior, colores e íconos en todas (estilos en `app/web/static/css/pos.css`, íconos en `app/web/static/iconos.svg`, barra común en `api.js`). Las pantallas nuevas siguen este mismo estilo.

Venta con teclado, para no usar el ratón: el campo visible es solo para código de barras y todo lo que se teclea o escanea cae ahí aunque no tenga el cursor; la búsqueda por nombre está oculta y se abre con F2 (flechas + Enter agregan, Esc cierra); con productos en el carrito, Esc pasa al modo cobro (el cursor va a "¿Con cuánto paga?", Enter cobra y otro Esc regresa a escanear); después de cobrar, Enter empieza la siguiente venta.

## Arranque del programa y pantalla de inicio ("núcleo")

Ya está hecho (29/09/2026). Al abrir la dirección del servidor (`/`), al iniciar sesión o en páginas desconocidas, el sistema lleva a la pantalla de inicio o "núcleo" (`/inicio`), salvo que esa computadora tenga activado "Entrar directo a Vender". Las pantallas existentes son `/login`, `/inicio`, `/venta`, `/turno` y `/devoluciones`. Lo de abajo es el diseño que se siguió; un cambio respecto a él: la imagen del centro no es solo el logo, sino cualquier imagen que el administrador sube desde el núcleo (Configuración → Imagen de inicio), guardada en la base por negocio. Falta subir la imagen real de Farmacia La Fe.

Lo que se quería: que el programa NO empiece en la caja, sino en una pantalla de inicio o "núcleo" desde donde se entra a todas las funciones del sistema. El flujo es: acceso directo de Chrome en modo aplicación → inicio de sesión → núcleo → la función elegida, y desde cualquier pantalla se regresa al núcleo.

Ícono del acceso directo (29/09/2026): el logo de Cuadra, `docs/referencia/icono.png`. Ya está en todas las pantallas (pestaña, manifiesto) y hay un script que crea el acceso directo con ese ícono (ver README.md, "Pantallas"); falta correrlo en las computadoras de la farmacia.

Referencia visual: en `docs/referencia/` hay dos fotos de la pantalla principal de PVWin, el sistema que usa hoy la farmacia (una a pantalla completa y otra en ventana sin maximizar, que es como se usa normalmente). Revísalas antes de diseñar. El núcleo nuevo sigue la misma estructura, que el personal ya conoce, pero con el estilo visual actual del proyecto (`pos.css`, `iconos.svg`, barra común de `api.js`).

Diseño decidido del núcleo, de arriba a abajo:
- Barra de menús con las funciones agrupadas por tema, como los menús de PVWin, con letra grande y textos en español llano. Es la excepción acordada a la regla de "botones en lugar de listas desplegables", porque el personal ya está acostumbrado a esos menús. Agrupación propuesta (se puede mejorar): "Ventas" (Vender, Turno y corte, Devoluciones y cambios), "Inventario" (Inventario y caducidades, Entradas de mercancía, Productos y precios), "Reportes", "Configuración" (usuarios, cajas e impresoras, datos del negocio) y "Ayuda".
- Barra de accesos rápidos debajo, como la fila de íconos de PVWin, pero con botones más grandes con ícono y nombre visible, solo para las funciones de uso diario: Vender, Turno y corte, Inventario y Entradas de mercancía.
- Centro: el logo del negocio grande, centrado y ocupando el espacio disponible sin deformarse, igual que en PVWin. El logo es configurable por negocio (guardado con los datos del negocio, no fijo en el código). Todavía no está el archivo original del logo de Farmacia La Fe: dejar preparado dónde se carga y, mientras no haya logo, mostrar el nombre del negocio con buen tamaño.
- Barra de estado abajo, como la de PVWin: nombre del negocio, usuario y rol, caja de esta computadora, si hay turno abierto, fecha y hora, e indicador de conexión con el servidor.

Reglas del núcleo:
- Cada rol ve solo lo que puede usar (ver "Usuarios y permisos"); lo que no le toca no aparece.
- Las funciones que todavía no existen (Productos y precios, Entradas de mercancía, Inventario, Reportes, Configuración) aparecen como "Próximamente" y no abren nada.
- La lista de secciones (nombre, ícono, grupo, ruta, roles, si existe, si va en accesos rápidos) vive en un solo lugar en `api.js`, y de ahí salen los menús, los accesos rápidos y la barra superior de las demás pantallas.
- Todo se usa sin ratón: Alt abre los menús con flechas y Enter, y cada acceso rápido tiene una tecla (por ejemplo F1 a F4) visible en el botón.
- "Inicio" siempre visible en la barra superior de las demás pantallas, y el logo o nombre del negocio también lleva al núcleo.
- `/`, las páginas desconocidas y el inicio de sesión llevan al núcleo en lugar de a `/venta`; hay que ajustar `app/api/web.py`, `login.html` y las pruebas de `tests/test_web.py` que hoy esperan `/venta`.
- Ajuste por computadora (guardado en esa computadora, como la caja) para entrar directo a Vender al iniciar sesión, pensado para mostrador. Por defecto se entra al núcleo.

## Pantallas responsivas

En la farmacia normalmente usan el programa en una ventana sin maximizar, casi del tamaño de la pantalla (ver la segunda foto en `docs/referencia/`), así que ese caso tiene prioridad, aunque todas las pantallas (el núcleo y las existentes) deben verse y usarse bien a distintos tamaños. Hasta ahora solo se probaron a 1366×768 en pantalla completa.

Ya está hecho (29/09/2026), en `app/web/static/css/pos.css`:
- Núcleo: cabe siempre en la ventana; los menús se acomodan en dos renglones si no caben, los accesos pasan a dos columnas a media pantalla y la imagen se ajusta al espacio que queda.
- Barra superior de las demás pantallas: solo íconos por debajo de 1200 px (salvo Inicio y la pantalla actual) y botón "Menú" por debajo de 760 px.
- Venta: el panel de cobro mide de 320 a 380 px según el ancho; por debajo de 1100 px se oculta la columna Precio (queda el importe); en ventanas bajas el cobro se compacta; a media pantalla pasa a una columna con el cobro abajo. Si el cobro no cabe, se desplaza por dentro y Cobrar se queda pegado abajo.
- Corte: el botón Cerrar turno se queda pegado abajo al desplazarse.
- Devoluciones: las columnas se ajustan a su contenido (ya no hay anchos fijos) y el renglón de Volver / Hacer la devolución se queda pegado abajo cuando está a la vista.

Cómo se verificó (y cómo volver a hacerlo tras cambios de diseño): con el servidor de demostración, probar cada pantalla a varios tamaños (al menos 1920×1080, 1366×768, ventana restaurada de unos 1200×700, media pantalla de unos 683 px de ancho, y una ventana baja de unos 600 px de alto) y revisar que no haya desplazamiento horizontal, que la acción principal de cada pantalla (Cobrar, Cerrar turno, Hacer la devolución) siempre esté a la vista y que el texto no se encime.

Importante para producción: `uvicorn --reload` es solo para desarrollo. En la farmacia, el servidor FastAPI debe quedar instalado como servicio de Windows que arranque solo con el equipo y se reinicie si falla, sin depender de que alguien tenga una ventana abierta, porque ese es justo el problema que tienen hoy con PVWin.

## Catálogo

El catálogo es grande, del orden de varios miles de productos: medicamentos de patente, genéricos y similares, además de perfumería y artículos como pañales, desodorantes, champús y leches de bebé. La búsqueda en mostrador debe ser instantánea mientras se escribe, así que requiere buen indexado (búsqueda parcial y sin importar acentos o mayúsculas).

El catálogo inicial se importa desde un Excel exportado de PVWin, que incluye productos, precios y existencias. El sistema también debe poder exportar inventario y reportes de ventas a Excel.

Productos fraccionados o a granel: hay productos que se compran por caja y se venden por pieza o sobre (por ejemplo "AGRANEL ADVIL 200 MG C/2", sueros en polvo). El modelo debe permitir un factor de conversión entre la unidad de compra y la unidad de venta, para que una entrada de una caja sume las piezas correctas. La falta de esto en PVWin es probablemente la causa de muchas existencias negativas.

El control por lote y caducidad debe ser configurable por categoría: obligatorio en medicamentos, opcional o desactivado en dulces, bebidas, perfumería y productos genéricos tipo "AGUJAS VARIAS" o "BUBBALOO VARIOS SABORES", donde capturar lote estorba más de lo que ayuda. Los productos sin control de lote manejan una sola existencia.

Se puede marcar un producto como "requiere receta" (por ejemplo antibióticos), lo cual solo muestra un aviso al vender. La farmacia no maneja medicamentos controlados.

## Importación desde PVWin

El importador lee los reportes tal como los exporta PVWin, sin limpieza manual previa, para poder repetir la importación el día del cambio. Se usan dos reportes que se unen por la columna Clave.

El reporte "Catálogo de artículos" (hoja `Hoja1`) tiene título en las filas 1 y 2, encabezados en la fila 4 y datos desde la fila 6; la primera columna va vacía. Sus columnas son Clave (código de barras o clave interna), Alterna (vacía), ProdServ (clave de producto SAT), Descripción, SAT (clave de unidad, siempre H87), UMV (siempre PZA), Factor (siempre 1), Localiza, Gpo, Dpto, USD, $Pcio Compra (sin impuestos), Mínimo, Máximo, Exto, %IEPS y %IVA. No trae precio de venta; está pendiente volver a exportarlo completo y con precio de venta si PVWin lo permite (la versión recibida se cortó en la letra D, con 3,440 productos).

El reporte "Reporte de inventarios - Detallado - Sin mostrar ceros" tiene la misma estructura de encabezado y columnas Clave, Descripción, Localización, Grupo, Depto, Existencia y UMV. Al terminar cada letra trae un renglón de subtotal con "Letra: X" en la primera columna, y al final un total general; esos renglones se ignoran. Contiene 6,629 productos con 39,175 piezas en total. Como omite existencias en cero, no sirve como catálogo: los productos que solo están en el catálogo se importan con existencia cero.

Reglas de mapeo y limpieza: IVA e IEPS se aplican solo a los productos que PVWin marca explícitamente en el catálogo de artículos (columnas %IVA y %IEPS); si no vienen marcados son 0%, porque muchos productos no los llevan (casi todos los medicamentos, higiene femenina, etc.). Antes se deducía el IVA por el grupo de PVWin (Grupo 2 = 16%), pero el grupo no es confiable (hay medicamentos en el 2) y se dejó de hacer el 29/09/2026. 274 productos vienen como "_GND" (sin grupo) y quedan para asignar categoría a mano. El campo Localización no es una ubicación: tiene nombres de laboratorio (MAVER, LIOMONT, BAYER) y algunas fechas sueltas viejas, así que se guarda como laboratorio solo cuando es texto y se descarta cuando es fecha. Mínimo y Máximo se importan para las sugerencias de pedido. Los productos con precio de compra en cero se marcan para revisión. El IVA de 20% del "A GRANEL BRONCORUB LATA" es un error de captura y se corrige a 16%.

Casos conocidos: la clave "1" la comparten "ARTICULO DE PRUEBA" (que no se importa) y "TONICO PV CANNABIS + ARNICA,ALCANFOR 150 ML" (necesita clave nueva); "CRA EUCERIN ANTI-PIGMENT CORPORAL 200 ML" (4006000014395) y "ZIVATA CAPSULAS 0.5 MG C/30" (7501300421814) aparecen duplicados y se fusionan sumando existencias; hay un producto sin clave en el catálogo ("CEP DENTAL CLINIC ALL ROUNDER 59"); "OFERTA ESTERILIZADOR EVENFLO PLUS" con 1,250 piezas es casi seguro un error.

Lista de precios (29/09/2026): el reporte "Reporte de lista de precios - Por descripción de artículo - Impuestos No Incluidos - Sin existencias" (hoja `Hoja1`, mismo encabezado; columnas Clave, Descripción, UMV, USD y $Precio Venta 1 a 4) trae los 10,401 productos de la A a la Z con su precio sin impuestos. Se importa con `app/scripts/importar_precios_pvwin.py`: el precio de venta es "Precio Venta 1" + IEPS + IVA (solo los marcados en el catálogo), con el redondeo del negocio (Farmacia La Fe: a pesos enteros hacia arriba, decidido por el dueño aunque cambie algunos precios respecto a PVWin). Los productos de la lista que no estaban en la base (unos 2,600, casi todos de la E a la Z y sin existencia) se crean con IVA 0% y marcados para revisar, porque la lista no trae costo, departamento ni impuestos. Los que traen precio en cero quedan sin precio. Solo 4 productos usan Precio Venta 2; se usa siempre el 1.

Hay 322 productos con existencia negativa, sobre todo a granel, dulces y aceites. Se importan en cero y se genera una lista exportable a Excel para conteo físico.

Cada existencia importada entra en un lote especial por producto sin lote ni caducidad (caducidad NULL), para poder vender desde el primer día. Cuando se captura la caducidad de una caja, esas piezas pasan de ese lote a uno real, y el avance de la migración es cuántas piezas quedan sin caducidad. Como las existencias de PVWin pueden arrastrar diferencias, el sistema permite ajustes de inventario con motivo y usuario.

El importador debe generar un reporte de lo que hizo: productos creados, fusionados, omitidos, negativos puestos en cero y productos pendientes de revisar.

## Usuarios y permisos

Cada persona tiene su propio usuario, nunca compartido, y toda venta, ajuste, descuento, devolución y cierre de turno queda registrado con el usuario que lo hizo.

Los administradores (la dueña, su hija y el desarrollador) tienen acceso a todo, incluidos precios, reportes, cancelaciones y devoluciones. Los usuarios de bodega dan entradas de mercancía, registran lotes, hacen ajustes de inventario y pedidos, pero no cobran ni ven reportes de dinero. Los usuarios de mostrador venden, cobran y hacen su corte de caja, pero no cambian precios, no cancelan ni borran ventas: las devoluciones y cancelaciones las piden y un administrador las autoriza.

## Lotes y caducidades (parte central del sistema)

Hoy la farmacia no lleva lotes ni caducidades en el sistema; revisa la caja al vender y retira productos dos meses antes de caducar. El sistema nuevo sí los maneja.

Cada producto tiene varios registros de existencia, uno por lote, cada uno con su caducidad y cantidad. Cuando entra mercancía de un producto con un lote nuevo, se crea un registro nuevo en lugar de sumarse al anterior. Al vender, el sistema descuenta primero el lote que caduca antes (FEFO), y si ese lote no alcanza, completa con el siguiente. Cada venta guarda de qué lote salió cada pieza, para poder rastrear un lote si hay un retiro sanitario.

En pantalla de venta el sistema indica qué lote entregar (por ejemplo "entregar lote A, caducidad marzo 2027"). Si el vendedor entrega una caja de otro lote, debe poder escanearla o elegirla para que el descuento se haga del lote real.

Migración del inventario existente: de aquí en adelante toda entrada nueva se registra con lote y caducidad. Lo que ya está en anaquel se captura conforme se vende: si el producto aún no tiene caducidad registrada, aparece un campo pequeño para capturar la de la caja en mano. Ese campo se puede saltar sin bloquear la venta. El sistema marca los productos "sin caducidad registrada", lleva la cuenta del avance y señala los de poca rotación para capturarlos manualmente.

Alertas de caducidad: avisar con suficiente anticipación para mover el producto o devolverlo al proveedor, considerando que los distribuidores suelen aceptar devoluciones con tres a seis meses de anticipación. Lo caducado o dañado sale del inventario como merma registrada (con motivo y usuario), nunca se borra.

## Ventas y cobro

Métodos de pago: efectivo con cálculo de cambio, tarjeta y pagos mixtos. Transferencia queda preparada pero desactivada. En la primera versión el pago con tarjeta se registra manualmente; la integración con una terminal Mercado Pago Point es una etapa posterior.

Hardware existente que se reutiliza: lector de código de barras, impresoras de tickets y cajón de dinero. Las impresoras son una Bixolon SRP-330II y una Epson TM-T20II, ambas térmicas de 80 mm compatibles con ESC/POS, así que se manejan con el mismo código: un generador ESC/POS propio y mínimo (texto, corte y cajón), en lugar de la librería python-escpos, para no cargar dependencias que no hacen falta. El cajón se abre solo al cobrar en efectivo, conectado a la impresora, con el comando ESC/POS de pulso de cajón.

Como la app corre en el navegador y el servidor está en otra computadora, el navegador no puede mandar comandos directos a una impresora USB. Si las impresoras están conectadas por Ethernet, el servidor les imprime directo por IP (puerto 9100). Si están por USB, se instala un pequeño agente de impresión en cada computadora de mostrador que recibe el ticket y lo manda a su impresora. Hoy las impresoras están conectadas por USB (así que se necesita el agente de impresión en las computadoras de mostrador), pero el código de impresión debe quedar detrás de una interfaz que permita ambos modos, configurable por caja, para poder pasar a Ethernet sin reprogramar.

Si el sistema no tiene existencia suficiente de un producto, la venta se bloquea con un mensaje que pide a bodega o admin hacer un ajuste de inventario; así no se repiten las existencias negativas de PVWin. Se decidió así mientras se corrigen los negativos heredados y se hace el conteo físico; más adelante se puede revisar permitir la venta dejando el producto marcado para conteo.

Ventas en espera (hecho el 29/09/2026): el cajero puede guardar la venta que tiene en pantalla (F4, con una nota opcional para reconocer al cliente) para atender a otro, y retomarla después. Máximo 5 guardadas por caja, guardadas en el servidor (no se pierden si se cierra el navegador) y sin apartar existencia. Mientras haya ventas guardadas, o una venta sin cobrar en la pantalla, no se puede salir de la pantalla de venta; y mientras haya ventas guardadas en una caja, no se puede hacer su corte (lo impide también el servidor).

No hay crédito a clientes ni ventas a cuenta. Los descuentos quedan preparados pero desactivados; cuando se activen, el vendedor tendrá un tope y por encima de él se requiere autorización de administrador, con registro de quién lo aplicó.

Devoluciones y cancelaciones: siempre con motivo registrado y las autoriza un administrador. Para no dejar esperando a la fila mientras el administrador va a la caja (cambio del 29/09/2026), el cajero las pide desde Devoluciones y sigue cobrando; la solicitud llega a un centro de notificaciones que solo ven los administradores (campana en la barra de todas las pantallas), y cualquiera de ellos la autoriza o rechaza desde su computadora. Al autorizarla, la devolución se hace sola en el turno de la caja que la pidió (de ahí sale el dinero) y al cajero le aparece en Vender cuánto entregar; si se rechaza, le aparece que no entregue dinero y el motivo. El administrador puede seguir haciéndolas directo en la caja. Mientras una caja tenga solicitudes pendientes no se puede hacer su corte. La mercancía devuelta regresa siempre al inventario, a su lote original (el vendedor verifica que se pueda revender).

Cambios de producto: cuando un cliente se equivocó de medicamento y quiere cambiarlo por otro, se hace en una sola operación (solo administrador, con motivo). Lo que regresa vuelve a su lote original y su valor queda como saldo a favor en la venta nueva; si lo nuevo cuesta más, el cliente paga la diferencia (efectivo, tarjeta o mixto), y si cuesta menos, la diferencia se le regresa siempre en efectivo. El saldo a favor no es dinero, así que no cuenta en el corte de caja; solo cuentan la diferencia cobrada o regresada. El ticket de la venta nueva indica que es un cambio y de qué folio viene.

## Turnos y corte de caja

Hay dos turnos, mañana y tarde. Al abrir turno se captura el fondo de caja. Al cerrarlo, el sistema muestra lo esperado en efectivo y en tarjeta, el cajero captura lo contado y queda registrada la diferencia con el nombre de quien cerró.

## Precios y márgenes

Los precios de venta al público incluyen IVA (e IEPS cuando aplica); el ticket desglosa el impuesto. Los precios se ajustan cada vez que cambia el costo del proveedor, hacia arriba o hacia abajo. Se usan márgenes por categoría, por ejemplo 20% para patente, 50% para similares y 5% para leches de bebé (configurables).

Cuando entra una factura con un costo distinto, el sistema recalcula el precio de venta sugerido y lo muestra para aprobación antes de aplicarlo. Debe permitir precio manual en productos donde el margen no aplique, y guardar historial de precios.

Los medicamentos de patente tienen precio máximo al público impreso en la caja. Si el margen da un precio mayor, se usa el máximo y el sistema avisa que ese producto se vende con menos margen del deseado.

Redondeo de precios de venta: como en el día a día casi no se usan centavos, cada negocio puede activar un redondeo del precio de venta (por ejemplo a pesos enteros o a medios pesos). Se redondea siempre hacia arriba para no perder margen, salvo que eso pase el precio máximo al público, en cuyo caso se redondea hacia abajo. Solo aplica al precio de venta; el costo de compra conserva sus decimales.

## Proveedores, pedidos y entradas

Compran a unos nueve o diez proveedores. El sistema maneja pedidos: sugiere qué pedir según existencias y ventas, se genera el pedido, y al llegar la mercancía se compara la factura contra lo pedido para detectar faltantes o cambios de precio.

Lectura de facturas para dar entrada: primero se usa el XML del CFDI, que se lee directamente sin IA. Solo cuando no hay XML (PDF, foto, nota de remisión) se usa IA. Lote y caducidad pueden no venir en el XML, y la IA puede complementarlos desde el PDF. La IA nunca mete datos directamente al inventario: siempre hay una pantalla de revisión donde el usuario corrige y confirma, con validaciones como que la suma de renglones coincida con el total, y marcando lo que no se leyó con seguridad.

Se guarda una tabla de equivalencias por proveedor que relaciona cómo nombra el proveedor cada producto con el producto del catálogo. La primera vez se relaciona a mano (con sugerencia de la IA) y después se reconoce solo. Si el producto no existe, se propone darlo de alta con los datos leídos.

## Asistente de IA

Se usa la API de Claude, no un modelo local, por costo y precisión. La IA se usa solo donde hay texto libre: leer facturas en PDF o imagen y responder preguntas en lenguaje natural sobre el negocio. La IA nunca calcula totales ni cobros, eso lo hace el código de forma exacta, y cualquier acción que modifique datos requiere confirmación.

Todo lo que se pueda resolver con consultas a la base de datos se hace sin IA: productos próximos a caducar, más vendidos, sugerencias de resurtido y detección de productos que se caducan seguido porque se compran de más.

## Facturación a clientes

La farmacia factura de forma ocasional, hoy desde PVWin, que ya está conectado a un PAC. La facturación CFDI NO va en la primera versión; mientras tanto siguen facturando desde PVWin. Cuando se agregue, se conectará por API al mismo PAC si es posible (pendiente averiguar cuál es).

## Etapas propuestas

La primera etapa es la estructura del proyecto, el modelo de datos, usuarios y permisos, catálogo con importación desde Excel, e inventario con lotes y caducidades. La segunda es ventas, cobro, tickets, cajón, turnos y corte de caja. La tercera es entradas de mercancía, proveedores, pedidos, márgenes y lectura de facturas XML. La cuarta es la lectura de facturas con IA, alertas y el asistente en lenguaje natural. Después vienen la integración con Mercado Pago Point, la facturación CFDI, los descuentos y la preparación para vender el sistema a otros negocios.

## Estado actual

De la etapa 1 ya están hechos (ver README.md) la estructura del proyecto, la conexión a PostgreSQL con Alembic, el endpoint `/health`, las tablas `negocios`, `usuarios`, `categorias`, `productos`, `lotes` y `ajustes_inventario` con `negocio_id` en todas, el factor de conversión para productos a granel, el control de lote configurable por categoría, el redondeo de precio de venta por negocio, el CRUD de categorías y productos con búsqueda y borrado lógico, el script para crear usuarios, el importador de PVWin descrito arriba (ya se corrió con los datos reales: 7,790 productos) y el inventario por lote (existencias en orden FEFO, captura de caducidades, ajustes y mermas con motivo, bitácora y avance de la migración). También está el inicio de sesión con permisos por rol: sesiones guardadas en la base de datos con cookie httpOnly de 12 horas (se prefirió sobre JWT para que cerrar sesión o desactivar a un usuario corte el acceso de inmediato), y el negocio y el usuario salen de la sesión en todos los endpoints. Con esto la etapa 1 está completa; lo único pendiente es reimportar cuando llegue el catálogo completo de PVWin.

De la etapa 2 ya están hechos (ver README.md): cajas y turnos con corte de caja (un solo turno abierto por caja; ya existen "Mostrador 1" y "Mostrador 2" en la base real); ventas con cobro en efectivo, tarjeta y mixto, descuento de lotes por FEFO o por el lote que indica el vendedor, captura de caducidad al vender, desglose de IVA e IEPS y folios consecutivos; cancelaciones, devoluciones y cambios de producto (los hace el admin; el cajero pide devoluciones y cancelaciones y un admin las autoriza desde el centro de notificaciones); ventas en espera (hasta 5 por caja); tickets en ESC/POS con impresión por red o por agente USB y apertura del cajón solo con efectivo (encabezado y pie de Farmacia La Fe ya configurados); y las pantallas en HTML + Alpine.js: inicio de sesión, venta en mostrador (con escaneo, búsqueda por nombre con F2 y modo cobro con Esc), turno y corte, devoluciones, cancelaciones y cambios de producto, y el centro de notificaciones (solo admin). Hay casi 250 pruebas automáticas (`pytest`) que corren contra una base aparte.

Para retomar, lo pendiente es:
- Ya está la pantalla de inicio o "núcleo" con pantallas responsivas (ver arriba). La migración de la imagen de inicio (`b7e4a1c9d2f3`) ya se corrió en la base real (29/09/2026); falta subir la imagen de Farmacia La Fe desde el núcleo.
- Precios ya importados en la base real (29/09/2026): 10,385 de 10,398 productos tienen precio y 6,304 se pueden vender (tienen existencia). Falta revisar: los 2,608 productos nuevos (IVA 0% supuesto, sin costo ni departamento), los 2,090 a los que se les quitó el IVA deducido por grupo (hoja "Impuestos corregidos" del reporte en `datos/`) y los 13 sin precio. Si se consigue de PVWin el Catálogo de artículos completo de la A a la Z (con %IVA), volver a correr `importar_precios_pvwin` para tomar sus impuestos.
- Probar la impresión en la farmacia: instalar el agente en una computadora de mostrador (`agente_impresion/LEEME.md`), configurar la caja y usar la prueba de impresión para revisar acentos, corte y cajón.
- Pantallas que faltan: inventario (captura de caducidades, ajustes, mermas, avance), catálogo y precios para el administrador, y la vista sencilla para la tableta. La de devoluciones y cancelaciones ya está (`/devoluciones`, solo admin): se busca la venta por folio o de la lista de hoy, se elige devolver piezas o cancelar todo, se pide motivo y se confirma diciendo cuánto entregar en efectivo y cuánto regresar a tarjeta. Ahí mismo está el cambio de producto: se marca lo que regresa, se escanea o busca lo que se lleva, y la pantalla dice si el cliente paga la diferencia (efectivo, tarjeta o las dos) o si se le regresa en efectivo; imprime el ticket de la venta nueva.
- Dejar el servidor instalado como servicio de Windows en la computadora dedicada, con arranque automático.
- Después sigue la etapa 3 (entradas de mercancía, proveedores, pedidos, márgenes y lectura de facturas XML).

Para ver las pantallas sin tocar datos reales: `python -m app.scripts.servidor_demo` levanta un servidor en http://127.0.0.1:8001 sobre la base de pruebas, con productos de ejemplo (usuario `demo`, contraseña `demo1234`).

Decisión de lotes al vender: el sistema siempre sugiere el lote con la caducidad más próxima (FEFO); los lotes sin caducidad registrada van al final porque no se sabe cuándo caducan. En la práctica el vendedor entrega la caja que toma primero, así que la pantalla de venta debe hacer muy fácil indicar el lote real (escaneando o eligiendo) para que el descuento se haga del lote correcto; si no indica nada, se descuenta por FEFO.

Decisiones del importador ya tomadas: cada departamento de PVWin se vuelve una categoría "Depto N" que se renombra después (la categoría recuerda su número de PVWin, así que reimportar no pierde el nombre ni el margen); los códigos de barras que perdieron el cero inicial al pasar por Excel se guardan tal cual y la búsqueda por clave ignora los ceros a la izquierda; dos productos se consideran el mismo si comparten clave y su descripción coincide ignorando espacios y signos (así se fusionan los dos ZIVATA), y una clave usada por productos distintos (como "0" y "1") se quita y el producto queda marcado para asignarle clave nueva; volver a importar se hace con `--reemplazar`, que borra productos, lotes y ajustes, y solo se usa antes de tener ventas reales.

## Datos pendientes

Falta el reporte "Catálogo de artículos" completo de la A a la Z y, sobre todo, un reporte de PVWin que traiga el precio de venta: hoy ningún producto importado tiene precio, y sin eso no se puede vender. Se decidió tomar los precios reales de PVWin en lugar de calcularlos con márgenes. Falta el archivo original del logo de Farmacia La Fe (PNG o JPG, no foto de pantalla). Falta el RFC del negocio para agregarlo al encabezado del ticket (hoy lleva dirección y teléfono), y con qué PAC está contratada la facturación actual.