<#
Primer paso de la instalación del SERVIDOR de Cuadra en una computadora nueva.

Instala Git (si falta), baja el programa de GitHub a C:\POS y sigue con
instalador\instalar_servidor.ps1, que hace todo lo demás.

Uso: abrir PowerShell COMO ADMINISTRADOR y pegar (una sola línea):
    irm https://raw.githubusercontent.com/DValerioR/POS-Cuadra/master/instalador/instalar.ps1 -OutFile $env:TEMP\instalar.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\instalar.ps1

Si C:\POS ya tiene el programa, solo lo actualiza (git pull) y vuelve a
correr la instalación, que no borra nada de lo que ya exista.
#>
param(
    [string]$Destino = "C:\POS",
    [string]$Repositorio = "https://github.com/DValerioR/POS-Cuadra.git"
)

$ErrorActionPreference = "Stop"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Abre PowerShell como administrador (clic derecho → Ejecutar como administrador) y vuelve a pegar la línea." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "Falta winget (Instalador de aplicaciones). Instálalo desde la Microsoft Store ('Instalador de aplicación') y vuelve a intentar." -ForegroundColor Red
    exit 1
}

function Buscar-Git {
    $g = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($g) { return $g.Source }
    foreach ($r in @("$env:ProgramFiles\Git\cmd\git.exe", "${env:ProgramFiles(x86)}\Git\cmd\git.exe")) {
        if (Test-Path $r) { return $r }
    }
    return $null
}

Write-Host "`n== Cuadra: instalación del servidor ==" -ForegroundColor Cyan
$git = Buscar-Git
if (-not $git) {
    Write-Host "Instalando Git..."
    winget install --id Git.Git -e --scope machine --silent --accept-package-agreements --accept-source-agreements
    $git = Buscar-Git
    if (-not $git) { throw "No se pudo instalar Git." }
}

if (Test-Path (Join-Path $Destino ".git")) {
    Write-Host "El programa ya está en $Destino; se actualiza..."
    & $git -C $Destino pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "No se pudo actualizar el programa con git pull." }
} elseif ((Test-Path $Destino) -and (Get-ChildItem $Destino -Force | Select-Object -First 1)) {
    throw "La carpeta $Destino ya existe y no es una copia de GitHub. Muévela o bórrala y vuelve a intentar."
} else {
    Write-Host "Bajando el programa de GitHub a $Destino..."
    & $git clone $Repositorio $Destino
    if ($LASTEXITCODE -ne 0) { throw "No se pudo bajar el programa de GitHub. ¿Hay internet?" }
}

& powershell -ExecutionPolicy Bypass -File (Join-Path $Destino "instalador\instalar_servidor.ps1") -Destino $Destino
exit $LASTEXITCODE
