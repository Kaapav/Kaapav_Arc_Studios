$ErrorActionPreference = "Stop"
$endpoint = "http://127.0.0.1:8765/api/bootstrap"

try {
    $bootstrap = Invoke-RestMethod -Uri $endpoint -TimeoutSec 3
}
catch {
    throw "The KAAPAV dashboard is not running. Open KAAPAV Studio Dashboard first."
}

$code = [string]$bootstrap.code
Set-Clipboard -Value $code
Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show(
    "Pairing code:`n`n$code`n`nValid for 60 seconds and copied to this PC's clipboard. Enter it once in the KAAPAV Control Room app.",
    "KAAPAV Secure Device Pairing",
    [System.Windows.MessageBoxButton]::OK,
    [System.Windows.MessageBoxImage]::Information
) | Out-Null
