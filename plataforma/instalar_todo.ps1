# Deja la plataforma de inversion funcionando en este ordenador (Windows).
# Instala Git y Python si faltan, descarga el proyecto y abre el panel.
# Solo caracteres ASCII: PowerShell 5.1 lee .ps1 sin BOM como ANSI.

$ErrorActionPreference = "Stop"

function Refrescar-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User")
}

function Hay($nombre) { [bool](Get-Command $nombre -ErrorAction SilentlyContinue) }

function PythonReal {
  # Devuelve el Python de verdad. Windows incluye un python.exe FALSO en
  # WindowsApps que solo abre la Microsoft Store: hay que ignorarlo.
  foreach ($nombre in @("py", "python", "python3")) {
    $cmd = Get-Command $nombre -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps") { return $nombre }
  }
  return $null
}

Write-Host ""
Write-Host "=== Plataforma de inversion: instalacion automatica ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Hay "winget")) {
  Write-Host "Este Windows no tiene 'winget'. Instala a mano:" -ForegroundColor Yellow
  Write-Host "  Git    : https://git-scm.com/download/win"
  Write-Host "  Python : https://www.python.org/downloads/  (marca 'Add python.exe to PATH')"
  Write-Host "y vuelve a ejecutar este archivo."
  Read-Host "Pulsa Enter para salir"
  exit 1
}

if (-not (Hay "git")) {
  Write-Host "[1/4] Instalando Git..."
  winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
  Refrescar-Path
} else {
  Write-Host "[1/4] Git ya esta instalado."
}

if (-not (PythonReal)) {
  Write-Host "[2/4] Instalando Python (el python.exe de Microsoft Store no cuenta)..."
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  Refrescar-Path
} else {
  Write-Host "[2/4] Python ya esta instalado."
}

$rama = "claude/plataforma-inversion-automatica-wx1zl4"
$destino = Join-Path $HOME "MPF_CONTADORES"
if (Test-Path (Join-Path $destino "plataforma")) {
  Write-Host "[3/4] El proyecto ya existe en $destino; actualizando..."
  git -C $destino fetch origin $rama
  git -C $destino checkout $rama
  git -C $destino pull origin $rama
} else {
  Write-Host "[3/4] Descargando el proyecto a $destino ..."
  git clone -b $rama https://github.com/gusseo20-glitch/MPF_CONTADORES.git $destino
}

Set-Location (Join-Path $destino "plataforma")
$py = PythonReal
if (-not $py) {
  Write-Host "Python se ha instalado pero esta ventana aun no lo ve." -ForegroundColor Yellow
  Write-Host "Cierra esta ventana y vuelve a hacer doble clic en instalar_todo.bat."
  Read-Host "Pulsa Enter para salir"
  exit 1
}

Write-Host "[4/4] Comprobando la instalacion (unos segundos)..."
cmd /c "$py -m unittest discover -s tests -t . 2>&1" | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Las pruebas fallaron. Ejecuta esto en esta misma ventana para ver el detalle:" -ForegroundColor Yellow
  Write-Host "  $py -m unittest discover -s tests -t ."
  Read-Host "Pulsa Enter para salir"
  exit 1
}
Write-Host "Pruebas: OK" -ForegroundColor Green

Write-Host ""
Write-Host "Abriendo el panel en http://127.0.0.1:8000  (cierra esta ventana para parar)"
Write-Host "Solo escucha en este ordenador: nadie de fuera puede entrar."
& $py -m plataforma.cli web
