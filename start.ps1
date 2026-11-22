param(
    [int]$Port = 8000,
    [string]$PythonPath = '',
    [switch]$Tracking
)
$ErrorActionPreference = 'Stop'
$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
if ($listeners | Where-Object { $_.Port -eq $Port -and $_.Address.ToString() -in '127.0.0.1', '0.0.0.0', '::' }) {
    throw "Le port $Port est deja utilise. Arretez le serveur Wasel dans son terminal (Ctrl+C), puis relancez cette commande."
}
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
    & $PythonPath -m uvicorn api.main:app --host 127.0.0.1 --port $Port --no-access-log
} finally { Pop-Location }
