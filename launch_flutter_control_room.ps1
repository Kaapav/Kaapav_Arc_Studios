$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$exe = Join-Path $root "flutter\kaapav_control_room\build\windows\x64\runner\Release\kaapav_control_room.exe"

if (!(Test-Path -LiteralPath $exe)) {
    throw "KAAPAV Control Room is not built yet: $exe"
}

Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe)
