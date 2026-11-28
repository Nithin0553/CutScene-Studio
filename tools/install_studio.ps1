param([string]$Python = 'python', [switch]$Dev, [switch]$Agent, [string]$StorageRoot)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Repo
# Configure storage before venv creation or pip, not just at server launch.
if ([string]::IsNullOrWhiteSpace($StorageRoot)) {
    $StorageRoot = Split-Path -Parent $Repo
}
$StorageRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($StorageRoot)
$directories = @{ PIP_CACHE_DIR = 'cache\pip'; TEMP = 'temp'; TMP = 'temp' }
foreach ($name in $directories.Keys) {
    $directory = Join-Path $StorageRoot $directories[$name]
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    [Environment]::SetEnvironmentVariable($name, $directory, 'Process')
}
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
if ($Agent -or $Dev) {
    & $Exe -m pip install 'langgraph>=1,<2'
    if ($LASTEXITCODE -ne 0) { throw 'AI agent dependency installation failed.' }
    & $Exe -c 'import langgraph.graph, langsmith'
    if ($LASTEXITCODE -ne 0) { throw 'AI agent dependencies are missing.' }
}
if ($Dev) {
    & $Exe -m pip install 'pytest>=8,<9' 'ruff>=0.7'
    if ($LASTEXITCODE -ne 0) { throw 'Test tool installation failed.' }
}
& $Exe -c 'import jsonschema, pydantic, yaml, tkinter'
if ($LASTEXITCODE -ne 0) { throw 'Studio prerequisites are missing; check Python and Tkinter installation.' }
Write-Host 'Setup complete. Run .\tools\start_studio.ps1'
