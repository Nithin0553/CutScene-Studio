param([string]$Python = 'python', [switch]$Dev)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Repo
& $Python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer and rerun setup.' }
$Venv = Join-Path $Repo '.venv-studio'
$Exe = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $Exe -PathType Leaf)) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Studio environment.' }
}
& $Exe -m pip install 'jsonschema>=4.23,<5' 'pydantic>=2.8,<3' 'pyyaml>=6,<7'
if ($LASTEXITCODE -ne 0) { throw 'Studio dependency installation failed.' }
if ($Dev) {
    & $Exe -m pip install 'pytest>=8,<9' 'ruff>=0.7'
    if ($LASTEXITCODE -ne 0) { throw 'Test tool installation failed.' }
}
& $Exe -c 'import jsonschema, pydantic, yaml, tkinter'
if ($LASTEXITCODE -ne 0) { throw 'Studio prerequisites are missing; check Python and Tkinter installation.' }
Write-Host 'Setup complete. Run .\tools\start_studio.ps1'
