@echo off
REM ============================================================
REM  PrintHub Pro - Windows uninstall  (v1.2.0)
REM  Removes the logon auto-run task and stops the hub.
REM  Does NOT delete your print data or the Chrome extension.
REM ============================================================
title PrintHub Pro Uninstall
echo.
echo [..] Removing logon task "PrintHub Pro" ...
schtasks /Delete /TN "PrintHub Pro" /F >nul 2>&1
if not errorlevel 1 (
  echo [OK] Logon task removed
) else (
  echo [..] No logon task found - nothing to remove
)

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
