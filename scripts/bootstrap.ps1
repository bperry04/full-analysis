# One-time setup: Python 3.13 venv (outside OneDrive), data root, web dependencies (node_modules junctioned outside OneDrive).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$data = if ($env:FA_DATA_ROOT) { $env:FA_DATA_ROOT } else { "C:\fadata" }
foreach ($d in @("$data", "$data\lake", "$data\raw", "$data\cache", "$data\runs", "$data\logs", "$data\tmp", "$data\venv", "$data\node_modules")) { New-Item -ItemType Directory -Force $d | Out-Null }

if (-not (Test-Path "$data\venv\fa313\Scripts\python.exe")) {
  Write-Host "creating venv (Python 3.13) at $data\venv\fa313"
  py -3.13 -m venv "$data\venv\fa313"
}
& "$data\venv\fa313\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "$data\venv\fa313\Scripts\python.exe" -m pip install -r "$root\requirements.txt" --quiet
Write-Host "python deps installed"

if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env"; Write-Host "created .env — edit FA_SEC_USER_AGENT (name + email) at minimum" }

$nm = "$root\web\node_modules"
if (-not (Test-Path $nm)) {
  New-Item -ItemType Directory -Force "$data\node_modules\fa-web" | Out-Null
  cmd /c mklink /J "$nm" "$data\node_modules\fa-web" | Out-Null
  Write-Host "junction web\node_modules -> $data\node_modules\fa-web"
}
Push-Location "$root\web"; npm install --no-audit --no-fund; Pop-Location
Write-Host "web deps installed"
Write-Host ""
Write-Host "Run:  scripts\run_api.ps1   (API + scheduler on :8000)"
Write-Host "      scripts\run_web.ps1   (UI on :5173)"
Write-Host "      $data\venv\fa313\Scripts\python.exe -m fa analyze AAPL"
