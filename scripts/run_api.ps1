param([switch]$Reload)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Project virtual environment is missing. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.env'))) {
    throw 'Copy .env.example to .env and review local settings before starting the API.'
}
$Arguments = @('-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '8000')
if ($Reload) { $Arguments += '--reload' }
& $Python @Arguments
exit $LASTEXITCODE
