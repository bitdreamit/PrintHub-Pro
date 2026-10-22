@echo off
REM ============================================================
REM  PrintHub Pro - ONE-CLICK Windows setup  (v1.5.1)
REM  Just double-click this file. Zero questions:
REM    1. removes Mark-of-the-Web from all files
REM       (fixes "Access is denied" on downloaded zips)
REM    2. stops any OLD hub still holding port 9235
REM    3. uses the BUNDLED Python runtime (installer\runtime) -
REM       no system Python needed; system Python = fallback
REM    4. checks SumatraPDF (auto-installs it via winget)
REM    5. registers AUTO-RUN as a NORMAL STARTUP APP:
REM       "PrintHub Pro" shows in Task Manager > Startup apps
REM       (enable/disable there, or from the tray icon menu)
REM    6. starts the hub now, hidden, and health-checks it
REM    7. the hub shows a "PrintHub Pro" TRAY ICON with a menu
REM       (open status page, test page, pause, autostart, exit)
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
REM  v1.5.1: PrintHubPro.exe = pythonw.exe renamed, so Task Manager
REM  shows "PrintHubPro" instead of "python".
set PYW=
if exist "%~dp0..\installer\runtime\PrintHubPro.exe" (
  for %%I in ("%~dp0..\installer\runtime\PrintHubPro.exe") do set "PYW=%%~fI"
  echo [OK] Bundled runtime found - PrintHubPro.exe, no system Python needed
  goto pyw_ready
)
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

REM ---- 4) AUTO-RUN as a normal STARTUP APP (visible + controllable) ----
REM  v1.5.1: a shortcut named "PrintHub Pro" in the user's Startup
REM  folder - Task Manager > Startup apps lists it with our icon, and
REM  it can be enabled/disabled there (or in the tray icon menu).
REM  The hidden SCHEDULED TASK from v1.2-v1.4 is removed so the hub
REM  never starts twice.
set LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PrintHub Pro.lnk
schtasks /Delete /TN "PrintHub Pro" /F >nul 2>&1
del "%LNK%" >nul 2>&1
if defined PYW (
  for %%I in ("%~dp0..\hub\printhub.py") do set "HUBPY=%%~fI"
  for %%I in ("%~dp0..\hub\printhub.ico") do set "HUBICO=%%~fI"
  for %%I in ("%~dp0..\hub") do set "HUBDIR=%%~fI"
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut('!LNK!'); $s.TargetPath='!PYW!'; $s.Arguments=[char]34+'!HUBPY!'+[char]34+' serve'; $s.IconLocation='!HUBICO!,0'; $s.WorkingDirectory='!HUBDIR!'; $s.Description='PrintHub Pro silent print hub'; $s.Save()" >nul 2>&1
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut('!LNK!'); $s.TargetPath='wscript.exe'; $s.Arguments=[char]34+'%~dp0START-PRINT-HUB.vbs'+[char]34; $s.IconLocation='%~dp0..\hub\printhub.ico,0'; $s.Description='PrintHub Pro silent print hub'; $s.Save()" >nul 2>&1
)
if exist "%LNK%" (
  echo [OK] Auto-run registered as a Startup app named "PrintHub Pro"
  echo      Control it: Task Manager ^> Startup apps  -or-  tray icon menu
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
echo     - "PrintHub Pro" TRAY ICON near the clock: right-click
echo       it for status page / test page / pause / auto-run / exit
echo     - starts again automatically at every logon as the
echo       Startup app "PrintHub Pro" (Task Manager ^> Startup)
echo     - Chrome: chrome://extensions ^> Developer mode
echo       ^> Load unpacked ^> select the extension folder
echo     - click the PrintHub icon ^> Connect
echo    Remove auto-run anytime:  install\UNINSTALL-WINDOWS.bat
echo   ====================================================
echo.
pause
