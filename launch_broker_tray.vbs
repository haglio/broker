' Starts the broker's tray icon, which in turn supervises the broker itself.
' Launched by the "OSR2 Broker" scheduled task, by the Start Menu shortcut, and
' by fun_time. The tray's own mutex makes a duplicate launch a no-op.

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
configPath = projectRoot & "\osr2_broker_config.json"

' pythonw, not python: the tray is a GUI app and must not flash up a console.
pythonExe = projectRoot & "\.venv\Scripts\pythonw.exe"

' The copy a previous run left named for the tray, when there is one.  Windows
' identifies a process by the file it was started from, so a bare interpreter
' puts the tray and the broker it supervises in the task list as two identical
' anonymous "Python" rows -- which is exactly the pair you need to tell apart
' when one of them is stuck.  See osr2_broker.process_names.
namedExe = projectRoot & "\.venv\Scripts\Broker-Tray.exe"
If fso.FileExists(namedExe) Then
    pythonExe = namedExe
End If
If Not fso.FileExists(pythonExe) Then
    pythonExe = "pythonw.exe"
End If

shell.CurrentDirectory = projectRoot
cmd = """" & pythonExe & """ -m osr2_broker.tray --config """ & configPath & """"
shell.Run cmd, 0, False
