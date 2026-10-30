@echo off

rem AdvPrint Pro Tool - friendly control menu

rem (start / stop / status / service add+remove / auto-run /

rem  update check / uninstall)

if exist "%~dp0installer\runtime\python.exe" (

  "%~dp0installer\runtime\python.exe" "%~dp0hub\tool.py"

) else (

  python "%~dp0hub\tool.py"

)

pause

