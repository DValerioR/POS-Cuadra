# Contexto del proyecto: Punto de venta con asistente de IA

Este documento resume todas las decisiones tomadas antes de empezar a programar. Léelo completo antes de proponer estructura, modelo de datos o código.

## Qué es

Un punto de venta (POS) para negocios, desarrollado en Python, que empieza funcionando en una farmacia familiar real y que después se venderá a otros negocios. La primera versión es solo para farmacia, pero el diseño debe permitir crecer a otros giros (restaurantes, abarrotes) mediante un núcleo común y módulos por giro. Los módulos de otros giros NO se construyen todavía.

Desde el inicio, todos los datos deben estar separados por negocio (por ejemplo, un `negocio_id` en las tablas principales), y el nombre, logo, márgenes y categorías deben ser configurables, no fijos en el código.

## Quién lo desarrolla

El desarrollador está estudiando programación, sabe SQL básico y un poco de MongoDB. Explica las decisiones técnicas con claridad, avanza por etapas pequeñas que funcionen de verdad y evita complejidad innecesaria. El proyecto se versiona con Git desde el primer día.

## Infraestructura

La farmacia tiene una sola sucursal con cuatro computadoras Windows: dos en bodega para inventario y dos en mostrador para ventas, además de una tableta Android. El sistema debe funcionar en red local, sin depender de internet y sin pagar servidores.

El sistema actual (PVWin) tiene el problema de que el servidor vive dentro del programa de la computadora principal, y si alguien lo cierra, las demás dejan de funcionar. Esto no debe repetirse: el servidor corre como servicio independiente que arranca solo con el equipo, idealmente en una computadora dedicada.

La arquitectura acordada es una aplicación web en red local que en las computadoras se ve como aplicación de escritorio (con su ícono, sin navegador visible), y que en la tableta se abre desde el navegador. La tableta tendrá una vista sencilla para consultar existencias y precios y para capturar lotes y caducidades.

Stack: Python y PostgreSQL. El framework web y la forma de empaquetar la app de escritorio están por definir; propón opciones justificadas. MongoDB queda descartado.

## Catálogo

El catálogo es grande, del orden de varios miles de productos: medicamentos de patente, genéricos y similares, además de perfumería y artículos como pañales, desodorantes, champús y leches de bebé. La búsqueda en mostrador debe ser instantánea mientras se escribe, así que requiere buen indexado (búsqueda parcial y sin importar acentos o mayúsculas).

El catálogo inicial se importa desde un Excel exportado de PVWin, que incluye productos, precios y existencias. El sistema también debe poder exportar inventario y reportes de ventas a Excel.

Se puede marcar un producto como "requiere receta" (por ejemplo antibióticos), lo cual solo muestra un aviso al vender. La farmacia no maneja medicamentos controlados.

## Usuarios y permisos

Cada persona tiene su propio usuario, nunca compartido, y toda venta, ajuste, descuento, devolución y cierre de turno queda registrado con el usuario que lo hizo.

Los administradores (la dueña, su hija y el desarrollador) tienen acceso a todo, incluidos precios, reportes, cancelaciones y devoluciones. Los usuarios de bodega dan entradas de mercancía, registran lotes, hacen ajustes de inventario y pedidos, pero no cobran ni ven reportes de dinero. Los usuarios de mostrador venden, cobran y hacen su corte de caja, pero no cambian precios, no cancelan ni borran ventas.

## Lotes y caducidades (parte central del sistema)

Hoy la farmacia no lleva lotes ni caducidades en el sistema; revisa la caja al vender y retira productos dos meses antes de caducar. El sistema nuevo sí los maneja.

Cada producto tiene varios registros de existencia, uno por lote, cada uno con su caducidad y cantidad. Cuando entra mercancía de un producto con un lote nuevo, se crea un registro nuevo en lugar de sumarse al anterior. Al vender, el sistema descuenta primero el lote que caduca antes (FEFO), y si ese lote no alcanza, completa con el siguiente. Cada venta guarda de qué lote salió cada pieza, para poder rastrear un lote si hay un retiro sanitario.

En pantalla de venta el sistema indica qué lote entregar (por ejemplo "entregar lote A, caducidad marzo 2027"). Si el vendedor entrega una caja de otro lote, debe poder escanearla o elegirla para que el descuento se haga del lote real.

Migración del inventario existente: de aquí en adelante toda entrada nueva se registra con lote y caducidad. Lo que ya está en anaquel se captura conforme se vende: si el producto aún no tiene caducidad registrada, aparece un campo pequeño para capturar la de la caja en mano. Ese campo se puede saltar sin bloquear la venta. El sistema marca los productos "sin caducidad registrada", lleva la cuenta del avance y señala los de poca rotación para capturarlos manualmente.

Alertas de caducidad: avisar con suficiente anticipación para mover el producto o devolverlo al proveedor, considerando que los distribuidores suelen aceptar devoluciones con tres a seis meses de anticipación. Lo caducado o dañado sale del inventario como merma registrada (con motivo y usuario), nunca se borra.

## Ventas y cobro

Métodos de pago: efectivo con cálculo de cambio, tarjeta y pagos mixtos. Transferencia queda preparada pero desactivada. En la primera versión el pago con tarjeta se registra manualmente; la integración con una terminal Mercado Pago Point es una etapa posterior.

Hardware existente que se reutiliza: lector de código de barras, impresora de tickets y cajón de dinero. El cajón se abre solo al cobrar en efectivo, conectado a la impresora. Modelo de impresora pendiente de confirmar.

No hay crédito a clientes ni ventas a cuenta. Los descuentos quedan preparados pero desactivados; cuando se activen, el vendedor tendrá un tope y por encima de él se requiere autorización de administrador, con registro de quién lo aplicó.

Devoluciones y cancelaciones solo las hace un administrador, con motivo registrado. La mercancía devuelta regresa siempre al inventario, a su lote original (el vendedor verifica que se pueda revender).

## Turnos y corte de caja

Hay dos turnos, mañana y tarde. Al abrir turno se captura el fondo de caja. Al cerrarlo, el sistema muestra lo esperado en efectivo y en tarjeta, el cajero captura lo contado y queda registrada la diferencia con el nombre de quien cerró.

## Precios y márgenes

Los precios se ajustan cada vez que cambia el costo del proveedor, hacia arriba o hacia abajo. Se usan márgenes por categoría, por ejemplo 20% para patente, 50% para similares y 5% para leches de bebé (configurables).

Cuando entra una factura con un costo distinto, el sistema recalcula el precio de venta sugerido y lo muestra para aprobación antes de aplicarlo. Debe permitir precio manual en productos donde el margen no aplique, y guardar historial de precios.

Los medicamentos de patente tienen precio máximo al público impreso en la caja. Si el margen da un precio mayor, se usa el máximo y el sistema avisa que ese producto se vende con menos margen del deseado.

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

## Datos pendientes

Falta confirmar cuántos productos trae el Excel exportado de PVWin, la marca y modelo de la impresora de tickets, y con qué PAC está contratada la facturación actual.
