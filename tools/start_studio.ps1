param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Repo
$Python = Join-Path $Repo '.venv-studio\Scripts\python.exe'
if (-not (Test-Path $Python -PathType Leaf)) {
    throw 'Run .\tools\install_studio.ps1 first.'
}
& $Python -c 'import jsonschema, pydantic, yaml, tkinter'
if ($LASTEXITCODE -ne 0) { throw 'Run .\tools\install_studio.ps1 to repair the environment.' }
Write-Host "Open http://127.0.0.1:$Port"
& $Python -B '.\tools\studio_local_bridge.py' --port $Port
if ($LASTEXITCODE -ne 0) { throw "Studio stopped with exit code $LASTEXITCODE." }
