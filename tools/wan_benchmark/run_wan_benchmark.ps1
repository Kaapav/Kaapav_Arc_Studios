param(
    [ValidateRange(1, 240)]
    [int]$PollSeconds = 30
)

$ErrorActionPreference = "Stop"
$package = $PSScriptRoot
$root = (Resolve-Path (Join-Path $package "..\..")).Path
$kaggle = Join-Path $root ".venv\Scripts\kaggle.exe"
$python = Join-Path $root ".venv\Scripts\python.exe"
$kernel = "kaapav/kaapav-wan-i2v-benchmark"
$output = Join-Path $package "output"
$env:KAGGLE_ENABLE_OAUTH = "1"

if (!(Test-Path -LiteralPath $kaggle)) {
    throw "Kaggle CLI missing: $kaggle"
}
if (!(Test-Path -LiteralPath $python)) {
    throw "Project Python missing: $python"
}

& $python (Join-Path $package "build_notebook.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python (Join-Path $package "validate_package.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Submitting private Kaggle T4 benchmark..."
& $kaggle kernels push -p $package
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$deadline = (Get-Date).AddHours(4)
do {
    Start-Sleep -Seconds $PollSeconds
    $statusText = (& $kaggle kernels status $kernel 2>&1 | Out-String).Trim()
    Write-Host $statusText
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($statusText -match '(?i)complete') { break }
    if ($statusText -match '(?i)error|failed|cancel') {
        throw "Kaggle benchmark failed: $statusText"
    }
    if ((Get-Date) -ge $deadline) {
        throw "Kaggle benchmark did not complete within four hours"
    }
} while ($true)

New-Item -ItemType Directory -Force -Path $output | Out-Null
& $kaggle kernels output $kernel -p $output --force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$reportPath = Join-Path $output "benchmark_report.json"
if (!(Test-Path -LiteralPath $reportPath)) {
    throw "Kaggle completed without benchmark_report.json"
}
$report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if ($report.status -ne "passed") {
    throw "Wan benchmark did not pass: $($report.error)"
}
Write-Host "WAN BENCHMARK PASSED"
Write-Host "Video: $(Join-Path $output 'kaapav_wan_benchmark.mp4')"
Write-Host "Generation seconds: $($report.generation_seconds)"
