' PrintHub Pro - hidden launcher, no console window  (v1.2.1)
' MANUAL / FALLBACK launcher only: since v1.2.1 the "PrintHub Pro"
' logon task runs pythonw.exe DIRECTLY (wscript/.vbs is blocked by
' Defender ASR on many company machines). Double-click this file
' only when the scheduled task could not be created.
' Hub log: %UserProfile%\.printhub\hub.log

Option Explicit
Dim sh, fso, base, hub, logdir, ts
Dim py, candidates, v, wout, wline

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
hub  = base & "\hub\printhub.py"

' ---- 1) resolve pythonw.exe -------------------------------------------
py = ""

' 1a) whatever is on PATH (where.exe, first hit wins)
On Error Resume Next
If fso.FileExists(sh.ExpandEnvironmentStrings("%SystemRoot%\System32\where.exe")) Then
  Set wout = sh.Exec("%ComSpec% /c where pythonw.exe 2>nul")
  Do While Not wout.StdOut.AtEndOfStream
    wline = Trim(wout.StdOut.ReadLine())
    If py = "" And wline <> "" And fso.FileExists(wline) Then py = wline
  Loop
End If
On Error GoTo 0

' 1b) per-user installs - the case most installers miss
'     %LocalAppData%\Programs\Python\Python31x\pythonw.exe
' 1c) all-users installs - C:\Program Files\Python31x\pythonw.exe
If py = "" Then
  candidates = Array( _
    sh.ExpandEnvironmentStrings("%LocalAppData%\Programs\Python"), _
    "C:\Program Files\" )
  Dim roots, root, vers
  vers = Array("314","313","312","311","310")
  For Each root In candidates
    For Each v In vers
      If fso.FileExists(root & "\Python" & v & "\pythonw.exe") Then
        py = root & "\Python" & v & "\pythonw.exe"
        Exit For
      End If
    Next
    If py <> "" Then Exit For
  Next
End If

' 1d) py launcher (all-users default) then bare PATH fallback
If py = "" And fso.FileExists("C:\Windows\pyw.exe") Then py = "C:\Windows\pyw.exe"
If py = "" Then py = "pythonw.exe"

' ---- 2) boot log - makes "why is nothing printing" answerable ---------
logdir = sh.ExpandEnvironmentStrings("%LocalAppData%\PrintHubPro")
On Error Resume Next
If Not fso.FolderExists(logdir) Then fso.CreateFolder(logdir)
Set ts = fso.OpenTextFile(logdir & "\boot.log", 8, True)
ts.WriteLine Now & "  start  python=""" & py & """  hub=""" & hub & """"
ts.Close
On Error GoTo 0

' ---- 3) launch hidden --------------------------------------------------
sh.CurrentDirectory = base & "\hub"
sh.Run """" & py & """ """ & hub & """ serve", 0, False
