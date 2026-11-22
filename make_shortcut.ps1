<#
.SYNOPSIS
    Creates a Desktop shortcut for Remove AI Watermarks Studio.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\make_shortcut.ps1
#>
[CmdletBinding()]
param(
    [switch]$IncludeUpdater
)

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$target = Join-Path $root "Start Studio.cmd"
if (-not (Test-Path $target)) {
    throw "Launcher not found: $target"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "Remove AI Watermarks Studio.lnk"

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = $target
$sc.WorkingDirectory = $root
$sc.Description = "Remove AI Watermarks Studio - local web app"
$sc.WindowStyle = 7  # start minimized; the browser is the primary UI
$sc.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
$sc.Save()

Write-Host "Desktop shortcut created: $link" -ForegroundColor Green

if ($IncludeUpdater) {
    $updTarget = Join-Path $root "Update Studio.cmd"
    if (Test-Path $updTarget) {
        $updLink = Join-Path $desktop "Update Remove AI Watermarks Studio.lnk"
        $usc = $shell.CreateShortcut($updLink)
        $usc.TargetPath = $updTarget
        $usc.WorkingDirectory = $root
        $usc.Description = "Update Remove AI Watermarks Studio from GitHub"
        $usc.WindowStyle = 1
        $usc.IconLocation = "$env:SystemRoot\System32\shell32.dll,238"
        $usc.Save()
        Write-Host "Updater shortcut created: $updLink" -ForegroundColor Green
    }
}
