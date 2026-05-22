' PT AI Voice — Windows Launcher (double-click, no console window)
Dim oShell, oFS, strDir
Set oFS    = CreateObject("Scripting.FileSystemObject")
Set oShell = CreateObject("WScript.Shell")

strDir = oFS.GetParentFolderName(WScript.ScriptFullName)
oShell.CurrentDirectory = strDir

' pythonw.exe = Python không kèm cửa sổ console
oShell.Run "pythonw main.py", 0, False
