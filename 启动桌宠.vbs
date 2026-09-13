' 本机安静启动：不显示控制台；再次启动会打开现有面板。
Option Explicit
Dim files, shell, root, python
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(root, ".venv\Scripts\pythonw.exe")
If Not files.FileExists(python) Then
    MsgBox "Please run setup.ps1 first.", 48, "Neko Local Companion"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run Chr(34) & python & Chr(34) & " -m pet", 4, False
