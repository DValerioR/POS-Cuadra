<#
Crea en el escritorio el acceso directo "Cuadra", que abre el punto de venta
en Chrome como aplicación (sin barra de direcciones ni pestañas) y con el
ícono de Cuadra.

Uso (en PowerShell, en la computadora donde se quiere el acceso directo):
    powershell -ExecutionPolicy Bypass -File crear_acceso_directo.ps1 -Servidor http://192.168.1.50:8000

El ícono se descarga del servidor (/favicon.ico) y se guarda en
%LOCALAPPDATA%\Cuadra, así que el servidor debe estar prendido.
Se puede volver a correr: reemplaza el acceso directo anterior.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Servidor,
    [string]$Nombre = "Cuadra"
)

$ErrorActionPreference = "Stop"
$Servidor = $Servidor.TrimEnd("/")
if ($Servidor -notmatch "^https?://") { $Servidor = "http://$Servidor" }

# Chrome: en Archivos de programa (todos los usuarios) o en el perfil del usuario.
$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $chrome) { throw "No se encontró Google Chrome. Instálalo y vuelve a correr este script." }

# Ícono, descargado del servidor.
$carpeta = Join-Path $env:LOCALAPPDATA "Cuadra"
New-Item -ItemType Directory -Force -Path $carpeta | Out-Null
$icono = Join-Path $carpeta "cuadra.ico"
try {
    Invoke-WebRequest -Uri "$Servidor/favicon.ico" -OutFile $icono -UseBasicParsing
} catch {
    throw "No se pudo descargar el ícono de $Servidor. ¿El servidor está prendido y la dirección es correcta?"
}

# Acceso directo en el escritorio.
$escritorio = [Environment]::GetFolderPath("Desktop")
$ruta = Join-Path $escritorio "$Nombre.lnk"
$shell = New-Object -ComObject WScript.Shell
$acceso = $shell.CreateShortcut($ruta)
$acceso.TargetPath = $chrome
$acceso.Arguments = "--app=$Servidor/"
$acceso.IconLocation = "$icono,0"
$acceso.WorkingDirectory = Split-Path $chrome
$acceso.Description = "Punto de venta Cuadra"
$acceso.Save()

Write-Host "Listo: acceso directo '$Nombre' en el escritorio, abre $Servidor/"
