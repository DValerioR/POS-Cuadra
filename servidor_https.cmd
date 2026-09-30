@echo off
rem Servidor HTTPS en la red local, para la tableta (la camara solo funciona con HTTPS).
rem Antes, una sola vez: .venv\Scripts\python.exe -m app.scripts.certificado_local
rem En la tableta: https://<IP de esta computadora>:8443/tableta
cd /d "%~dp0"
if not exist certificados\servidor.crt (
  echo Falta el certificado. Corre primero: .venv\Scripts\python.exe -m app.scripts.certificado_local
  exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile certificados\servidor.key --ssl-certfile certificados\servidor.crt
