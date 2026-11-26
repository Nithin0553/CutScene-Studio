param(
    [ValidateRange(1024,65535)][int]$Port = 8765,
    [string]$StorageRoot,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Repo

# Keep run data and caches beside the checkout rather than in the user profile.
if ([string]::IsNullOrWhiteSpace($StorageRoot)) {
    $StorageRoot = Split-Path -Parent $Repo
}
$StorageRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($StorageRoot)
$Workspace = Join-Path $StorageRoot 'runs'
$directories = @{
    PIP_CACHE_DIR = 'cache\pip'
    npm_config_cache = 'cache\npm'
    HF_HOME = 'cache\huggingface'
    UPM_CACHE_ROOT = 'cache\unity'
    TEMP = 'temp'
    TMP = 'temp'
}
foreach ($name in $directories.Keys) {
    $directory = Join-Path $StorageRoot $directories[$name]
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    [Environment]::SetEnvironmentVariable($name, $directory, 'Process')
}
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null

$Python = Join-Path $Repo '.venv-studio\Scripts\python.exe'
if (-not (Test-Path $Python -PathType Leaf)) {
    throw 'Run .\tools\install_studio.ps1 first.'
}
& $Python -B -c 'import jsonschema, pydantic, yaml, tkinter'
if ($LASTEXITCODE -ne 0) { throw 'Run .\tools\install_studio.ps1 to repair the environment.' }

Write-Host "Repository: $Repo"
Write-Host "Storage root: $StorageRoot"
Write-Host "Run workspace: $Workspace"
Write-Host "Python: $Python"
foreach ($name in ($directories.Keys | Sort-Object)) {
    Write-Host ("${name}: " + [Environment]::GetEnvironmentVariable($name, 'Process'))
}
if ($CheckOnly) {
    Write-Host 'Storage and prerequisite checks complete. Studio was not started.'
    return
}

Write-Host "Open http://127.0.0.1:$Port"
& $Python -B '.\tools\studio_local_bridge.py' --port $Port --workspace $Workspace
if ($LASTEXITCODE -ne 0) { throw "Studio stopped with exit code $LASTEXITCODE." }
