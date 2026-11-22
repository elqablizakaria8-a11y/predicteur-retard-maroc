param(
    [int]$Port = 8000,
    [string]$PythonPath = ''
)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Python introuvable. Creez .venv et installez requirements.txt selon le README, ou indiquez -PythonPath.'
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend\dist\index.html'))) {
    throw 'Interface non construite. Executez npm ci puis npm run build dans frontend.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    Write-Output "Wasel : http://127.0.0.1:$Port (Ctrl+C pour arreter)"
    & $PythonPath -m uvicorn api.main:app --host 127.0.0.1 --port $Port
} finally { Pop-Location }
