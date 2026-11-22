<#
.SYNOPSIS
    Launches Remove AI Watermarks Studio on Windows.

.EXAMPLE
    .\run_webapp.ps1
    .\run_webapp.ps1 -Port 8080 -Open
    .\run_webapp.ps1 -Host 127.0.0.1 -Port 8000
#>
[CmdletBinding()]
param(
    [Alias("Host")]
    [string]$BindHost = $(if ($env:RAIW_HOST) { $env:RAIW_HOST } else { "127.0.0.1" }),

    [int]$Port = $(if ($env:RAIW_PORT) { [int]$env:RAIW_PORT } else { 8000 }),

    [switch]$Open
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
# Disable hf-xet on Windows to prevent stalled Hugging Face model downloads.
$env:HF_HUB_DISABLE_XET = "1"

$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host ""
    Write-Host "Virtual environment not found at $py" -ForegroundColor Red
    Write-Host "Run the installer first:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\install.ps1" -ForegroundColor White
    exit 1
}

$url = "http://${BindHost}:${Port}"
Write-Host "Starting Remove AI Watermarks Studio at $url  (Ctrl+C to stop)" -ForegroundColor Cyan

if ($Open) {
    $browserTarget = if ($BindHost -eq "0.0.0.0") { "http://127.0.0.1:${Port}" } else { $url }
    $probeHost = if ($BindHost -eq "0.0.0.0") { "127.0.0.1" } else { $BindHost }
    Start-Process -WindowStyle Hidden powershell -ArgumentList @(
        "-NoProfile",
        "-Command",
        "`$deadline=(Get-Date).AddSeconds(25); while((Get-Date) -lt `$deadline){ try { `$c=New-Object System.Net.Sockets.TcpClient('$probeHost',$Port); `$c.Close(); Start-Process '$browserTarget'; break } catch { Start-Sleep -Milliseconds 250 } }"
    )
}

# Invoke the venv Python directly (never `uv run`) to preserve GPU PyTorch wheels.
Push-Location $root
try {
    & $py -m uvicorn webapp.server:app --host $BindHost --port $Port
} finally {
    Pop-Location
}
