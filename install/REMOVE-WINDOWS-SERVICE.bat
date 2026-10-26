@echo off
REM  PrintHub Pro v1.7.2 - remove the Windows service. One UAC prompt.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service-remove.ps1"
