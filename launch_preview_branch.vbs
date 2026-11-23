' Rendered from [tool.haglio.launchers."launch_preview_branch.vbs"] in pyproject.toml.
' Change the spec, then run  python -m app_support.launcher --write  in this
' folder: the suite fails on a launcher that differs from its spec.

Option Explicit

Dim fso, shell, root, app, interpreter, directory, arguments, base, updater, gates, held(), rebases, primary, logPath, screenFolder, screenUp, picturesFolder

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
Decide
If shell.Environment("Process").Item("HAGLIO_LAUNCHER_DRY_RUN") = "1" Then
  Report
Else
  Launch
End If

Sub Decide()
  app = "Broker (branch preview)"
  primary = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(root)))
  logPath = fso.BuildPath(root, "state\preview_branch.log")
  screenFolder = fso.BuildPath(root, "state\preview_branch.screen")
  picturesFolder = fso.BuildPath(primary, "state\preview_branch.screen\preview")
  arguments = "-m osr2_broker.tray --config """ & primary & "\osr2_broker_config.json"""
  interpreter = fso.BuildPath(primary, ".venv\Scripts\pythonw.exe")
  directory = root
  base = primary
  updater = fso.BuildPath(fso.GetParentFolderName(base), "app_support\.venv\Scripts\pythonw.exe")
  gates = Array(fso.BuildPath(base, ".git\production-update.turn"))
  rebases = RebaseFoldersOf(root)
End Sub

Sub Report()
  WScript.Echo "app: " & app
  WScript.Echo "primary: " & primary
  WScript.Echo "interpreter: " & interpreter
  WScript.Echo "directory: " & directory
  WScript.Echo "arguments: " & arguments
  WScript.Echo "log: " & logPath
  WScript.Echo "environment: " & "BROKER_BRANCH_SESSION" & "=" & "1"
  WScript.Echo "command: " & Command()
  WScript.Echo "update: " & Update()
  Dim gate
  For Each gate In gates
    WScript.Echo "gate: " & gate
  Next
  Dim rebase
  For Each rebase In rebases
    WScript.Echo "rebase: " & rebase
  Next
  WScript.Echo "loading screen: " & LoadingScreen()
  WScript.Echo "screen: " & screenFolder
  WScript.Echo "pictures: " & picturesFolder
End Sub

Sub Launch()
  If Not fso.FileExists(interpreter) Then
    Refuse "The primary checkout's virtual environment is missing:" & vbCrLf & interpreter
  End If
  ShowLoadingScreen
  CatchUp
  HoldGates
  shell.Environment("Process").Item("BROKER_BRANCH_SESSION") = "1"
  logPath = FreeLog(logPath)
  Note logPath, "===== " & Now & " launch: " & Command()
  StopIfCanceled
  shell.Run Command(), 0, False
  Say "started"
  ReleaseGates
End Sub

Function Command()
  Command = "cmd /c cd /d " & Quote(directory) & " && " & Quote(interpreter) & " " & arguments & " >> " & Quote(logPath) & " 2>&1 & type nul > " & Quote(fso.BuildPath(screenFolder, "ended"))
End Function

Function Quote(text)
  Quote = Chr(34) & text & Chr(34)
End Function

Sub Tell(message)
  TakeDownLoadingScreen
  If OnTheCommandLine() Then
    WScript.Echo "dialog: " & message
  ElseIf Not ShownWithCopy(message) Then
    MsgBox message, vbCritical, app
  End If
End Sub

Function ShownWithCopy(message)
  Dim told
  Set told = shell.Environment("Process")
  told("HAGLIO_ALERT_TITLE") = app
  told("HAGLIO_ALERT_MESSAGE") = message
  told("HAGLIO_ALERT_APP_ICON") = fso.BuildPath(root, "broker_icon.ico")
  told("HAGLIO_ALERT_APP_ID") = "Haglio.Alert.8c45c66d33ddd505"
  On Error Resume Next
  ShownWithCopy = shell.Run("powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand JABFAHIAcgBvAHIAQQBjAHQAaQBvAG4AUAByAGUAZgBlAHIAZQBuAGMAZQAgAD0AIAAnAFMAdABvAHAAJwAKAEEAZABkAC0AVAB5AHAAZQAgAC0AQQBzAHMAZQBtAGIAbAB5AE4AYQBtAGUAIABTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALAAgAFMAeQBzAHQAZQBtAC4ARAByAGEAdwBpAG4AZwAKAFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4AQQBwAHAAbABpAGMAYQB0AGkAbwBuAF0AOgA6AEUAbgBhAGIAbABlAFYAaQBzAHUAYQBsAFMAdAB5AGwAZQBzACgAKQAKACQAYQBwAHAASQBjAG8AbgAgAD0AIAAkAGUAbgB2ADoASABBAEcATABJAE8AXwBBAEwARQBSAFQAXwBBAFAAUABfAEkAQwBPAE4ACgAkAHcAZQBhAHIAcwBUAGgAZQBBAHAAcABzAEkAYwBvAG4AIAA9ACAAJABhAHAAcABJAGMAbwBuACAALQBhAG4AZAAgACgAVABlAHMAdAAtAFAAYQB0AGgAIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAYQBwAHAASQBjAG8AbgAgAC0AUABhAHQAaABUAHkAcABlACAATABlAGEAZgApAAoAaQBmACAAKAAkAHcAZQBhAHIAcwBUAGgAZQBBAHAAcABzAEkAYwBvAG4AKQAgAHsACgAgACAAQQBkAGQALQBUAHkAcABlACAALQBOAGEAbQBlAHMAcABhAGMAZQAgAEgAYQBnAGwAaQBvACAALQBOAGEAbQBlACAAVABhAHMAawBiAGEAcgAgAC0ATQBlAG0AYgBlAHIARABlAGYAaQBuAGkAdABpAG8AbgAgACcAWwBEAGwAbABJAG0AcABvAHIAdAAoACIAcwBoAGUAbABsADMAMgAuAGQAbABsACIALAAgAEMAaABhAHIAUwBlAHQAIAA9ACAAQwBoAGEAcgBTAGUAdAAuAFUAbgBpAGMAbwBkAGUAKQBdACAAcAB1AGIAbABpAGMAIABzAHQAYQB0AGkAYwAgAGUAeAB0AGUAcgBuACAAaQBuAHQAIABTAGUAdABDAHUAcgByAGUAbgB0AFAAcgBvAGMAZQBzAHMARQB4AHAAbABpAGMAaQB0AEEAcABwAFUAcwBlAHIATQBvAGQAZQBsAEkARAAoAHMAdAByAGkAbgBnACAAaQBkACkAOwAnAAoAIAAgAGkAZgAgACgAWwBIAGEAZwBsAGkAbwAuAFQAYQBzAGsAYgBhAHIAXQA6ADoAUwBlAHQAQwB1AHIAcgBlAG4AdABQAHIAbwBjAGUAcwBzAEUAeABwAGwAaQBjAGkAdABBAHAAcABVAHMAZQByAE0AbwBkAGUAbABJAEQAKAAkAGUAbgB2ADoASABBAEcATABJAE8AXwBBAEwARQBSAFQAXwBBAFAAUABfAEkARAApACAALQBsAHQAIAAwACkAIAB7ACAAJAB3AGUAYQByAHMAVABoAGUAQQBwAHAAcwBJAGMAbwBuACAAPQAgACQAZgBhAGwAcwBlACAAfQAKAH0ACgAkAHQAaQB0AGwAZQAgAD0AIAAkAGUAbgB2ADoASABBAEcATABJAE8AXwBBAEwARQBSAFQAXwBUAEkAVABMAEUACgAkAG0AZQBzAHMAYQBnAGUAIAA9ACAAJABlAG4AdgA6AEgAQQBHAEwASQBPAF8AQQBMAEUAUgBUAF8ATQBFAFMAUwBBAEcARQAKACQAaQBjAG8AbgAgAD0AIABbAFMAeQBzAHQAZQBtAC4ARAByAGEAdwBpAG4AZwAuAFMAeQBzAHQAZQBtAEkAYwBvAG4AcwBdADoAOgBFAHIAcgBvAHIACgAkAGYAbwByAG0AIAA9ACAATgBlAHcALQBPAGIAagBlAGMAdAAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAEYAbwByAG0ACgAkAGYAbwByAG0ALgBUAGUAeAB0ACAAPQAgACQAdABpAHQAbABlAAoAJABmAG8AcgBtAC4ARgBvAHIAbQBCAG8AcgBkAGUAcgBTAHQAeQBsAGUAIAA9ACAAJwBGAGkAeABlAGQARABpAGEAbABvAGcAJwAKACQAZgBvAHIAbQAuAE0AYQB4AGkAbQBpAHoAZQBCAG8AeAAgAD0AIAAkAGYAYQBsAHMAZQAKACQAZgBvAHIAbQAuAE0AaQBuAGkAbQBpAHoAZQBCAG8AeAAgAD0AIAAkAGYAYQBsAHMAZQAKACQAZgBvAHIAbQAuAFMAaABvAHcASQBjAG8AbgAgAD0AIAAkAHcAZQBhAHIAcwBUAGgAZQBBAHAAcABzAEkAYwBvAG4ACgBpAGYAIAAoACQAdwBlAGEAcgBzAFQAaABlAEEAcABwAHMASQBjAG8AbgApACAAewAgACQAZgBvAHIAbQAuAEkAYwBvAG4AIAA9ACAATgBlAHcALQBPAGIAagBlAGMAdAAgAFMAeQBzAHQAZQBtAC4ARAByAGEAdwBpAG4AZwAuAEkAYwBvAG4AIAAkAGEAcABwAEkAYwBvAG4AIAB9AAoAJABmAG8AcgBtAC4AUwB0AGEAcgB0AFAAbwBzAGkAdABpAG8AbgAgAD0AIAAnAEMAZQBuAHQAZQByAFMAYwByAGUAZQBuACcACgAkAGYAbwByAG0ALgBUAG8AcABNAG8AcwB0ACAAPQAgACQAdAByAHUAZQAKACQAZgBvAHIAbQAuAEEAdQB0AG8AUwBpAHoAZQAgAD0AIAAkAHQAcgB1AGUACgAkAGYAbwByAG0ALgBBAHUAdABvAFMAaQB6AGUATQBvAGQAZQAgAD0AIAAnAEcAcgBvAHcAQQBuAGQAUwBoAHIAaQBuAGsAJwAKACQAZgBvAHIAbQAuAFAAYQBkAGQAaQBuAGcAIAA9ACAATgBlAHcALQBPAGIAagBlAGMAdAAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAFAAYQBkAGQAaQBuAGcAIAAxADIACgAkAHIAbwB3AHMAIAA9ACAATgBlAHcALQBPAGIAagBlAGMAdAAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAFQAYQBiAGwAZQBMAGEAeQBvAHUAdABQAGEAbgBlAGwACgAkAHIAbwB3AHMALgBBAHUAdABvAFMAaQB6AGUAIAA9ACAAJAB0AHIAdQBlAAoAJAByAG8AdwBzAC4AQwBvAGwAdQBtAG4AQwBvAHUAbgB0ACAAPQAgADIACgAkAHIAbwB3AHMALgBSAG8AdwBDAG8AdQBuAHQAIAA9ACAAMgAKACQAcABpAGMAdAB1AHIAZQAgAD0AIABOAGUAdwAtAE8AYgBqAGUAYwB0ACAAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4AUABpAGMAdAB1AHIAZQBCAG8AeAAKACQAcABpAGMAdAB1AHIAZQAuAEkAbQBhAGcAZQAgAD0AIAAkAGkAYwBvAG4ALgBUAG8AQgBpAHQAbQBhAHAAKAApAAoAJABwAGkAYwB0AHUAcgBlAC4AUwBpAHoAZQBNAG8AZABlACAAPQAgACcAQQB1AHQAbwBTAGkAegBlACcACgAkAHAAaQBjAHQAdQByAGUALgBNAGEAcgBnAGkAbgAgAD0AIABOAGUAdwAtAE8AYgBqAGUAYwB0ACAAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4AUABhAGQAZABpAG4AZwAgADAALAAgADAALAAgADEAMgAsACAAMQAyAAoAJABzAGEAaQBkACAAPQAgAE4AZQB3AC0ATwBiAGoAZQBjAHQAIABTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBMAGEAYgBlAGwACgAkAHMAYQBpAGQALgBUAGUAeAB0ACAAPQAgACQAbQBlAHMAcwBhAGcAZQAKACQAcwBhAGkAZAAuAEEAdQB0AG8AUwBpAHoAZQAgAD0AIAAkAHQAcgB1AGUACgAkAHMAYQBpAGQALgBNAGEAeABpAG0AdQBtAFMAaQB6AGUAIAA9ACAATgBlAHcALQBPAGIAagBlAGMAdAAgAFMAeQBzAHQAZQBtAC4ARAByAGEAdwBpAG4AZwAuAFMAaQB6AGUAIAA0ADgAMAAsACAAMAAKACQAcwBhAGkAZAAuAE0AYQByAGcAaQBuACAAPQAgAE4AZQB3AC0ATwBiAGoAZQBjAHQAIABTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBQAGEAZABkAGkAbgBnACAAMAAsACAAMAAsACAAMAAsACAAMQAyAAoAJABiAHUAdAB0AG8AbgBzACAAPQAgAE4AZQB3AC0ATwBiAGoAZQBjAHQAIABTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBGAGwAbwB3AEwAYQB5AG8AdQB0AFAAYQBuAGUAbAAKACQAYgB1AHQAdABvAG4AcwAuAEEAdQB0AG8AUwBpAHoAZQAgAD0AIAAkAHQAcgB1AGUACgAkAGIAdQB0AHQAbwBuAHMALgBGAGwAbwB3AEQAaQByAGUAYwB0AGkAbwBuACAAPQAgACcAUgBpAGcAaAB0AFQAbwBMAGUAZgB0ACcACgAkAGIAdQB0AHQAbwBuAHMALgBEAG8AYwBrACAAPQAgACcARgBpAGwAbAAnAAoAJABvAGsAIAA9ACAATgBlAHcALQBPAGIAagBlAGMAdAAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAEIAdQB0AHQAbwBuAAoAJABvAGsALgBUAGUAeAB0ACAAPQAgACcATwBLACcACgAkAG8AawAuAEQAaQBhAGwAbwBnAFIAZQBzAHUAbAB0ACAAPQAgACcATwBLACcACgAkAGMAbwBwAHkAIAA9ACAATgBlAHcALQBPAGIAagBlAGMAdAAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAEIAdQB0AHQAbwBuAAoAJABjAG8AcAB5AC4AQQB1AHQAbwBTAGkAegBlACAAPQAgACQAdAByAHUAZQAKACQAYwBvAHAAeQAuAFQAZQB4AHQAIAA9ACAAJwBDAG8AcAB5ACAAZQByAHIAbwByACAAbQBlAHMAcwBhAGcAZQAnAAoAJABjAG8AcAB5AC4ATQBpAG4AaQBtAHUAbQBTAGkAegBlACAAPQAgACQAYwBvAHAAeQAuAEcAZQB0AFAAcgBlAGYAZQByAHIAZQBkAFMAaQB6AGUAKABbAFMAeQBzAHQAZQBtAC4ARAByAGEAdwBpAG4AZwAuAFMAaQB6AGUAXQA6ADoARQBtAHAAdAB5ACkACgAoAE4AZQB3AC0ATwBiAGoAZQBjAHQAIABTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBUAG8AbwBsAFQAaQBwACkALgBTAGUAdABUAG8AbwBsAFQAaQBwACgAJABjAG8AcAB5ACwAIAAiAEMAbwBwAGkAZQBzACAAdABoAGkAcwAgAHcAaQBuAGQAbwB3ACcAcwAgAHQAaQB0AGwAZQAgAGEAbgBkACAAbQBlAHMAcwBhAGcAZQAsACAAcgBlAGEAZAB5ACAAdABvACAAcABhAHMAdABlACIAKQAKACQAYgBhAGMAawAgAD0AIABOAGUAdwAtAE8AYgBqAGUAYwB0ACAAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4AVABpAG0AZQByAAoAJABiAGEAYwBrAC4ASQBuAHQAZQByAHYAYQBsACAAPQAgADIAMAAwADAACgAkAGIAYQBjAGsALgBBAGQAZABfAFQAaQBjAGsAKAB7AAoAIAAgACQAYgBhAGMAawAuAFMAdABvAHAAKAApAAoAIAAgACQAYwBvAHAAeQAuAFQAZQB4AHQAIAA9ACAAJwBDAG8AcAB5ACAAZQByAHIAbwByACAAbQBlAHMAcwBhAGcAZQAnAAoAfQApAAoAJABjAG8AcAB5AC4AQQBkAGQAXwBDAGwAaQBjAGsAKAB7AAoAIAAgAFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4AQwBsAGkAcABiAG8AYQByAGQAXQA6ADoAUwBlAHQAVABlAHgAdAAoACQAdABpAHQAbABlACAAKwAgACIAYAByAGAAbgBgAHIAYABuACIAIAArACAAJABtAGUAcwBzAGEAZwBlACkACgAgACAAJABjAG8AcAB5AC4AVABlAHgAdAAgAD0AIAAnAEMAbwBwAGkAZQBkACcACgAgACAAJABiAGEAYwBrAC4AUwB0AG8AcAAoACkACgAgACAAJABiAGEAYwBrAC4AUwB0AGEAcgB0ACgAKQAKAH0AKQAKACQAYgB1AHQAdABvAG4AcwAuAEMAbwBuAHQAcgBvAGwAcwAuAEEAZABkACgAJABvAGsAKQAKACQAYgB1AHQAdABvAG4AcwAuAEMAbwBuAHQAcgBvAGwAcwAuAEEAZABkACgAJABjAG8AcAB5ACkACgAkAHIAbwB3AHMALgBDAG8AbgB0AHIAbwBsAHMALgBBAGQAZAAoACQAcABpAGMAdAB1AHIAZQAsACAAMAAsACAAMAApAAoAJAByAG8AdwBzAC4AQwBvAG4AdAByAG8AbABzAC4AQQBkAGQAKAAkAHMAYQBpAGQALAAgADEALAAgADAAKQAKACQAcgBvAHcAcwAuAEMAbwBuAHQAcgBvAGwAcwAuAEEAZABkACgAJABiAHUAdAB0AG8AbgBzACwAIAAwACwAIAAxACkACgAkAHIAbwB3AHMALgBTAGUAdABDAG8AbAB1AG0AbgBTAHAAYQBuACgAJABiAHUAdAB0AG8AbgBzACwAIAAyACkACgAkAGYAbwByAG0ALgBDAG8AbgB0AHIAbwBsAHMALgBBAGQAZAAoACQAcgBvAHcAcwApAAoAJABmAG8AcgBtAC4AQQBjAGMAZQBwAHQAQgB1AHQAdABvAG4AIAA9ACAAJABvAGsACgAkAGYAbwByAG0ALgBBAGQAZABfAFMAaABvAHcAbgAoAHsAIAAkAGYAbwByAG0ALgBBAGMAdABpAHYAYQB0AGUAKAApACAAfQApAAoAJABmAG8AcgBtAC4ATwBwAGEAYwBpAHQAeQAgAD0AIAAwAAoAJABmAG8AcgBtAC4AUwBoAG8AdwAoACkACgAkAGYAbwByAG0ALgBIAGkAZABlACgAKQAKACQAZgBvAHIAbQAuAE8AcABhAGMAaQB0AHkAIAA9ACAAMQAKAFsAdgBvAGkAZABdACQAZgBvAHIAbQAuAFMAaABvAHcARABpAGEAbABvAGcAKAApAAoA", 0, True) = 0
  If Err.Number <> 0 Then ShownWithCopy = False
  On Error GoTo 0
End Function

Function OnTheCommandLine()
  OnTheCommandLine = LCase(fso.GetFileName(WScript.FullName)) = "cscript.exe"
End Function

Sub Refuse(message)
  Tell message
  WScript.Quit 1
End Sub

Sub Warn(message)
  TakeDownLoadingScreen
  If OnTheCommandLine() Then
    WScript.Echo "warning: " & message
  Else
    MsgBox message, vbExclamation, app
  End If
  WScript.Quit 1
End Sub

Function Update()
  Update = Quote(updater) & " -m app_support.production_update --before-launch " & Quote(base)
End Function

Sub CatchUp()
  If Not fso.FileExists(updater) Then Exit Sub
  shell.Run "cmd /c " & Quote(Update() & " & type nul > " & Quote(fso.BuildPath(screenFolder, "updated"))), 0, False
  Do Until fso.FileExists(fso.BuildPath(screenFolder, "updated"))
    StopIfCanceled
    WScript.Sleep 100
  Loop
End Sub

Sub HoldGates()
  Dim index, waited
  waited = 0
  Do While Rebasing()
    If waited >= 900000 Then WScript.Quit 1
    StopIfCanceled
    WScript.Sleep 500
    waited = waited + 500
  Loop
  ReDim held(UBound(gates))
  For index = 0 To UBound(gates)
    If fso.FolderExists(fso.GetParentFolderName(gates(index))) Then
      waited = 0
      Do Until Holds(index)
        If waited >= 900000 Then WScript.Quit 1
        StopIfCanceled
        WScript.Sleep 500
        waited = waited + 500
      Loop
    End If
  Next
End Sub

Function Holds(index)
  On Error Resume Next
  Set held(index) = fso.OpenTextFile(gates(index), 1, True)
  Holds = (Err.Number = 0)
  Err.Clear
  On Error GoTo 0
End Function

Sub ReleaseGates()
  Dim index
  For index = 0 To UBound(held)
    If IsObject(held(index)) Then held(index).Close
  Next
End Sub

Function RebaseFoldersOf(folder)
  Dim gitFolder, stream, pointer
  gitFolder = fso.BuildPath(folder, ".git")
  If fso.FileExists(gitFolder) Then
    Set stream = fso.OpenTextFile(gitFolder, 1)
    If Not stream.AtEndOfStream Then pointer = stream.ReadLine
    stream.Close
    pointer = Trim(Replace(pointer, "gitdir:", ""))
    If InStr(pointer, ":") = 0 Then pointer = fso.BuildPath(folder, pointer)
    gitFolder = fso.GetAbsolutePathName(Replace(pointer, "/", "\"))
  End If
  RebaseFoldersOf = Array(fso.BuildPath(gitFolder, "rebase-merge"), fso.BuildPath(gitFolder, "rebase-apply"))
End Function

Function Rebasing()
  Dim folder
  Rebasing = False
  For Each folder In rebases
    If fso.FolderExists(folder) Then Rebasing = True
  Next
End Function

Function LoadingScreen()
  Dim gate
  LoadingScreen = Quote(updater) & " -m app_support.loading_screen"
  For Each gate In gates
    LoadingScreen = LoadingScreen & " " & Quote(fso.GetParentFolderName(fso.GetParentFolderName(gate)))
  Next
End Function

Sub ShowLoadingScreen()
  Dim name
  shell.Environment("Process").Item("HAGLIO_LOADING_SCREEN") = screenFolder
  shell.Environment("Process").Item("HAGLIO_LOADING_SCREEN_PICTURES") = picturesFolder
  shell.Environment("Process").Item("HAGLIO_LOADING_SCREEN_LINES") = "[""Updating Broker...""]"
  If Not fso.FolderExists(fso.GetParentFolderName(screenFolder)) Then fso.CreateFolder fso.GetParentFolderName(screenFolder)
  If Not fso.FolderExists(screenFolder) Then fso.CreateFolder screenFolder
  For Each name In Array("shown.json", "taken", "started", "ended", "canceled", "updated")
    If fso.FileExists(fso.BuildPath(screenFolder, name)) Then fso.DeleteFile fso.BuildPath(screenFolder, name)
  Next
  If fso.FileExists(updater) And fso.FileExists(fso.BuildPath(picturesFolder, "pictures.json")) Then
    shell.Run LoadingScreen(), 1, False
    screenUp = True
  End If
End Sub

Sub StopIfCanceled()
  If fso.FileExists(fso.BuildPath(screenFolder, "canceled")) Then WScript.Quit 0
End Sub

Sub Say(flag)
  On Error Resume Next
  fso.CreateTextFile(fso.BuildPath(screenFolder, flag), True).Close
  Err.Clear
  On Error GoTo 0
End Sub

Sub TakeDownLoadingScreen()
  Dim waited
  If screenUp <> True Then Exit Sub
  screenUp = False
  Say "ended"
  waited = 0
  Do While fso.FileExists(fso.BuildPath(screenFolder, "shown.json")) And waited < 3000
    WScript.Sleep 100
    waited = waited + 100
  Loop
End Sub

Function FreeLog(preferred)
  Dim folder, candidate, index
  folder = fso.GetParentFolderName(preferred)
  If Not fso.FolderExists(folder) Then fso.CreateFolder folder
  For index = 1 To 9
    candidate = preferred
    If index > 1 Then
      candidate = fso.BuildPath(folder, fso.GetBaseName(preferred) & "-" & index & "." & fso.GetExtensionName(preferred))
    End If
    RollIfOversize candidate
    If CanAppend(candidate) Then
      FreeLog = candidate
      Exit Function
    End If
  Next
  FreeLog = preferred
End Function

Function CanAppend(path)
  Dim stream
  On Error Resume Next
  Set stream = fso.OpenTextFile(path, 8, True)
  CanAppend = (Err.Number = 0)
  If CanAppend Then stream.Close
  Err.Clear
  On Error GoTo 0
End Function

Sub RollIfOversize(path)
  On Error Resume Next
  If fso.FileExists(path) Then
    If fso.GetFile(path).Size > 1000000 Then
      If fso.FileExists(path & ".1") Then fso.DeleteFile path & ".1"
      fso.MoveFile path, path & ".1"
    End If
  End If
  Err.Clear
  On Error GoTo 0
End Sub

Sub Note(path, line)
  Dim stream
  On Error Resume Next
  Set stream = fso.OpenTextFile(path, 8, True)
  stream.WriteLine line
  stream.Close
  Err.Clear
  On Error GoTo 0
End Sub
