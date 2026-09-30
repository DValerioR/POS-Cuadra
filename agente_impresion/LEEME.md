# Agente de impresión (impresoras USB)

Programa pequeño que corre en cada computadora de mostrador que tenga la
impresora de tickets conectada por USB. Recibe los tickets del servidor del
POS y se los pasa a la impresora a través de Windows, en modo RAW (así
llegan también el corte de papel y la apertura del cajón).

Si algún día la impresora se conecta por Ethernet, el agente ya no hace
falta: en la caja se cambia `impresora_modo` a `red` y la dirección a
`IP-DE-LA-IMPRESORA:9100`.

## Instalación en una computadora de mostrador

1. **Python** (el mismo que el servidor) instalado, con "Add to PATH".
   El agente solo usa la biblioteca estándar: no hay que instalar nada con pip.

2. Copiar `agente.py` a `C:\POS-agente\agente.py`.

3. Ver el nombre exacto de la impresora en PowerShell:
   ```
   Get-Printer | Select-Object Name
   ```
   Por ejemplo `EPSON TM-T20II Receipt` o `BIXOLON SRP-330II`.

4. El token (una contraseña larga, distinta en cada caja) se genera en el POS:
   Inicio → Configuración → Cajas e impresoras → la caja → "USB con agente" →
   "Generar token". Ahí mismo aparece el comando del paso 5 listo para copiar.

5. Probarlo a mano:
   ```
   python C:\POS-agente\agente.py --impresora "EPSON TM-T20II Receipt" --token EL_TOKEN
   ```
   Debe decir `Agente de impresión escuchando en el puerto 9110`.

6. Abrir el puerto en el firewall **solo para el servidor** (PowerShell como
   administrador; cambia `IP-DEL-SERVIDOR`):
   ```
   New-NetFirewallRule -DisplayName "Agente impresion POS" -Direction Inbound -Protocol TCP -LocalPort 9110 -RemoteAddress IP-DEL-SERVIDOR -Action Allow
   ```

7. En el POS (como admin), en Cajas e impresoras: poner la IP de esta
   computadora, el papel (80 o 58 mm), Guardar, y usar "Imprimir prueba" y
   "Probar cajón". Revisa que los acentos y la Ñ salgan bien. (Por API es
   `PUT /cajas/{id}` y `POST /cajas/{id}/prueba-impresion`.)

8. Que arranque solo al prender la computadora: en el Programador de tareas,
   crear una tarea "Al iniciar el sistema", que se ejecute aunque no haya
   sesión iniciada, con la acción:
   - Programa: `pythonw.exe` (sin ventana)
   - Argumentos: `C:\POS-agente\agente.py --impresora "EPSON TM-T20II Receipt" --token EL_TOKEN`

## Recomendaciones

- La computadora de mostrador y la impresora de red deben tener **IP fija**
  (reservación DHCP en el módem), para que la dirección configurada no cambie.
- Si un ticket no sale, la venta **sí queda guardada**: el POS avisa el error
  y se puede reimprimir con `POST /ventas/{id}/imprimir`.
- `GET http://IP-DE-LA-PC:9110/estado` dice si el agente está vivo.
