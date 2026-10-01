# Instalar Cuadra en la farmacia

El programa se baja de GitHub (`DValerioR/POS-Cuadra`). Hace falta internet
y una cuenta de Windows con permisos de administrador. Todo se puede volver a
correr: lo que ya está hecho se salta y **nunca se borra una base que ya
tenga datos**.

## 1. La computadora servidor (una sola)

Es la que guarda la base de datos; conviene que sea la que más tiempo pasa
prendida. Si se va a pasar la información de otra computadora, primero hay que
copiar a una USB el respaldo más reciente (Configuración → Respaldos →
"Respaldar ahora"; el archivo `.dump` queda en `datos\respaldos`).

1. Abrir **PowerShell como administrador** (clic derecho en Inicio →
   "Terminal (Administrador)").
2. Pegar esta línea y presionar Enter:

   ```
   irm https://raw.githubusercontent.com/DValerioR/POS-Cuadra/master/instalador/instalar.ps1 -OutFile $env:TEMP\instalar.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\instalar.ps1
   ```

3. El instalador:
   - instala Git, Python 3.14 y PostgreSQL 17, y baja el programa a `C:\POS`;
   - crea la base `pos` con su propio usuario y el archivo `.env` (que solo
     pueden leer los administradores). La contraseña del usuario `postgres`
     queda en `C:\POS\datos\postgres_admin.txt`: hay que guardarla en un lugar
     seguro;
   - **pregunta por los datos**: escribe la ruta del respaldo `.dump` (ej.
     `E:\pos_20261001_220000_manual.dump`) para cargar la información, o deja
     vacío para empezar con una base nueva (pide el nombre del negocio y crea
     al primer administrador);
   - crea el certificado HTTPS para la tableta;
   - deja el servidor como tarea de Windows ("Cuadra - servidor" en el puerto
     8000 y "Cuadra - servidor HTTPS" en el 8443) que arranca sola al prender
     la computadora, aunque nadie inicie sesión, y se vuelve a levantar si se
     cierra; y la tarea "Cuadra - actualizar" (ver abajo);
   - abre esos puertos en el firewall solo para la red privada (si la red está
     marcada como pública, pregunta si se cambia);
   - instala Chrome si falta y crea el acceso directo "Cuadra" en el escritorio.
4. Al final muestra la dirección para las demás computadoras (ej.
   `http://192.168.1.50:8000`). **Fija esa IP en el módem** (reservación DHCP)
   para que no cambie.

Lo que pasó queda en `C:\ProgramData\Cuadra\instalacion.log`.

Los respaldos automáticos los hace el mismo servidor (cada día, en
`C:\POS\datos\respaldos`). Después de instalar, elige en Configuración →
Respaldos dónde guardar una copia fuera de la computadora (USB, Google Drive u
OneDrive).

## 2. Cada caja y la bodega

Con el servidor ya prendido, en cada computadora, en PowerShell como
administrador:

```
irm https://raw.githubusercontent.com/DValerioR/POS-Cuadra/master/instalador/instalar_caja.ps1 -OutFile $env:TEMP\caja.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\caja.ps1
```

Pide la IP del servidor, instala Chrome si falta y crea el acceso directo.
Si la computadora tiene la **impresora de tickets por USB**, pregunta cuál es y
pide el token de la caja (en el sistema: Configuración → Cajas e impresoras →
la caja → "USB con agente" → "Generar token"). Instala el agente de impresión
en `C:\POS-agente`, que arranca solo al prender la computadora y solo acepta
conexiones del servidor. Después, en Cajas e impresoras, pon la IP de esa
computadora y usa "Imprimir prueba" y "Probar cajón".

## 3. Actualizaciones (automáticas)

No hay que ir a la farmacia: basta con subir la versión nueva a GitHub (rama
`master`). La tarea de Windows **"Cuadra - actualizar"** revisa cada 30 minutos
y, si hay versión nueva, la instala **solo cuando la farmacia está cerrada**
(horario de Datos del negocio y al menos 30 minutos antes de abrir; si no hay
horario capturado, de 1 a 5 de la mañana):

1. Respalda la base.
2. Baja la versión nueva, instala librerías y pone al día la base.
3. Reinicia el servidor y revisa que responda.
4. **Si algo falla, regresa sola a la versión anterior** (código y base), lo
   avisa en la campana y no vuelve a intentar esa versión hasta que haya otra
   más nueva o un administrador pida "Instalar ahora".

En **Configuración → Actualizaciones** se ve la versión instalada, si hay una
nueva (con la lista de cambios), el historial y el botón **"Instalar ahora"**
(no espera al cierre; el sistema se reinicia alrededor de un minuto).

Las pantallas abiertas en las cajas avisan "Hay una versión nueva del
sistema" con un botón para recargar. Inicio, Vender, Turno, la tableta,
Encargos, Conversaciones y Notificaciones se recargan solas si nadie las ha
usado en 5 minutos (Vender nunca a media venta). Las demás esperan a que
alguien presione "Recargar", para no perder algo capturado a medias.

Para instalar en ese momento desde el servidor: doble clic en
`C:\POS\instalador\actualizar.cmd` (pide permiso de administrador).
Registro: `C:\ProgramData\Cuadra\actualizacion.log`.

**Cuidado:** todo lo que se sube a `master` llega a la farmacia esa misma
noche. Sube solo cambios terminados y con las pruebas pasando.

## Si algo falla

- El instalador dice en qué paso se detuvo; se corrige y se vuelve a correr.
- El servidor deja su registro en `C:\POS\datos\servidor.log`.
- Para detener o prender el servidor a mano: Programador de tareas →
  "Cuadra - servidor".
- Restaurar un respaldo sobre una base que ya tiene datos no lo hace el
  instalador (para no borrar nada por error); ver `README.md`, "Respaldos".
