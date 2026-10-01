# WhatsApp Business

El POS usa la **API oficial de WhatsApp Business** (Cloud API de Meta). No se
usan programas que conectan un WhatsApp normal por código QR: van contra las
reglas de WhatsApp y bloquean el número.

## Lo que se necesita

1. Un número para la farmacia que no esté ya en la app de WhatsApp (o darlo de
   baja de la app antes).
2. Una cuenta de **Meta Business** verificada con los datos de la farmacia.
3. En developers.facebook.com: una app con el producto "WhatsApp", el número
   agregado y un **token de acceso permanente** (usuario del sistema).
4. Todo lo de Meta se captura desde el programa, en **Configuración → WhatsApp
   y bot** (se guarda en el `.env`): token de acceso, identificador del número
   (Phone number ID), secreto de la app (Configuración de la app → Básica) y una
   clave para verificar el webhook (botón "Generar").

## El bot (contesta a los clientes)

Código: `app/whatsapp/bot.py` (reglas y herramientas), `app/api/whatsapp.py`
(webhook y pantallas). Contesta las 24 horas, de usted y con redacción formal:

- Precio y si hay ("sí tenemos / nos quedan pocas piezas / por el momento no
  tenemos"; nunca cantidades), ofertas y si requiere receta. Tolera nombres mal
  escritos ("¿Se refiere a…?") y lee fotos de la caja o la receta.
- Horario (con los días especiales), dirección, liga de ubicación, teléfono y
  formas de pago: se capturan en **Datos del negocio** (Horario de atención e
  Información para clientes).
- Encargos: si el producto es por encargo o no hay, pregunta si lo quiere
  encargar y lo registra (sale en Encargos con "WhatsApp"). Fuera de horario
  no se confirma: le informa que no puede procesarse fuera del horario laboral.
- Nunca da consejo médico, dosis ni diagnósticos; ofrece pasarlo con el personal.
- **Pasar a una persona** (si el cliente lo pide, tiene una queja, quiere
  factura o el bot no sabe qué contestar): la conversación sale primero en
  **Ventas → Conversaciones de WhatsApp** y en la campana, y se manda la
  plantilla `atencion_cliente` al **número para avisos** (el WhatsApp de la
  tableta). Desde Conversaciones alguien la toma ("Atenderla yo"), le contesta
  y al terminar la regresa al bot. Mientras la atiende una persona el bot no
  contesta; si pasan 12 horas sin mensajes, regresa sola al bot.
- Si la IA falla (sin internet o sin clave), le dice al cliente que una persona
  le atenderá y la pasa a Conversaciones. Más de 40 mensajes de un cliente en un
  día también pasan a una persona (para cuidar el costo).
- Se puede apagar el bot (Configuración → WhatsApp y bot): todo llega a
  Conversaciones para que lo conteste una persona.

WhatsApp solo deja escribir texto libre dentro de las 24 horas desde el último
mensaje del cliente; después, Conversaciones no deja contestar (hay que esperar
a que el cliente escriba o llamarle).

### Que Meta pueda mandar los mensajes al servidor (túnel)

Meta avisa de cada mensaje a una dirección de internet con HTTPS (webhook). El
servidor de la farmacia está en la red local, así que se usa un túnel seguro,
sin abrir puertos del módem. Recomendado: **Cloudflare Tunnel** (gratis):

1. Crear una cuenta de Cloudflare y un dominio (o usar uno que ya tengan).
2. En la computadora servidor instalar `cloudflared` y crear el túnel hacia
   `http://localhost:8000`, publicado solo en la ruta `/whatsapp/webhook`
   (en Cloudflare Zero Trust → Networks → Tunnels). Instalarlo como servicio
   para que arranque con Windows.
3. En developers.facebook.com → la app → WhatsApp → Configuración → Webhook:
   - URL de devolución de llamada: `https://<dominio del túnel>/whatsapp/webhook`
   - Token de verificación: la misma clave que se guardó en el programa.
   - Suscribirse al campo **messages**.

Cada mensaje trae la firma de Meta (`X-Hub-Signature-256`) y el servidor la
comprueba con el secreto de la app: lo que no venga de Meta se rechaza. Si se
cae internet solo se detiene el bot; el punto de venta sigue igual.

### Probarlo sin Meta (demo)

En el servidor demo (`servidor_demo --ia-simulada`) el WhatsApp y la IA son
simulados: en Conversaciones de WhatsApp aparece "Probar como cliente" para
escribir (o mandar una foto) como si fuera un cliente y ver qué contesta el bot.

## Plantillas de mensaje (dar de alta en Meta)

WhatsApp solo deja que la farmacia escriba primero (fuera de las 24 horas
después del último mensaje del cliente) con **plantillas aprobadas**. Los
avisos de encargos usan estas tres (y el aviso al personal, `atencion_cliente`,
abajo). La pantalla Configuración → WhatsApp y bot las muestra con un botón
para copiar el texto. Darlas de alta en el Administrador de
WhatsApp → Plantillas de mensajes, categoría **Utilidad**, idioma **Español
(México)**, con el nombre y el texto exactos (`{{1}}` cliente, `{{2}}`
producto, `{{3}}` nombre de la farmacia):

**encargo_pedido**

> Estimado(a) {{1}}, le informamos que su encargo de {{2}} ya fue solicitado a nuestro proveedor. Le avisaremos por este medio en cuanto llegue a {{3}}. Gracias por su preferencia.

**encargo_disponible**

> Estimado(a) {{1}}, le informamos que su encargo de {{2}} ya se encuentra disponible en {{3}}. Puede pasar a recogerlo en nuestro horario de atención. Gracias por su preferencia.

**encargo_no_disponible**

> Estimado(a) {{1}}, lamentamos informarle que no fue posible encargar {{2}}, {{3}}. Si lo desea, con gusto le sugerimos una alternativa. Atentamente, {{4}}.

En esta, `{{3}}` es el motivo en frase formal (según lo que elija el personal):
"ya que nuestro proveedor no cuenta con existencias por el momento", "ya que se
trata de un medicamento controlado", "ya que nuestro proveedor no maneja este
producto", "ya que es un producto que no manejamos en nuestra farmacia" o, con
otro motivo, "por causas ajenas a
nuestra farmacia" (lo que escribe el personal no se le manda al cliente), y
`{{4}}` es el nombre de la farmacia. En Meta, al dar de alta la plantilla, se
pone un ejemplo para cada variable.

**atencion_cliente** (al WhatsApp del personal, cuando un cliente necesita a una persona)

> Un cliente necesita atención en WhatsApp: {{1}} ({{2}}). Motivo: {{3}}. Contéstele desde el sistema, en Ventas → Conversaciones de WhatsApp.

`{{1}}` nombre del cliente, `{{2}}` su número, `{{3}}` el motivo.

(Los textos viven también en `app/whatsapp/cliente.py`; si se cambian allá,
hay que cambiarlos y volver a aprobarlos en Meta.)

## Cuándo se envían

En Encargos, al marcar "Ya se pidió" (o al enviar un pedido que incluye el
encargo), "Ya llegó" o "No se encargó", el sistema manda la plantilla al
teléfono del cliente. Si no se puede (el cliente no dejó teléfono, WhatsApp
no está configurado o falla el envío), el encargo queda con "Falta avisar"
para que alguien de la farmacia le avise y lo marque.

## Costos

Meta cobra cada plantilla de "Utilidad" que envía la farmacia (unos centavos
de dólar por mensaje en México; ver la tabla de precios de Meta). Contestar a
un cliente dentro de las 24 horas en que escribió no se cobra. Además, cada
respuesta del bot usa la API de Claude (y leer una foto, otra llamada).
