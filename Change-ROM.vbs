Option Explicit

Dim fso, shell, appDir, exePath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
exePath = fso.BuildPath(appDir, "Shinobi3Recomp.exe")

If Not fso.FileExists(exePath) Then
    MsgBox "Shinobi3Recomp.exe was not found beside this helper.", vbOKOnly Or vbExclamation, "Shinobi III"
    WScript.Quit 1
End If

' The app opens its native ROM picker, remembers a valid selection, and then
' starts the game. Hiding the script host avoids a console window.
shell.Run Chr(34) & exePath & Chr(34) & " --select-rom", 0, False
