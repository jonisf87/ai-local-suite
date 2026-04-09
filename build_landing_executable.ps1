$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$pythonCmd = $env:PYTHON_BIN
if ([string]::IsNullOrWhiteSpace($pythonCmd)) {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = 'py'
  }
  elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = 'python'
  }
  else {
    throw "No se encontró Python en PATH. Define PYTHON_BIN antes de ejecutar."
  }
}

$baseArgs = @()
if ($pythonCmd -eq 'py') {
  $baseArgs = @('-3')
}

Write-Host "[INFO] Usando Python: $pythonCmd $($baseArgs -join ' ')"

& $pythonCmd @baseArgs -m pip install --upgrade pip
& $pythonCmd @baseArgs -m pip install pyinstaller -r requirements.txt

& $pythonCmd @baseArgs -m PyInstaller `
  --noconfirm `
  --clean `
  --name landing-manager `
  --add-data "static;static" `
  landing_manager.py

Write-Host "[OK] EXE generado en: $ScriptDir\dist\landing-manager\landing-manager.exe"
