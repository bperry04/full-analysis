$root = Split-Path -Parent $PSScriptRoot
$data = if ($env:FA_DATA_ROOT) { $env:FA_DATA_ROOT } else { "C:\fadata" }
Set-Location $root
& "$data\venv\fa313\Scripts\python.exe" -m uvicorn fa.api.main:app --host 127.0.0.1 --port 8000
