@echo off
REM ============================================================
REM  PrintHub Pro - Windows uninstall  (v1.5.0)
REM  Removes the Startup-app shortcut (and the legacy logon task
REM  from v1.2-v1.4) and stops the hub.
REM  Does NOT delete your print data or the Chrome extension.
REM ============================================================
title PrintHub Pro Uninstall
echo.
echo [..] Removing Startup shortcut "PrintHub Pro" ...
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PrintHub Pro.lnk" >nul 2>&1
if not exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PrintHub Pro.lnk" (
  echo [OK] Startup shortcut removed - no more auto-run at logon
) else (
  echo [!] Could not remove the Startup shortcut - delete it manually:
  echo     %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
)
echo [..] Removing legacy logon task "PrintHub Pro" (v1.2-v1.4) ...
schtasks /Delete /TN "PrintHub Pro" /F >nul 2>&1
echo [OK] Done

echo [..] Stopping any hub on port 9235 ...
set KILLED=
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r /c:":9235 .*LISTENING"') do (
  taskkill /F /PID %%a >nul 2>&1 && set KILLED=1
)
if defined KILLED (
  echo [OK] Hub stopped
) else (
  echo [OK] Hub was not running
)

echo.
echo [OK] PrintHub Pro uninstalled.
echo      Print data kept in:  %USERPROFILE%\.printhub
echo      Delete it manually if you want:
echo        rmdir /s /q "%USERPROFILE%\.printhub"
echo      Remove the Chrome extension in chrome://extensions
echo.
pause
