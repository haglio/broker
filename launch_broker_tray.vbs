' Rendered from [tool.haglio.launchers."launch_broker_tray.vbs"] in pyproject.toml.
' Change the spec, then run  python -m app_support.launcher --write  in this
' folder: the suite fails on a launcher that differs from its spec.

Option Explicit

Dim fso, shell, root, app, interpreter, directory, arguments

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
  app = "OSR2 Broker"
  arguments = "-m osr2_broker.tray --config """ & root & "\osr2_broker_config.json"""
  interpreter = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")
  If fso.FileExists(fso.BuildPath(root, ".venv\Scripts\Broker-Tray.exe")) Then interpreter = fso.BuildPath(root, ".venv\Scripts\Broker-Tray.exe")
  directory = root
End Sub

Sub Report()
  WScript.Echo "app: " & app
  WScript.Echo "interpreter: " & interpreter
  WScript.Echo "directory: " & directory
  WScript.Echo "arguments: " & arguments
  WScript.Echo "command: " & Command()
End Sub

Sub Launch()
  If Not fso.FileExists(interpreter) Then
    Refuse app & "'s virtual environment is missing:" & vbCrLf & interpreter, vbCritical
  End If
  shell.CurrentDirectory = directory
  shell.Run Command(), 0, False
End Sub

Function Command()
  Command = Quote(interpreter) & " " & arguments
End Function

Function Quote(text)
  Quote = Chr(34) & text & Chr(34)
End Function

Sub Tell(message, icon)
  If LCase(fso.GetFileName(WScript.FullName)) = "cscript.exe" Then
    WScript.Echo "dialog: " & message
  Else
    MsgBox message, icon, app
  End If
End Sub

Sub Refuse(message, icon)
  Tell message, icon
  WScript.Quit 1
End Sub
