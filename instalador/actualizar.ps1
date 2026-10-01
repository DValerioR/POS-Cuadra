<#
Actualiza Cuadra en el SERVIDOR con la versión más nueva de GitHub.

Dos formas:
  - Automática: la tarea de Windows "Cuadra - actualizar" la corre cada 30
    minutos con -Automatico. Si hay versión nueva, solo la instala cuando la
    farmacia está cerrada (horario de Datos del negocio; sin horario, de 1 a 5
    de la mañana), o en cuanto un administrador pide "Instalar ahora" en
    Configuración → Actualizaciones.
  - A mano: doble clic en actualizar.cmd (instala en ese momento).

Pasos: respalda la base, baja la versión nueva, instala librerías, pone al
día la base (migraciones), reinicia el servidor y revisa que responda. Si
algo falla, regresa a la versión anterior (código y base) y lo avisa en la
campana. Lo que pasa queda en datos\actualizacion.json (lo muestra la
pantalla) y en C:\ProgramData\Cuadra\actualizacion.log.
#>
param(
    [string]$Destino = (Split-Path -Parent $PSScriptRoot),
    [switch]$Automatico,
    [int]$Puerto = 8000,
    [int]$PuertoHttps = 8443
)

$ErrorActionPreference = "Stop"
$Rama = "master"
$tareas = @("Cuadra - servidor", "Cuadra - servidor HTTPS")
$venv = Join-Path $Destino ".venv\Scripts\python.exe"
$git = @((Get-Command git.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source), "$env:ProgramFiles\Git\cmd\git.exe") |
    Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$datos = Join-Path $Destino "datos"
$archivoEstado = Join-Path $datos "actualizacion.json"
$bandera = Join-Path $datos "actualizar_ahora"
$candado = Join-Path $datos "actualizando.lock"
New-Item -ItemType Directory -Force -Path $datos | Out-Null

# --- Estado (lo lee la pantalla Configuración → Actualizaciones) -------------------
function Leer-Estado {
    if (Test-Path $archivoEstado) {
        try { return (Get-Content $archivoEstado -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { }
    }
    return [pscustomobject]@{}
}
function Guardar-Estado([hashtable]$cambios) {
    $e = Leer-Estado
    foreach ($k in $cambios.Keys) { $e | Add-Member -NotePropertyName $k -NotePropertyValue $cambios[$k] -Force }
    [IO.File]::WriteAllText($archivoEstado, ($e | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))
}
function Agregar-Historial([string]$de, [string]$a, [string]$resultado, [string]$mensaje) {
    $lista = @((Leer-Estado).historial | Where-Object { $_ })
    $lista = @([pscustomobject]@{ fecha = (Get-Date).ToString("o"); de = $de; a = $a; resultado = $resultado; mensaje = $mensaje }) + $lista
    Guardar-Estado @{ historial = @($lista | Select-Object -First 20) }
}
function Ahora { return (Get-Date).ToString("o") }

# git con la carpeta marcada como segura (la tarea corre como SYSTEM y la carpeta es de quien instaló).
# Los programas externos (git, pip, alembic) escriben avisos por la salida de
# errores; en PowerShell 5.1 eso no debe detener nada: cuenta su código de salida.
function Git([string[]]$argumentos) {
    $ErrorActionPreference = "Continue"
    $salida = & $git -c "safe.directory=*" -C $Destino @argumentos 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "git $($argumentos[0]) falló (código $LASTEXITCODE): $($salida -join ' ')" }
    return $salida
}
function Correr([string]$exe, [string[]]$argumentos, [string]$error) {
    Push-Location $Destino
    try {
        $ErrorActionPreference = "Continue"
        & $exe @argumentos 2>&1 | ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -ne 0) { throw "$error (código $LASTEXITCODE)" }
    } finally { Pop-Location }
}
function Revision-Base {
    Push-Location $Destino
    try {
        $ErrorActionPreference = "Continue"
        $s = & $venv -m alembic current 2>&1 | ForEach-Object { "$_" }
        $m = [regex]::Match("$s", "([0-9a-f]{12})")
        if ($m.Success) { return $m.Groups[1].Value }
        return $null
    } finally { Pop-Location }
}
function Detener-Servidor {
    foreach ($t in $tareas) { if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $t } }
    # Lo que siga escuchando en los puertos del servidor (el proceso de Python).
    Get-NetTCPConnection -LocalPort $Puerto, $PuertoHttps -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}
function Prender-Servidor {
    foreach ($t in $tareas) { if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) { Start-ScheduledTask -TaskName $t } }
    for ($i = 0; $i -lt 45; $i++) {
        try {
            if ((Invoke-WebRequest -Uri "http://localhost:$Puerto/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Seconds 2 }
    }
    return $false
}

$carpetaLog = Join-Path $env:ProgramData "Cuadra"
New-Item -ItemType Directory -Force -Path $carpetaLog | Out-Null
Start-Transcript -Path (Join-Path $carpetaLog "actualizacion.log") -Append | Out-Null

# Una sola actualización a la vez (un candado de más de una hora se considera abandonado).
if ((Test-Path $candado) -and ((Get-Date) - (Get-Item $candado).LastWriteTime).TotalMinutes -lt 60) {
    Write-Host "Ya hay una actualización en curso."
    Stop-Transcript | Out-Null
    exit 0
}

try {
    if (-not $git) { throw "No se encontró Git." }
    Set-Content -Path $candado -Value (Ahora)

    # --- ¿Hay versión nueva? -------------------------------------------------------
    Git @("fetch", "--quiet", "origin", $Rama) | Out-Null
    $actual = "$(Git @('rev-parse', 'HEAD'))".Trim()
    $nueva = "$(Git @('rev-parse', "origin/$Rama"))".Trim()
    $corta = { param($c) $c.Substring(0, 7) }
    Guardar-Estado @{ version = (& $corta $actual); ultima_revision = (Ahora); instalada = $true }
    if ($actual -eq $nueva) {
        Guardar-Estado @{ estado = "al_dia"; disponible = $null; mensaje = $null }
        Remove-Item $bandera -ErrorAction SilentlyContinue
        Write-Host "Ya está en la versión más nueva ($(& $corta $actual))."
        return
    }
    $cambios = @(Git @("log", "--format=%s", "$actual..$nueva")) | Select-Object -First 15
    Guardar-Estado @{ disponible = (& $corta $nueva); cambios = @($cambios) }

    # --- ¿Se puede instalar ahora? ---------------------------------------------------
    $forzada = Test-Path $bandera
    if ($Automatico -and -not $forzada -and (Leer-Estado).fallida -eq (& $corta $nueva)) {
        Write-Host "La versión $(& $corta $nueva) ya falló una vez; se espera otra más nueva o 'Instalar ahora'."
        return
    }
    if ($Automatico -and -not $forzada) {
        Push-Location $Destino
        try {
            $ErrorActionPreference = "Continue"
            & $venv -m app.scripts.puede_actualizar 2>&1 | Out-Null
            $puede = ($LASTEXITCODE -eq 0)
            $ErrorActionPreference = "Stop"
        } finally { Pop-Location }
        if (-not $puede) {
            Guardar-Estado @{ estado = "pendiente"; mensaje = "Se instalará sola cuando cierre la farmacia." }
            Write-Host "Hay versión nueva ($(& $corta $nueva)); se instalará cuando cierre la farmacia."
            return
        }
    }
    Remove-Item $bandera -ErrorAction SilentlyContinue
    Guardar-Estado @{ estado = "instalando"; mensaje = "Instalando la versión nueva…"; inicio = (Ahora) }
    Write-Host "Instalando de $(& $corta $actual) a $(& $corta $nueva)..."

    # --- Respaldo -----------------------------------------------------------------------
    Correr $venv @("-c", "from app.services import respaldos; r = respaldos.hacer(); print('Respaldo:', r['nombre'])") "No se pudo respaldar la base; no se instaló nada"
    $revisionAntes = Revision-Base

    # --- Instalar --------------------------------------------------------------------
    Detener-Servidor
    $error_ = $null
    try {
        Git @("reset", "--hard", "--quiet", $nueva) | Out-Null
        Correr $venv @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt") "No se pudieron instalar las librerías"
        Correr $venv @("-m", "alembic", "upgrade", "head") "No se pudo poner al día la base"
        if (-not (Prender-Servidor)) { throw "El servidor no arrancó con la versión nueva" }
    } catch {
        $error_ = $_.Exception.Message
    }

    if (-not $error_) {
        Guardar-Estado @{ estado = "ok"; version = (& $corta $nueva); disponible = $null; cambios = @(); mensaje = $null; instalada_el = (Ahora) }
        Agregar-Historial (& $corta $actual) (& $corta $nueva) "ok" ""
        Write-Host "Listo: versión $(& $corta $nueva) instalada."
        return
    }

    # --- Algo falló: regresar a la versión anterior --------------------------------------
    Write-Host "Falló: $error_. Regresando a la versión anterior..." -ForegroundColor Yellow
    Detener-Servidor
    $regreso = "Se regresó a la versión anterior."
    try {
        $revisionAhora = Revision-Base
        if ($revisionAntes -and $revisionAhora -and $revisionAhora -ne $revisionAntes) {
            Correr $venv @("-m", "alembic", "downgrade", $revisionAntes) "No se pudo regresar la base"
        }
        Git @("reset", "--hard", "--quiet", $actual) | Out-Null
        Correr $venv @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt") "No se pudieron reinstalar las librerías"
    } catch {
        $regreso = "No se pudo regresar solo ($($_.Exception.Message)); el respaldo de antes de actualizar está en Respaldos."
    }
    $prendio = Prender-Servidor
    if (-not $prendio) { $regreso += " El servidor no arrancó: revisa datos\servidor.log." }
    # No se reintenta la misma versión: hasta que llegue otra nueva o un administrador pida "Instalar ahora".
    Guardar-Estado @{ estado = "error"; version = (& $corta $actual); fallida = (& $corta $nueva); mensaje = "La actualización falló: $error_. $regreso" }
    Agregar-Historial (& $corta $actual) (& $corta $nueva) "error" "$error_. $regreso"
} catch {
    Guardar-Estado @{ estado = "error"; mensaje = "No se pudo revisar o instalar: $($_.Exception.Message)" }
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    # Si el servidor quedó apagado, se prende.
    try { Invoke-WebRequest -Uri "http://localhost:$Puerto/health" -UseBasicParsing -TimeoutSec 3 | Out-Null } catch { Prender-Servidor | Out-Null }
} finally {
    Remove-Item $candado -ErrorAction SilentlyContinue
    Stop-Transcript | Out-Null
}
