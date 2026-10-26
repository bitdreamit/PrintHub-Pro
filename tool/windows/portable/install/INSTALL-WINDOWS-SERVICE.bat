@echo off
REM  PrintHub Pro v1.7.2 - install as a Windows service ("PrintHub Pro Service"
REM  in services.msc, starts at boot, auto-restarts). One UAC prompt.
REM  Installed layout: <root>\install\*.bat, <root>\runtime\PrintHubPro.exe,
REM  <root>\hub\printhub.py
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service-install.ps1"
