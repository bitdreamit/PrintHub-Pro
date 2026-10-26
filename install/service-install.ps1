# PrintHub Pro v1.7.1 - install the Windows service (one UAC prompt)
# Runs from install\INSTALL-WINDOWS-SERVICE.bat or directly:
#   powershell -NoProfile -ExecutionPolicy Bypass -File service-install.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # install\ -> package root
$py   = Join-Path $root "runtime\PrintHubPro.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root "PrintHubPro.exe" }
$hub = Join-Path $root "hub\printhub.py"
if (-not (Test-Path $hub)) { Write-Host "hub\printhub.py not found next to this script"; Pause; exit 1 }
Write-Host "PrintHub Pro - installing the Windows service (confirm the UAC prompt)..."
Start-Process -FilePath $py -ArgumentList ('"' + $hub + '"', "service", "install") -Verb RunAs -Wait
$res = Join-Path $env:USERPROFILE ".printhub\service_result.txt"
if (Test-Path $res) { Get-Content $res }
Write-Host ""
Write-Host "Check: services.msc -> 'PrintHub Pro Service' (or: python printhub.py service status)"
Pause
