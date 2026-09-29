@echo off
rem Respaldo de la base del POS (lo corre la tarea de Windows "Cuadra - respaldo diario").
rem Deja el resultado en backups\respaldo.log.
cd /d "%~dp0"
if not exist backups mkdir backups
echo ==== %date% %time% >> "backups\respaldo.log"
".venv\Scripts\python.exe" -m app.scripts.respaldar >> "backups\respaldo.log" 2>&1
