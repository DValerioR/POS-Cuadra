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
     cierra;
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

## 3. Actualizar

En el servidor, doble clic en `C:\POS\instalador\actualizar.cmd` (pide permiso
de administrador). Respalda la base, baja la versión nueva de GitHub, instala
lo que haga falta, pone al día la base y vuelve a prender el servidor. Las
demás computadoras toman la versión nueva solas al recargar la página.
Lo que pasó queda en `C:\ProgramData\Cuadra\actualizacion.log`.

## Si algo falla

- El instalador dice en qué paso se detuvo; se corrige y se vuelve a correr.
- El servidor deja su registro en `C:\POS\datos\servidor.log`.
- Para detener o prender el servidor a mano: Programador de tareas →
  "Cuadra - servidor".
- Restaurar un respaldo sobre una base que ya tiene datos no lo hace el
  instalador (para no borrar nada por error); ver `README.md`, "Respaldos".
