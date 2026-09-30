# Respaldos de la base de datos

## Qué se respalda y dónde

- Todo: productos, lotes, ventas, turnos, usuarios, facturas… Es un archivo
  de `pg_dump` en formato "custom" (`pos_AAAAMMDD_HHMMSS_auto.dump` o
  `..._manual.dump`).
- Carpeta: `datos/respaldos` dentro de la carpeta del sistema (se cambia con
  `CARPETA_RESPALDOS` en el `.env`).
- **Automático:** mientras el servidor está prendido, cada 30 minutos revisa
  si el último respaldo tiene más de 24 horas y, si es así, hace uno. Se
  guardan los últimos 30 automáticos (`RESPALDOS_A_CONSERVAR`). Los hechos con
  el botón "Respaldar ahora" no se borran solos.
- **Copia fuera de la computadora (recomendado):** con
  `CARPETA_RESPALDOS_COPIA=E:\Respaldos POS` (una USB) o una carpeta que se
  sincronice con Google Drive / OneDrive, cada respaldo se copia también ahí.
  Si la copia falla (USB desconectada), el respaldo local se hace igual y la
  pantalla lo avisa.
- Si `pg_dump` no se encuentra solo, indicar su carpeta con
  `PG_BIN=C:\Program Files\PostgreSQL\17\bin`.
- Para apagar los automáticos: `RESPALDOS_AUTOMATICOS=false`.

En el programa: Configuración → Respaldos (ver el último, respaldar ahora,
descargar). Si el último falló o hace más de un día que no hay respaldo, la
campana de notificaciones lo avisa a los administradores.

## Recuperar la información de un respaldo

Esto reemplaza **toda** la información actual por la del respaldo. Hacerlo
con cuidado y, de preferencia, con ayuda técnica.

1. Cerrar el servidor del POS (y que nadie esté vendiendo).
2. Por si acaso, respaldar lo que hay ahora (el botón, o `pg_dump` a mano).
3. En una terminal, en la carpeta de PostgreSQL (`C:\Program Files\PostgreSQL\17\bin`):

   ```
   dropdb -U postgres pos
   createdb -U postgres pos
   pg_restore -U postgres -d pos --no-owner "C:\POS\datos\respaldos\pos_20261001_220000_auto.dump"
   ```

   (Pide la contraseña del usuario de PostgreSQL. Si la base tiene otro
   nombre o usuario, ver `DATABASE_URL` en el `.env`.)
4. En la carpeta del POS: `.venv\Scripts\python -m alembic upgrade head`
   (por si el respaldo es de una versión anterior del sistema).
5. Volver a arrancar el servidor.

Para probar un respaldo sin tocar la base real, restaurarlo en otra base
(`createdb -U postgres pos_prueba_respaldo` y `pg_restore -d pos_prueba_respaldo ...`).
