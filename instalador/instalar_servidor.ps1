<#
Instala el SERVIDOR de Cuadra en esta computadora (lo llama instalar.ps1,
que antes baja el programa de GitHub a C:\POS). Correr como administrador.

Pasos (cada uno se salta si ya está hecho, así que se puede volver a correr):
  1. Python 3.14 y PostgreSQL 17 (con winget).
  2. Entorno de Python con las librerías del programa.
  3. Base de datos "pos" con su usuario y el archivo .env.
  4. Datos: restaura un respaldo (.dump) o crea el negocio y su administrador.
  5. Certificado HTTPS de la red local (cámara de la tableta).
  6. El servidor como tarea de Windows que arranca sola al prender la
     computadora (puerto 8000; y 8443 con HTTPS para la tableta) y se
     vuelve a levantar si se cierra; y la tarea que instala sola las
     versiones nuevas de GitHub (con la farmacia cerrada).
  7. Firewall: abre esos puertos solo en redes privadas.
  8. Google Chrome y el acceso directo "Cuadra" en el escritorio.
Al final muestra la dirección para las demás computadoras.

Nunca borra una base que ya tenga datos. Lo que pasa queda en
C:\ProgramData\Cuadra\instalacion.log.
#>
param(
    [string]$Destino = "C:\POS",
    [string]$Respaldo = ""
)

$ErrorActionPreference = "Stop"
$Puerto = 8000
$PuertoHttps = 8443
$PuertoPostgres = 5432
$Base = "pos"
$UsuarioBase = "pos"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "Corre este instalador como administrador." -ForegroundColor Red; exit 1 }
if (-not (Test-Path (Join-Path $Destino "app\main.py"))) { Write-Host "No está el programa en $Destino." -ForegroundColor Red; exit 1 }

$carpetaLog = Join-Path $env:ProgramData "Cuadra"
New-Item -ItemType Directory -Force -Path $carpetaLog | Out-Null
Start-Transcript -Path (Join-Path $carpetaLog "instalacion.log") -Append | Out-Null

$total = 8
function Paso([int]$n, [string]$texto) { Write-Host "`n[$n/$total] $texto" -ForegroundColor Cyan }
function Bien([string]$texto) { Write-Host "    $texto" -ForegroundColor Green }
function Aviso([string]$texto) { Write-Host "    $texto" -ForegroundColor Yellow }

# Los programas externos (pip, alembic...) escriben avisos por la salida de
# errores; en PowerShell 5.1 eso no debe detener nada: cuenta su código de salida.
function Correr([string]$exe, [string[]]$argumentos, [string]$error) {
    $ErrorActionPreference = "Continue"
    & $exe @argumentos 2>&1 | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) { throw "$error (código $LASTEXITCODE)" }
}

function Clave([int]$largo = 24) {
    $letras = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    $bytes = New-Object byte[] $largo
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return -join ($bytes | ForEach-Object { $letras[$_ % $letras.Length] })
}

function Texto-Plano([Security.SecureString]$s) {
    return [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

function Escribir-Archivo([string]$ruta, [string]$contenido) {
    [IO.File]::WriteAllText($ruta, $contenido, (New-Object Text.UTF8Encoding $false))
}

function Winget([string]$id, [string[]]$extra = @()) {
    $argumentos = @("install", "--id", $id, "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements") + $extra
    & winget @argumentos
    # -1978335189 = ya estaba instalado y al día
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) { throw "winget no pudo instalar $id (código $LASTEXITCODE). ¿Hay internet?" }
}

try {
    Write-Host "`n== Cuadra: instalación del servidor en $Destino ==" -ForegroundColor Cyan

    # --- 1. Python y PostgreSQL ------------------------------------------------
    Paso 1 "Python y PostgreSQL"
    function Buscar-Python {
        foreach ($r in @("$env:ProgramFiles\Python314\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe")) {
            if (Test-Path $r) { return $r }
        }
        return $null
    }
    $python = Buscar-Python
    if (-not $python) {
        Write-Host "    Instalando Python 3.14..."
        Winget "Python.Python.3.14" @("--scope", "machine")
        $python = Buscar-Python
        if (-not $python) { throw "No se encontró Python después de instalarlo." }
    }
    Bien "Python: $python"

    function Buscar-PostgreSQL {
        $psql = Get-ChildItem "$env:ProgramFiles\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue |
            Sort-Object { [int]$_.Directory.Parent.Name } -Descending | Select-Object -First 1
        if ($psql) { return $psql.Directory.FullName }
        return $null
    }
    $pgBin = Buscar-PostgreSQL
    $clavePostgres = $null
    $archivoEnv = Join-Path $Destino ".env"
    if (-not $pgBin) {
        Write-Host "    Instalando PostgreSQL 17 (tarda unos minutos)..."
        $clavePostgres = Clave
        Winget "PostgreSQL.PostgreSQL.17" @("--override", "--mode unattended --unattendedmodeui none --superpassword $clavePostgres --serverport $PuertoPostgres")
        $pgBin = Buscar-PostgreSQL
        if (-not $pgBin) { throw "No se encontró PostgreSQL después de instalarlo." }
        # La contraseña del administrador de PostgreSQL se guarda solo para administradores de Windows.
        $datos = Join-Path $Destino "datos"
        New-Item -ItemType Directory -Force -Path $datos | Out-Null
        $archivoClave = Join-Path $datos "postgres_admin.txt"
        Escribir-Archivo $archivoClave "Usuario de PostgreSQL: postgres`r`nContraseña: $clavePostgres`r`n(Guárdala en un lugar seguro; sirve para restaurar respaldos o reinstalar.)`r`n"
        & icacls $archivoClave /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" | Out-Null
        Bien "PostgreSQL instalado. Su contraseña quedó en $archivoClave (solo administradores)."
    } else {
        Bien "PostgreSQL: $pgBin"
    }
    $servicio = Get-Service "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($servicio -and $servicio.Status -ne "Running") { Start-Service $servicio.Name }
    if ($servicio) { Set-Service $servicio.Name -StartupType Automatic }
    $psql = Join-Path $pgBin "psql.exe"

    # --- 2. Entorno de Python ----------------------------------------------------
    Paso 2 "Librerías del programa"
    $venv = Join-Path $Destino ".venv\Scripts\python.exe"
    if (-not (Test-Path $venv)) { Correr $python @("-m", "venv", (Join-Path $Destino ".venv")) "No se pudo crear el entorno de Python" }
    Correr $venv @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", (Join-Path $Destino "requirements.txt")) "No se pudieron instalar las librerías"
    Bien "Listo."

    # --- 3. Base de datos y .env -------------------------------------------------
    Paso 3 "Base de datos"
    if (Test-Path $archivoEnv) {
        Bien "Ya existe $archivoEnv : se usa la base que ahí dice."
    } else {
        if (-not $clavePostgres) {
            Aviso "PostgreSQL ya estaba instalado: escribe la contraseña de su usuario 'postgres'."
            $clavePostgres = Texto-Plano (Read-Host "    Contraseña de postgres" -AsSecureString)
        }
        $env:PGPASSWORD = $clavePostgres
        function Psql([string]$sql) {
            $r = & $psql -U postgres -h localhost -p $PuertoPostgres -d postgres -v ON_ERROR_STOP=1 -tAc $sql
            if ($LASTEXITCODE -ne 0) { throw "PostgreSQL no aceptó la orden (¿contraseña correcta?)." }
            return "$r".Trim()
        }
        $claveBase = Clave
        if ((Psql "SELECT 1 FROM pg_roles WHERE rolname = '$UsuarioBase'") -eq "1") {
            Psql "ALTER ROLE $UsuarioBase WITH LOGIN PASSWORD '$claveBase'" | Out-Null
        } else {
            Psql "CREATE ROLE $UsuarioBase WITH LOGIN PASSWORD '$claveBase'" | Out-Null
        }
        if ((Psql "SELECT 1 FROM pg_database WHERE datname = '$Base'") -ne "1") {
            Psql "CREATE DATABASE $Base OWNER $UsuarioBase ENCODING 'UTF8' TEMPLATE template0" | Out-Null
            Bien "Base '$Base' creada."
        } else {
            Bien "La base '$Base' ya existía."
        }
        Escribir-Archivo $archivoEnv (@(
            "DATABASE_URL=postgresql+psycopg://${UsuarioBase}:$claveBase@localhost:$PuertoPostgres/$Base",
            "PG_BIN=$pgBin",
            "ZONA_HORARIA=America/Mexico_City",
            ""
        ) -join "`n")
        & icacls $archivoEnv /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" | Out-Null
        Bien "Archivo .env creado (solo lo leen los administradores)."
    }
    Push-Location $Destino
    try {
        Correr $venv @("-m", "alembic", "upgrade", "head") "No se pudieron crear las tablas"
    } finally { Pop-Location }

    # --- 4. Datos ----------------------------------------------------------------
    Paso 4 "Datos"
    Push-Location $Destino
    try {
        $hay = & $venv -c "from sqlalchemy import func, select; from app.core.database import SessionLocal; from app.models import Negocio; s = SessionLocal(); print(s.scalar(select(func.count()).select_from(Negocio)))"
        if ($LASTEXITCODE -ne 0) { throw "No se pudo leer la base." }
        if ([int]"$hay".Trim() -gt 0) {
            Bien "La base ya tiene datos: no se toca."
        } else {
            if (-not $Respaldo) {
                Write-Host "    ¿Cargar un respaldo? Escribe la ruta del archivo .dump (por ejemplo, de una USB),"
                $Respaldo = Read-Host "    o deja vacío y presiona Enter para empezar con una base nueva"
                $Respaldo = $Respaldo.Trim('"', ' ')
            }
            if ($Respaldo) {
                if (-not (Test-Path $Respaldo)) { throw "No existe el archivo $Respaldo" }
                if (-not $clavePostgres) {
                    $clavePostgres = Texto-Plano (Read-Host "    Contraseña del usuario 'postgres' de PostgreSQL" -AsSecureString)
                }
                $env:PGPASSWORD = $clavePostgres
                Write-Host "    Restaurando $Respaldo ..."
                & (Join-Path $pgBin "pg_restore.exe") --no-owner --role=$UsuarioBase -h localhost -p $PuertoPostgres -U postgres -d $Base $Respaldo
                if ($LASTEXITCODE -ne 0) { Aviso "pg_restore avisó algo (código $LASTEXITCODE); se revisa abajo." }
                Correr $venv @("-m", "alembic", "upgrade", "head") "No se pudo poner al día la base restaurada"
                $hay = & $venv -c "from sqlalchemy import func, select; from app.core.database import SessionLocal; from app.models import Negocio; s = SessionLocal(); print(s.scalar(select(func.count()).select_from(Negocio)))"
                if ([int]"$hay".Trim() -lt 1) { throw "El respaldo no se cargó bien (la base sigue sin negocio)." }
                Bien "Respaldo cargado."
            } else {
                $nombre = Read-Host "    Nombre del negocio (ej. Farmacia La Fe)"
                $usuario = Read-Host "    Usuario del administrador para entrar al sistema (ej. diego)"
                $completo = Read-Host "    Nombre completo del administrador"
                Correr $venv @("-m", "app.scripts.primer_negocio", "--nombre", $nombre, "--usuario", $usuario, "--nombre-completo", $completo) "No se pudo crear el negocio"
            }
        }
    } finally { Pop-Location }
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

    # --- 5. Certificado HTTPS ----------------------------------------------------
    Paso 5 "Certificado HTTPS de la red local"
    Push-Location $Destino
    try {
        if (Test-Path (Join-Path $Destino "certificados\servidor.crt")) { Bien "Ya existe." }
        else { Correr $venv @("-m", "app.scripts.certificado_local") "No se pudo crear el certificado" }
    } finally { Pop-Location }

    # --- 6. El servidor como tarea de Windows ------------------------------------
    Paso 6 "Servidor que arranca solo al prender la computadora"
    # El servidor corre como SYSTEM; con el perfil de quien instala, los
    # respaldos encuentran sus carpetas de OneDrive / Google Drive.
    $perfil = $env:USERPROFILE
    $comun = @(
        "@echo off",
        "chcp 65001 >nul",
        "rem Lo arranca la tarea de Windows al prender la computadora (lo creó el instalador).",
        "rem Si el servidor se cierra, vuelve a arrancar a los 5 segundos.",
        "cd /d `"%~dp0`"",
        "set `"USERPROFILE=$perfil`"",
        "set `"LOCALAPPDATA=$perfil\AppData\Local`"",
        "set `"APPDATA=$perfil\AppData\Roaming`"",
        "if not exist datos mkdir datos"
    )
    Escribir-Archivo (Join-Path $Destino "iniciar_servidor.cmd") ((@($comun) + @(
        ":inicio",
        "`".venv\Scripts\python.exe`" -m uvicorn app.main:app --host 0.0.0.0 --port $Puerto >> `"datos\servidor.log`" 2>&1",
        "ping -n 6 127.0.0.1 >nul",
        "goto inicio",
        ""
    )) -join "`r`n")
    Escribir-Archivo (Join-Path $Destino "iniciar_servidor_https.cmd") ((@($comun) + @(
        "rem Solo para la tableta (la cámara necesita HTTPS). Los respaldos los hace el otro servidor.",
        "set RESPALDOS_AUTOMATICOS=false",
        ":inicio",
        "`".venv\Scripts\python.exe`" -m uvicorn app.main:app --host 0.0.0.0 --port $PuertoHttps --ssl-keyfile certificados\servidor.key --ssl-certfile certificados\servidor.crt >> `"datos\servidor_https.log`" 2>&1",
        "ping -n 6 127.0.0.1 >nul",
        "goto inicio",
        ""
    )) -join "`r`n")

    # Si ya había un servidor de Cuadra corriendo, se detiene para arrancar el nuevo.
    foreach ($t in @("Cuadra - servidor", "Cuadra - servidor HTTPS")) {
        if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $t }
    }
    # Lo que siga escuchando en los puertos del servidor (el proceso de Python).
    Get-NetTCPConnection -LocalPort $Puerto, $PuertoHttps -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    $ocupado = Get-NetTCPConnection -LocalPort $Puerto -State Listen -ErrorAction SilentlyContinue
    if ($ocupado) { throw "Otro programa usa el puerto $Puerto (proceso $($ocupado[0].OwningProcess)). Ciérralo y vuelve a correr el instalador." }

    $ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $quien = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $alPrender = New-ScheduledTaskTrigger -AtStartup
    foreach ($t in @(@("Cuadra - servidor", "iniciar_servidor.cmd"), @("Cuadra - servidor HTTPS", "iniciar_servidor_https.cmd"))) {
        $accion = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Destino\$($t[1])`"" -WorkingDirectory $Destino
        Register-ScheduledTask -TaskName $t[0] -Action $accion -Trigger $alPrender -Settings $ajustes -Principal $quien `
            -Description "Punto de venta Cuadra (lo creó el instalador)" -Force | Out-Null
        Start-ScheduledTask -TaskName $t[0]
    }
    # Actualizaciones automáticas: cada 30 minutos revisa GitHub; instala solo con la farmacia cerrada.
    $accion = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $Destino `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Destino\instalador\actualizar.ps1`" -Automatico"
    $cada30 = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(5)) -RepetitionInterval (New-TimeSpan -Minutes 30)
    $ajustesAct = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName "Cuadra - actualizar" -Action $accion -Trigger $cada30 -Settings $ajustesAct -Principal $quien `
        -Description "Instala las versiones nuevas de Cuadra desde GitHub con la farmacia cerrada (lo creó el instalador)" -Force | Out-Null
    Write-Host "    Esperando a que el servidor responda..."
    $listo = $false
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:$Puerto/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $listo = $true; break }
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $listo) { throw "El servidor no respondió. Revisa $Destino\datos\servidor.log" }
    Bien "El servidor está prendido (tareas 'Cuadra - servidor' y 'Cuadra - servidor HTTPS')."

    # --- 7. Firewall -------------------------------------------------------------
    Paso 7 "Firewall y red"
    Get-NetFirewallRule -DisplayName "Cuadra - servidor" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName "Cuadra - servidor" -Direction Inbound -Protocol TCP -LocalPort $Puerto, $PuertoHttps `
        -Profile Private, Domain -Action Allow | Out-Null
    Bien "Puertos $Puerto y $PuertoHttps abiertos para la red privada."
    $publicas = Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq "Public" }
    foreach ($red in $publicas) {
        Aviso "La red '$($red.Name)' está como PÚBLICA: las demás computadoras no podrán entrar."
        $r = Read-Host "    ¿Es la red de la farmacia y la marco como privada? (S/N)"
        if ($r -match "^[sS]") {
            Set-NetConnectionProfile -InterfaceIndex $red.InterfaceIndex -NetworkCategory Private
            Bien "Marcada como privada."
        }
    }

    # --- 8. Chrome y acceso directo -----------------------------------------------
    Paso 8 "Google Chrome y acceso directo"
    $chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $chrome) {
        Write-Host "    Instalando Google Chrome..."
        Winget "Google.Chrome" @("--scope", "machine")
    }
    & powershell -ExecutionPolicy Bypass -File (Join-Path $Destino "acceso_directo\crear_acceso_directo.ps1") -Servidor "http://localhost:$Puerto"

    # --- Resumen ------------------------------------------------------------------
    $ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown"
    } | Select-Object -ExpandProperty IPAddress
    Write-Host "`n== Listo: Cuadra quedó instalado ==" -ForegroundColor Green
    Write-Host "En esta computadora: el acceso directo 'Cuadra' del escritorio (o http://localhost:$Puerto)."
    foreach ($ip in $ips) {
        Write-Host "En las demás computadoras de la red: http://${ip}:$Puerto   (tableta: https://${ip}:$PuertoHttps/tableta)"
    }
    Write-Host "Para instalar una caja o la bodega, en esa computadora corre (PowerShell como administrador):"
    Write-Host "  irm https://raw.githubusercontent.com/DValerioR/POS-Cuadra/master/instalador/instalar_caja.ps1 -OutFile `$env:TEMP\caja.ps1; powershell -ExecutionPolicy Bypass -File `$env:TEMP\caja.ps1" -ForegroundColor White
    Aviso "Importante: fija la IP de esta computadora en el módem (reservación DHCP) para que no cambie."
    Write-Host "Las versiones nuevas se instalan solas con la farmacia cerrada (Configuración → Actualizaciones)."
} catch {
    Write-Host "`nNo se pudo terminar la instalación: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Lo que pasó quedó en $carpetaLog\instalacion.log. Corrige el problema y vuelve a correr el instalador: lo ya hecho se salta."
    Stop-Transcript | Out-Null
    exit 1
}
Stop-Transcript | Out-Null
