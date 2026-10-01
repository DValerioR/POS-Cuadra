<#
Prepara una computadora de MOSTRADOR o BODEGA para usar Cuadra (el servidor
ya debe estar instalado y prendido en otra computadora de la red).

  1. Pide la IP del servidor y revisa que responda.
  2. Instala Google Chrome si falta y crea el acceso directo "Cuadra".
  3. Si esta computadora tiene la impresora de tickets por USB, instala el
     agente de impresión: Python, el agente (C:\POS-agente), la tarea que lo
     arranca al prender la computadora y el permiso del firewall solo para el
     servidor.

Uso: abrir PowerShell COMO ADMINISTRADOR y pegar (una sola línea):
    irm https://raw.githubusercontent.com/DValerioR/POS-Cuadra/master/instalador/instalar_caja.ps1 -OutFile $env:TEMP\caja.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\caja.ps1
#>
param(
    [string]$Servidor = "",
    [string]$Raw = "https://raw.githubusercontent.com/DValerioR/POS-Cuadra/master"
)

$ErrorActionPreference = "Stop"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "Abre PowerShell como administrador y vuelve a pegar la línea." -ForegroundColor Red; exit 1 }

function Winget([string]$id, [string[]]$extra = @()) {
    $argumentos = @("install", "--id", $id, "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements") + $extra
    & winget @argumentos
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) { throw "winget no pudo instalar $id (código $LASTEXITCODE). ¿Hay internet?" }
}

try {
    Write-Host "`n== Cuadra: preparar una caja o la bodega ==" -ForegroundColor Cyan

    # --- 1. Servidor -----------------------------------------------------------
    Write-Host "`n[1/3] Servidor" -ForegroundColor Cyan
    while ($true) {
        if (-not $Servidor) { $Servidor = Read-Host "    IP del servidor (la que mostró su instalador, ej. 192.168.1.50)" }
        $ipServidor = ($Servidor -replace "^https?://", "" -replace "[:/].*$", "").Trim()
        $Servidor = "http://${ipServidor}:8000"
        try {
            if ((Invoke-WebRequest -Uri "$Servidor/health" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) { break }
        } catch { }
        Write-Host "    No responde $Servidor. ¿Está prendido el servidor y es la IP correcta? ¿Esta computadora está en la misma red?" -ForegroundColor Yellow
        $Servidor = ""
    }
    Write-Host "    El servidor responde: $Servidor" -ForegroundColor Green

    # --- 2. Chrome y acceso directo ---------------------------------------------
    Write-Host "`n[2/3] Google Chrome y acceso directo" -ForegroundColor Cyan
    $chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
                "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $chrome) { Write-Host "    Instalando Google Chrome..."; Winget "Google.Chrome" @("--scope", "machine") }
    $script = Join-Path $env:TEMP "crear_acceso_directo.ps1"
    Invoke-WebRequest -Uri "$Raw/acceso_directo/crear_acceso_directo.ps1" -OutFile $script -UseBasicParsing
    & powershell -ExecutionPolicy Bypass -File $script -Servidor $Servidor

    # --- 3. Agente de impresión -------------------------------------------------
    Write-Host "`n[3/3] Impresora de tickets" -ForegroundColor Cyan
    $r = Read-Host "    ¿Esta computadora tiene la impresora de tickets conectada por USB? (S/N)"
    if ($r -notmatch "^[sS]") {
        Write-Host "    Sin agente de impresión."
    } else {
        $impresoras = @(Get-Printer | Select-Object -ExpandProperty Name)
        if (-not $impresoras.Count) { throw "Windows no tiene ninguna impresora instalada. Conecta la impresora, instala su controlador y vuelve a correr esto." }
        for ($i = 0; $i -lt $impresoras.Count; $i++) { Write-Host ("      {0}. {1}" -f ($i + 1), $impresoras[$i]) }
        do { $n = Read-Host "    Número de la impresora de tickets" } until ($n -match "^\d+$" -and [int]$n -ge 1 -and [int]$n -le $impresoras.Count)
        $impresora = $impresoras[[int]$n - 1]

        Write-Host "    En el sistema (como administrador): Configuración → Cajas e impresoras → esta caja → 'USB con agente' → 'Generar token'."
        $token = ""
        while ($token.Length -lt 16) {
            $seguro = Read-Host "    Pega aquí el token" -AsSecureString
            $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro)).Trim()
            if ($token.Length -lt 16) { Write-Host "    Ese token es muy corto; cópialo completo." -ForegroundColor Yellow }
        }

        $pythonw = @("$env:ProgramFiles\Python314\pythonw.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $pythonw) {
            Write-Host "    Instalando Python..."
            Winget "Python.Python.3.14" @("--scope", "machine")
            $pythonw = "$env:ProgramFiles\Python314\pythonw.exe"
            if (-not (Test-Path $pythonw)) { throw "No se encontró Python después de instalarlo." }
        }
        $carpeta = "C:\POS-agente"
        New-Item -ItemType Directory -Force -Path $carpeta | Out-Null
        Invoke-WebRequest -Uri "$Raw/agente_impresion/agente.py" -OutFile "$carpeta\agente.py" -UseBasicParsing

        $nombre = "Cuadra - agente de impresion"
        if (Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $nombre }
        $accion = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$carpeta\agente.py`" --impresora `"$impresora`" --token $token" -WorkingDirectory $carpeta
        $ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
        $quien = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $ajustes `
            -Principal $quien -Description "Imprime los tickets de Cuadra (lo creó el instalador)" -Force | Out-Null
        # La tarea guarda el token: solo la pueden ver los administradores.
        Start-ScheduledTask -TaskName $nombre

        Get-NetFirewallRule -DisplayName "Cuadra - agente de impresion" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName "Cuadra - agente de impresion" -Direction Inbound -Protocol TCP -LocalPort 9110 `
            -RemoteAddress $ipServidor -Action Allow | Out-Null

        $vivo = $false
        for ($i = 0; $i -lt 10; $i++) {
            try { if ((Invoke-WebRequest -Uri "http://localhost:9110/estado" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $vivo = $true; break } }
            catch { Start-Sleep -Seconds 1 }
        }
        if ($vivo) { Write-Host "    Agente de impresión funcionando con '$impresora'." -ForegroundColor Green }
        else { Write-Host "    El agente no respondió; revisa la tarea '$nombre' en el Programador de tareas." -ForegroundColor Yellow }

        $ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
            $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown"
        } | Select-Object -ExpandProperty IPAddress
        Write-Host "    Ahora, en el sistema → Cajas e impresoras → esta caja: pon la IP de esta computadora ($($ips -join ' o ')),"
        Write-Host "    guarda y usa 'Imprimir prueba' y 'Probar cajón'."
        Write-Host "    Fija la IP de esta computadora en el módem (reservación DHCP) para que no cambie." -ForegroundColor Yellow
    }

    Write-Host "`n== Listo: abre Cuadra con el acceso directo del escritorio ==" -ForegroundColor Green
} catch {
    Write-Host "`nNo se pudo terminar: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
