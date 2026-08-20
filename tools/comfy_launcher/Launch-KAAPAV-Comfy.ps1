$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'KAAPAV ComfyUI Launcher'

$Kaggle = 'D:\Apps\YT-Auto\.venv\Scripts\kaggle.exe'
$KernelFolder = 'D:\Apps\COMFY-UI\launcher'
$Kernel = 'kaapav/kaapav-comfyui-launcher'
$HealthUrl = 'https://comfy.kaapav.com/system_stats'
$ComfyUrl = 'https://comfy.kaapav.com/'

$env:KAGGLE_ENABLE_OAUTH = '1'
$env:PYTHONUTF8 = '1'

function Get-KernelStatus {
    $lines = & $Kaggle kernels status $Kernel 2>&1
    return ($lines -join ' ')
}

function Test-ComfyHealth {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 10
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

Write-Host ''
Write-Host 'KAAPAV ARC Studios - starting private ComfyUI...' -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $Kaggle)) {
    throw "Kaggle CLI not found: $Kaggle"
}
if (-not (Test-Path -LiteralPath (Join-Path $KernelFolder 'kernel-metadata.json'))) {
    throw "Launcher package not found: $KernelFolder"
}

$status = Get-KernelStatus
if (($status -notmatch 'RUNNING') -and ($status -notmatch 'QUEUED')) {
    Write-Host 'Starting a fresh private Kaggle GPU session...'
    & $Kaggle kernels push -p $KernelFolder
    if ($LASTEXITCODE -ne 0) {
        throw 'Kaggle rejected the launcher kernel push.'
    }
}
else {
    Write-Host 'A launcher session is already active; reusing it.'
}

$deadline = (Get-Date).AddMinutes(15)
while ((Get-Date) -lt $deadline) {
    if (Test-ComfyHealth) {
        Write-Host 'ComfyUI is healthy. Opening browser...' -ForegroundColor Green
        Start-Process $ComfyUrl
        exit 0
    }

    $status = Get-KernelStatus
    if ($status -match 'ERROR|CANCELLED') {
        throw "Kaggle launcher failed. Status: $status"
    }
    Write-Host 'Waiting for Kaggle, ComfyUI, and Cloudflare tunnel...'
    Start-Sleep -Seconds 15
}

throw 'ComfyUI did not become reachable within 15 minutes. Check the private Kaggle kernel log.'
