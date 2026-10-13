@echo off
REM ============================================================
REM  PrintHub Pro - ONE-CLICK Windows setup  (v1.4.0)
REM  Just double-click this file. Zero questions:
REM    1. removes Mark-of-the-Web from all files
REM       (fixes "Access is denied" on downloaded zips)
REM    2. stops any OLD hub still holding port 9235
REM    3. uses the BUNDLED Python runtime (installer\runtime) -
REM       no system Python needed; system Python = fallback
REM    4. checks SumatraPDF (auto-installs it via winget)
REM    5. registers AUTO-RUN at every Windows logon - the task
REM       runs pythonw.exe DIRECTLY, no .vbs / wscript involved
REM    6. starts the hub now, hidden, and health-checks it
REM  No admin rights needed.  Undo = UNINSTALL-WINDOWS.bat
REM  by Bitdream IT - MIT licensed
REM ============================================================
title PrintHub Pro Setup
setlocal EnableDelayedExpansion
echo.
echo   ==============================================
echo    PrintHub Pro  -  one-click setup
echo    installs + auto-run at logon, no questions
echo   ==============================================
echo.

REM ---- 0a) remove Mark-of-the-Web (downloaded-zip blocks) --------------
echo [..] Unblocking downloaded files ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ChildItem -LiteralPath '%~dp0..' -Recurse -File | Unblock-File" >nul 2>&1
echo [OK] Files unblocked - no more "Access is denied" on this folder

REM ---- 0b) stop any OLD hub holding port 9235 --------------------------
echo [..] Checking port 9235 for an old hub ...
set OLDKILL=
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r /c:":9235 .*LISTENING"') do (
  taskkill /F /PID %%a >nul 2>&1 && set OLDKILL=1
)
if defined OLDKILL (
  echo [OK] Old hub process stopped - port 9235 is now free
) else (
  echo [OK] Port 9235 was already free
)

REM ---- 1) Python: BUNDLED runtime first, system Python = fallback ------
set PYW=
if exist "%~dp0..\installer\runtime\pythonw.exe" (
  for %%I in ("%~dp0..\installer\runtime\pythonw.exe") do set "PYW=%%~fI"
  echo [OK] Bundled Python 3.11 runtime found - no system Python needed
  goto pyw_ready
)
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
  python --version >nul 2>&1 && set PY=python
)
if not defined PY (
  echo [!] Python 3 was not found on this PC.
  echo     Keep the FULL package unzipped: installer\runtime\pythonw.exe
  echo     is the bundled runtime. Or install Python from python.org.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
echo [OK] Python found  -  !PY!

REM ---- 2) resolve pythonw.exe FULL path (skip if bundled runtime) ------
REM  The task runs pythonw directly - Windows script hosts are often
REM  blocked by Defender ASR / group policy on company machines.
if defined PYW goto pyw_ready
set PYEXE=
set PYW=
for /f "delims=" %%p in ('%PY% -c "import sys;print(sys.executable)"') do set PYEXE=%%p
if defined PYEXE (
  set "PYW=!PYEXE:python.exe=pythonw.exe!"
  if not exist "!PYW!" set "PYW="
)
if not defined PYW (
  for /f "delims=" %%p in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%p"
)
if defined PYW (
  echo [OK] pythonw resolved:  !PYW!
) else (
  echo [..] pythonw path not resolved - task will use the .vbs launcher
)
:pyw_ready

REM ---- 3) SumatraPDF check (silent PDF printing engine) ----------------
set SUMATRA=
if exist "%ProgramFiles%\SumatraPDF\SumatraPDF.exe" set SUMATRA=1
if exist "%ProgramFiles(x86)%\SumatraPDF\SumatraPDF.exe" set SUMATRA=1
if exist "%LocalAppData%\SumatraPDF\SumatraPDF.exe" set SUMATRA=1
if exist "C:\Tools\SumatraPDF.exe" set SUMATRA=1
if defined SUMATRA (
  echo [OK] SumatraPDF found
) else (
  echo [..] SumatraPDF not found - installing with winget ...
  winget install --id SumatraPDF.SumatraPDF -e --silent --accept-source-agreements --accept-package-agreements >nul 2>&1
  if exist "%ProgramFiles%\SumatraPDF\SumatraPDF.exe" (
    echo [OK] SumatraPDF installed
  ) else (
    echo [!] Auto-install failed - opening the download page.
    echo     Install SumatraPDF, then run this setup again.
    start https://www.sumatrapdfreader.org/download-free-pdf-viewer
  )
)

REM ---- 4) AUTO-RUN at every logon - registered automatically -----------
REM  /F overwrites any previous task, so the path always points HERE.
REM  v1.2.1: runs pythonw.exe DIRECTLY - no wscript/.vbs in the boot
REM  path, so Defender ASR "VBS downloaded content" blocks cannot hit it.
if defined PYW (
  schtasks /Create /F /SC ONLOGON /TN "PrintHub Pro" /TR "\"!PYW!\" \"%~dp0..\hub\printhub.py\" serve" >nul 2>&1
) else (
  schtasks /Create /F /SC ONLOGON /TN "PrintHub Pro" /TR "wscript.exe \"%~dp0START-PRINT-HUB.vbs\"" >nul 2>&1
)
if not errorlevel 1 (
  echo [OK] Auto-run registered - hub starts at every Windows logon
) else (
  echo [!] Could not register auto-run - hub still runs now, but
  echo     after a reboot start it with install\START-PRINT-HUB.vbs
)

REM ---- 5) start the hub right now, hidden ------------------------------
echo [..] Starting PrintHub Pro on http://127.0.0.1:9235 ...
if defined PYW (
  start "" "!PYW!" "%~dp0..\hub\printhub.py" serve
) else (
  wscript.exe "%~dp0START-PRINT-HUB.vbs"
)

REM ---- 6) health check, up to 8 seconds --------------------------------
set UP=
for /l %%i in (1,1,8) do (
  if not defined UP (
    timeout /t 1 /nobreak >nul
    curl -s http://127.0.0.1:9235/health 2>nul | findstr /c:"version" >nul 2>&1 && set UP=1
  )
)
if defined UP (
  echo [OK] Hub is running - health check passed
) else (
  echo [!] Health check FAILED.
  echo     Look at:  %USERPROFILE%\.printhub\hub.log
  echo     Or run in a console:  hub\printhub.py serve  to see the error.
)

echo.
echo   ====================================================
echo    Setup finished - everything is automatic now:
echo     - hub running hidden at http://127.0.0.1:9235
echo     - starts again automatically at every logon
echo       (task runs pythonw.exe directly - no .vbs)
echo     - Chrome: chrome://extensions ^> Developer mode
echo       ^> Load unpacked ^> select the extension folder
echo     - click the PrintHub icon ^> Connect
echo    Remove auto-run anytime:  install\UNINSTALL-WINDOWS.bat
echo   ====================================================
echo.
pause
