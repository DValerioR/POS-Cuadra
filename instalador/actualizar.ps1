<#
Actualiza Cuadra en el SERVIDOR con la versión más nueva de GitHub.
Correr como administrador (o con doble clic en actualizar.cmd).

  1. Respalda la base (por si algo sale mal).
  2. Baja la versión nueva (git pull).
  3. Instala las librerías nuevas y pone al día la base (migraciones).
  4. Reinicia el servidor y revisa que responda.

Las demás computadoras toman la versión nueva solas al recargar la página.
#>
param([string]$Destino = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = "Stop"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "Corre la actualización como administrador." -ForegroundColor Red; exit 1 }

$venv = Join-Path $Destino ".venv\Scripts\python.exe"
$git = Get-Command git.exe -ErrorAction SilentlyContinue
$git = if ($git) { $git.Source } else { "$env:ProgramFiles\Git\cmd\git.exe" }
$carpetaLog = Join-Path $env:ProgramData "Cuadra"
New-Item -ItemType Directory -Force -Path $carpetaLog | Out-Null
Start-Transcript -Path (Join-Path $carpetaLog "actualizacion.log") -Append | Out-Null

function Correr([string]$exe, [string[]]$argumentos, [string]$error) {
    & $exe @argumentos
    if ($LASTEXITCODE -ne 0) { throw "$error (código $LASTEXITCODE)" }
}

$tareas = @("Cuadra - servidor", "Cuadra - servidor HTTPS")
Push-Location $Destino
try {
    Write-Host "`n[1/4] Respaldando la base..." -ForegroundColor Cyan
    Correr $venv @("-c", "from app.services import respaldos; r = respaldos.hacer(); print('    Respaldo:', r['nombre'])") "No se pudo respaldar; no se actualizó nada"

    Write-Host "`n[2/4] Bajando la versión nueva..." -ForegroundColor Cyan
    $antes = (& $git rev-parse --short HEAD).Trim()
    Correr $git @("pull", "--ff-only") "No se pudo bajar la versión nueva (¿hay internet? ¿se cambió algún archivo a mano?)"
    $despues = (& $git rev-parse --short HEAD).Trim()
    if ($antes -eq $despues) { Write-Host "    Ya estaba en la versión más nueva ($despues)." }
    else { Write-Host "    De $antes a $despues." }

    Write-Host "`n[3/4] Librerías y base de datos..." -ForegroundColor Cyan
    foreach ($t in $tareas) { if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $t } }
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*uvicorn app.main:app*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Correr $venv @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt") "No se pudieron instalar las librerías"
    Correr $venv @("-m", "alembic", "upgrade", "head") "No se pudo poner al día la base"
} catch {
    Write-Host "`nNo se terminó la actualización: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Se vuelve a prender el servidor. Detalle en $carpetaLog\actualizacion.log"
} finally {
    Pop-Location
}

Write-Host "`n[4/4] Prendiendo el servidor..." -ForegroundColor Cyan
foreach ($t in $tareas) { if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) { Start-ScheduledTask -TaskName $t } }
$listo = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        if ((Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $listo = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
if ($listo) { Write-Host "`nListo: el servidor está prendido con la versión nueva." -ForegroundColor Green }
else { Write-Host "`nEl servidor no respondió: revisa $Destino\datos\servidor.log" -ForegroundColor Red }
Stop-Transcript | Out-Null
