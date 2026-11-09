param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonCommand = Get-Command python -ErrorAction Stop
Push-Location -LiteralPath $projectPath
try {
    & $pythonCommand.Source -m prospect ensure
    if ($LASTEXITCODE -ne 0) { throw 'Prospect failed to start' }
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:18766/' }
} finally { Pop-Location }
