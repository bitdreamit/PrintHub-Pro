; ============================================================
;  PrintHub Pro - Windows one-time installer (NSIS)
;  - per-user install to %LOCALAPPDATA%\PrintHubPro (no admin)
;  - STANDALONE: ships a bundled Python 3.11 runtime
;    (%LOCALAPPDATA%\PrintHubPro\runtime) - no system Python
;    is ever needed; registry/py detection is only a fallback
;  - the runtime ships PrintHubPro.exe (= pythonw.exe renamed):
;    Task Manager shows "PrintHubPro", never "python"
;  - registers auto-run as a NORMAL STARTUP APP
;    ($SMSTARTUP\PrintHub Pro.lnk) - visible and toggleable in
;    Task Manager > Startup apps (scheduled task removed: was
;    invisible there - the hub looked uninstallable)
;  - starts the hub, creates Start Menu shortcuts
;  - the hub shows a "PrintHub Pro" tray icon with a menu
;  - real uninstaller with Add/Remove Programs entry
;  built with makensis 3.11 on Linux (Bitdream IT)
; ============================================================

Unicode true
Name "PrintHub Pro"
OutFile "/home/z/my-project/build/PrintHubPro/installer/PrintHub-Pro-Setup-1.5.0.exe"
InstallDir "$LOCALAPPDATA\PrintHubPro"
InstallDirRegKey HKCU "Software\PrintHubPro" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUnInstDetails show

VIProductVersion "1.5.0.0"
VIAddVersionKey ProductName "PrintHub Pro"
VIAddVersionKey FileVersion "1.5.0"
VIAddVersionKey ProductVersion "1.5.0"
VIAddVersionKey CompanyName "Bitdream IT"
VIAddVersionKey LegalCopyright "MIT License"
VIAddVersionKey FileDescription "PrintHub Pro - silent print bridge (one-time setup)"

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ICON   "/home/z/my-project/build/PrintHubPro/installer.ico"
!define MUI_UNICON "/home/z/my-project/build/PrintHubPro/installer.ico"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "/home/z/my-project/build/PrintHubPro/LICENSE"
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchHub"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.md"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function LaunchHub
  ReadRegStr $R0 HKCU "Software\PrintHubPro" "PythonW"
  ${If} $R0 != ""
    Exec '"$R0" "$INSTDIR\hub\printhub.py" serve'
    DetailPrint "Hub starting on http://127.0.0.1:9235"
  ${EndIf}
FunctionEnd

; ------------------------------------------------------------
; Find pythonw.exe -> $R0 (empty when not found)
; 0) bundled runtime $INSTDIR\runtime\pythonw.exe (always used)
; 1) PEP 514 registry: enumerate Software\Python\PythonCore\* in
;    HKLM/HKCU under BOTH registry views (tags are bare "3.10"
;    for 64-bit, "3.10-32" for 32-bit - earlier suffix-only scan
;    missed per-user python.org installs)
; 2) py -3 launcher -> sys.executable
; ------------------------------------------------------------
!macro TryHive ROOT VIEW
  StrCpy $R4 0
LoopEnum_${ROOT}_${VIEW}:
  ClearErrors
  EnumRegKey $R1 ${ROOT} "Software\Python\PythonCore" $R4
  ${If} ${Errors}
    Goto Done_${ROOT}_${VIEW}
  ${EndIf}
  IntOp $R4 $R4 + 1
  StrCpy $R5 "$R1" 2
  ${If} $R5 != "3."
    Goto LoopEnum_${ROOT}_${VIEW}
  ${EndIf}
  ClearErrors
  ReadRegStr $R2 ${ROOT} "Software\Python\PythonCore\$R1\InstallPath" "ExecutablePath"
  ${IfNot} ${Errors}
    ${GetParent} $R2 $R3
    StrCpy $R3 "$R3\pythonw.exe"
    Goto Found
  ${EndIf}
  ClearErrors
  ReadRegStr $R3 ${ROOT} "Software\Python\PythonCore\$R1\InstallPath" ""
  ${IfNot} ${Errors}
    StrCpy $R3 "$R3pythonw.exe"
    Goto Found
  ${EndIf}
  Goto LoopEnum_${ROOT}_${VIEW}
 Done_${ROOT}_${VIEW}:
!macroend

Function FindPythonW
  StrCpy $R0 ""
  ; 0) bundled Python runtime - the normal path, zero dependencies
  ;    PrintHubPro.exe preferred: process name = PrintHubPro, not python
  ${If} ${FileExists} "$INSTDIR\runtime\PrintHubPro.exe"
    StrCpy $R0 "$INSTDIR\runtime\PrintHubPro.exe"
    Goto Found
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\runtime\pythonw.exe"
    StrCpy $R0 "$INSTDIR\runtime\pythonw.exe"
    Goto Found
  ${EndIf}
  ; 1) PEP 514 registry, both views (emergency fallback only)
  SetRegView 64
  !insertmacro TryHive HKLM 64
  !insertmacro TryHive HKCU 64
  SetRegView 32
  !insertmacro TryHive HKLM 32
  !insertmacro TryHive HKCU 32
  SetRegView lastused
  ; 2) py launcher (last resort)
  nsExec::ExecToStack 'py -3 -c "import sys;print(sys.executable)"'
  Pop $R2
  Pop $R3
  ${If} $R2 == "0"
    ${GetParent} $R3 $R2
    StrCpy $R2 "$R2\pythonw.exe"
    ${If} ${FileExists} "$R2"
      StrCpy $R0 $R2
    ${Else}
      StrCpy $R0 $R3
    ${EndIf}
  ${EndIf}
 Found:
FunctionEnd

Section "PrintHub Pro (required)" SEC_MAIN
  SectionIn RO
  DetailPrint "Copying files..."
  SetOutPath "$INSTDIR\hub"
  File "/home/z/my-project/build/PrintHubPro/hub/printhub.py"
  File "/oname=printhub.ico" "/home/z/my-project/build/PrintHubPro/hub/printhub.ico"
  SetOutPath "$INSTDIR\install"
  File "/oname=START-PRINT-HUB.vbs" "/home/z/my-project/build/PrintHubPro/install/START-PRINT-HUB.vbs"
  SetOutPath "$INSTDIR"
  File "/oname=README.md" "/home/z/my-project/build/PrintHubPro/README.md"
  File "/oname=LICENSE" "/home/z/my-project/build/PrintHubPro/LICENSE"
  File "/oname=printhub.ico" "/home/z/my-project/build/PrintHubPro/installer.ico"

  DetailPrint "Installing bundled Python 3.11 runtime (standalone - no system Python needed)..."
  SetOutPath "$INSTDIR\runtime"
  File /r "/home/z/my-project/build/PrintHubPro/installer/runtime\*.*"

  DetailPrint "Resolving the bundled launcher..."
  Call FindPythonW
  WriteRegStr HKCU "Software\PrintHubPro" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\PrintHubPro" "PythonW" "$R0"

  ; ---- SumatraPDF info (not fatal) ----
  ${If} ${FileExists} "$PROGRAMFILES\SumatraPDF\SumatraPDF.exe"
    DetailPrint "SumatraPDF found."
  ${ElseIf} ${FileExists} "$LOCALAPPDATA\SumatraPDF\SumatraPDF.exe"
    DetailPrint "SumatraPDF found."
  ${Else}
    DetailPrint "SumatraPDF missing - install it later for silent PDF printing."
  ${EndIf}

  ; ---- auto-run as a normal STARTUP APP (visible + controllable) ----
  ;  v1.5.0: Startup-folder shortcut instead of a scheduled task -
  ;  Task Manager > Startup apps now lists "PrintHub Pro" with our
  ;  icon and the user can enable/disable it there (or in the tray).
  ;  The hidden scheduled task from v1.2-v1.4 is removed (legacy).
  DetailPrint "Registering auto-run as a Startup app..."
  nsExec::Exec 'schtasks /Delete /TN $\"PrintHub Pro$\" /F'
  Pop $R9
  SetShellVarContext current   ; $SMSTARTUP = THIS user's Startup folder (no admin)
  ${If} $R0 != ""
    CreateShortcut "$SMSTARTUP\PrintHub Pro.lnk" "$R0" \
      '"$INSTDIR\hub\printhub.py" serve' "$INSTDIR\printhub.ico" 0
    ${If} ${FileExists} "$SMSTARTUP\PrintHub Pro.lnk"
      DetailPrint "Auto-run registered: Startup app 'PrintHub Pro' (Task Manager > Startup apps)."
    ${Else}
      DetailPrint "Auto-run shortcut could not be created - start manually via Start Menu."
    ${EndIf}
  ${Else}
    DetailPrint "No usable pythonw.exe (bundled runtime missing + no system Python)."
    MessageBox MB_ICONEXCLAMATION|MB_OK \
      "Setup could not prepare the bundled Python runtime and found no system Python.$\n$\nPlease re-download PrintHub-Pro-Setup-1.5.0.exe (file may be damaged), or install Python from python.org (tick 'Add python.exe to PATH') and run this setup again."
    ExecShell "open" "https://www.python.org/downloads/"
  ${EndIf}

  ; ---- shortcuts + uninstaller ----
  DetailPrint "Creating shortcuts..."
  SetShellVarContext current
  CreateDirectory "$SMPROGRAMS\PrintHub Pro"
  ${If} $R0 != ""
    CreateShortcut "$SMPROGRAMS\PrintHub Pro\Start PrintHub Pro.lnk" "$R0" \
      '"$INSTDIR\hub\printhub.py" serve' "$INSTDIR\printhub.ico" 0
  ${EndIf}
  CreateShortcut "$SMPROGRAMS\PrintHub Pro\Uninstall PrintHub Pro.lnk" "$INSTDIR\uninstall.exe"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintHubPro" \
    "DisplayName" "PrintHub Pro (silent print bridge)"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintHubPro" \
    "DisplayVersion" "1.5.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintHubPro" \
    "Publisher" "Bitdream IT"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintHubPro" \
    "DisplayIcon" "$INSTDIR\printhub.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintHubPro" \
    "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintHubPro" \
    "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintHubPro" \
    "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  DetailPrint "Stopping hub and removing auto-run..."
  Delete "$SMSTARTUP\PrintHub Pro.lnk"
  nsExec::Exec 'schtasks /Delete /TN $\"PrintHub Pro$\" /F'
  nsExec::Exec 'powershell -NoProfile -Command $\"Get-NetTCPConnection -LocalPort 9235 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $$_ -Force -ErrorAction SilentlyContinue }$\"'
  Delete "$SMPROGRAMS\PrintHub Pro\*.lnk"
  RMDir "$SMPROGRAMS\PrintHub Pro"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintHubPro"
  DeleteRegKey HKCU "Software\PrintHubPro"
  RMDir /r "$INSTDIR"
  MessageBox MB_ICONINFORMATION|MB_OK \
    "PrintHub Pro uninstalled.$\n$\nYour print history in %USERPROFILE%\.printhub was kept.$\nDelete that folder manually if you do not want it."
SectionEnd
