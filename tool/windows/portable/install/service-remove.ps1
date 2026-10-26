# PrintHub Pro v1.7.2 - remove the Windows service (one UAC prompt)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $root "runtime\PrintHubPro.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root "PrintHubPro.exe" }
$hub = Join-Path $root "hub\printhub.py"
Write-Host "PrintHub Pro - removing the Windows service (confirm the UAC prompt)..."
Start-Process -FilePath $py -ArgumentList ('"' + $hub + '"', "service", "remove") -Verb RunAs -Wait
$res = Join-Path $env:USERPROFILE ".printhub\service_result.txt"
if (Test-Path $res) { Get-Content $res }
Write-Host "Tip: turn the Startup app back on from the tray menu or Options > Windows service."
Pause
