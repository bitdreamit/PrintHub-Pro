@echo off
REM ============================================================
REM  AdvPrint Pro - LIVE TEST (A-to-Z self-check, one click)
REM  by Bit Dream IT - Innovative Healthcare Solutions
REM  Runs the full self-test with the bundled runtime:
REM  python, data folder, token, SumatraPDF, browser, port,
REM  queue mechanics, printers. Add "print" to also send a
REM  REAL test page:  ADVPRINT-LIVETEST.bat print
REM ============================================================
title AdvPrint Pro Live Test
setlocal
set HERE=%~dp0..
set PY=
if exist "%HERE%\runtime\AdvPrintPro.exe" set PY=%HERE%\runtime\AdvPrintPro.exe
if exist "%HERE%\installer\runtime\AdvPrintPro.exe" set PY=%HERE%\installer\runtime\AdvPrintPro.exe
if not defined PY (
  for /f "delims=" %%P in ('where pythonw 2^>nul') do if not defined PY set "PY=%%P"
)
if not defined PY (
  echo [!] No bundled runtime and no system Python found.
  echo     Run install-windows.bat first.
  pause & exit /b 1
)
"%PY%" "%HERE%\hub\advprint.py" livetest %1
echo.
pause
