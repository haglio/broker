' Starts the broker's tray icon, which in turn supervises the broker itself.
' Launched by the "OSR2 Broker" scheduled task, by the Start Menu shortcut, and
' by fun_time. The tray's own mutex makes a duplicate launch a no-op.

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
configPath = projectRoot & "\osr2_broker_config.json"

' pythonw, not python: the tray is a GUI app and must not flash up a console.
pythonExe = projectRoot & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonExe) Then
    pythonExe = "pythonw.exe"
End If

shell.CurrentDirectory = projectRoot
cmd = """" & pythonExe & """ -m osr2_broker.tray --config """ & configPath & """"
shell.Run cmd, 0, False
