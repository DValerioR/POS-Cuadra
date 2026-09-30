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
4. En el `.env` del POS (se podrá capturar desde el programa cuando esté el bot):

   ```
   WHATSAPP_TOKEN=EAAG...
   WHATSAPP_NUMERO_ID=123456789012345   # "Identificador del número de teléfono" en Meta
   ```

## Plantillas de mensaje (dar de alta en Meta)

WhatsApp solo deja que la farmacia escriba primero (fuera de las 24 horas
después del último mensaje del cliente) con **plantillas aprobadas**. Los
avisos de encargos usan estas tres. Darlas de alta en el Administrador de
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
un cliente dentro de las 24 horas en que escribió no se cobra.
