$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $projectPython) {
    & $projectPython app.py
} elseif ($env:DB_BACKEND -eq 'mysql' -and (Get-Command py -ErrorAction SilentlyContinue)) {
    & py -3 app.py
} elseif (Test-Path -LiteralPath $bundledPython) {
    & $bundledPython app.py
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 app.py
} else {
    & python app.py
}
