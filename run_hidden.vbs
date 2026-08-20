Option Explicit

Dim shell, fileSystem, root, scriptArgument, scriptPath, powershellPath, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

If WScript.Arguments.Count < 1 Then
    WScript.Quit 2
End If

root = fileSystem.GetParentFolderName(WScript.ScriptFullName)
scriptArgument = WScript.Arguments(0)
If fileSystem.FileExists(scriptArgument) Then
    scriptPath = fileSystem.GetAbsolutePathName(scriptArgument)
Else
    scriptPath = fileSystem.BuildPath(root, scriptArgument)
End If
If Not fileSystem.FileExists(scriptPath) Then
    WScript.Quit 3
End If

powershellPath = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
command = Chr(34) & powershellPath & Chr(34) & _
    " -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File " & _
    Chr(34) & scriptPath & Chr(34)
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
