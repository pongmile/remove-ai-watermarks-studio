<#
.SYNOPSIS
    Smart launcher for Remove AI Watermarks Studio on Windows.
    Supports single-instance browser reuse, automatic shutdown when the last tab closes
    (-AutoShutdown / -NoAutoShutdown), and seamless in-app restart (exit code 75).

.EXAMPLE
    .\run_webapp.ps1 -Open
    .\run_webapp.ps1 -Port 8080 -Open -NoAutoShutdown
    .\run_webapp.ps1 -Host 127.0.0.1 -Port 8000
#>
[CmdletBinding()]
param(
    [Alias("Host")]
    [string]$BindHost = $(if ($env:RAIW_HOST) { $env:RAIW_HOST } else { "127.0.0.1" }),

    [int]$Port = $(if ($env:RAIW_PORT) { [int]$env:RAIW_PORT } else { 8000 }),

    [switch]$Open,

    [switch]$NoAutoShutdown
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
# Disable hf-xet on Windows to prevent stalled Hugging Face model downloads.
$env:HF_HUB_DISABLE_XET = "1"
if (-not $NoAutoShutdown -and $Open) {
    if (-not $env:RAIW_AUTO_SHUTDOWN) { $env:RAIW_AUTO_SHUTDOWN = "1" }
} elseif ($NoAutoShutdown) {
    $env:RAIW_AUTO_SHUTDOWN = "0"
}
$env:RAIW_ALLOW_RESTART = "1"

$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host ""
    Write-Host "Virtual environment not found at $py" -ForegroundColor Red
    Write-Host "Run the installer first:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\install.ps1" -ForegroundColor White
    exit 1
}

$probeHost = if ($BindHost -eq "0.0.0.0") { "127.0.0.1" } else { $BindHost }
$browserTarget = "http://${probeHost}:${Port}"
$url = "http://${BindHost}:${Port}"

# Smart single-instance check: if Studio is already running, reuse it instead of failing on port bind
$alreadyRunning = $false
try {
    $resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 -Uri "${browserTarget}/health"
    if ($resp.StatusCode -eq 200) { $alreadyRunning = $true }
} catch {
    $alreadyRunning = $false
}

if ($alreadyRunning) {
    Write-Host "Remove AI Watermarks Studio is already running at $browserTarget" -ForegroundColor Green
    if ($Open) { Start-Process $browserTarget }
    exit 0
}

Write-Host "Starting Remove AI Watermarks Studio at $url  (click Quit in app or Ctrl+C to stop)" -ForegroundColor Cyan

if ($Open) {
    Start-Process -WindowStyle Hidden powershell -ArgumentList @(
        "-NoProfile",
        "-Command",
        "`$deadline=(Get-Date).AddSeconds(25); while((Get-Date) -lt `$deadline){ try { `$c=New-Object System.Net.Sockets.TcpClient('$probeHost',$Port); `$c.Close(); Start-Process '$browserTarget'; break } catch { Start-Sleep -Milliseconds 250 } }"
    )
}

# Invoke the venv Python directly (never `uv run`) to preserve GPU PyTorch wheels.
Push-Location $root
try {
    while ($true) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $py -m uvicorn webapp.server:app --host $BindHost --port $Port
            $rc = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prev
        }
        if ($rc -eq 75) {
            Write-Host "Restarting Remove AI Watermarks Studio..." -ForegroundColor Cyan
            continue
        }
        exit $rc
    }
} finally {
    Pop-Location
}
