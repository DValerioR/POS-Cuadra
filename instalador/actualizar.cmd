@echo off
rem Actualiza Cuadra con la version mas nueva de GitHub (respalda antes).
rem Doble clic: pide permiso de administrador.
net session >nul 2>&1
if errorlevel 1 (
  powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
  exit /b
)
powershell -ExecutionPolicy Bypass -File "%~dp0actualizar.ps1"
pause
