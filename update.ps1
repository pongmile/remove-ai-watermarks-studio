<#
.SYNOPSIS
    Safe 1-click GitHub & upstream updater for Remove AI Watermarks Studio.
    Features automatic network retries with exponential backoff, PowerShell 5.1 stderr safety,
    optional -AutoStash, and full protection for your installed GPU PyTorch wheel
    (cu128 / xpu / rocm / directml / mps).

.EXAMPLE
    .\update.ps1                 # Pull latest updates from your fork (origin)
    .\update.ps1 -Upstream       # Sync latest releases from wiltodelta/remove-ai-watermarks
    .\update.ps1 -CheckOnly      # Check for updates without modifying files
    .\update.ps1 -AutoStash      # Auto-stash tracked local changes before updating & restore after
#>
[CmdletBinding()]
param(
    [switch]$Upstream,
    [switch]$CheckOnly,
    [string]$Branch = "",
    [switch]$SkipDeps,
    [switch]$AutoStash,
    [ValidateRange(1, 10)]
    [int]$Retries = 3
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:HF_HUB_DISABLE_XET = "1"
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "never"

$Root = $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$UpstreamUrl = "https://github.com/wiltodelta/remove-ai-watermarks.git"
$Stashed = $false

function Write-Step([string]$Msg) {
    Write-Host ""
    Write-Host "==> $Msg" -ForegroundColor Cyan
}

function Write-Info([string]$Msg) {
    Write-Host "    $Msg" -ForegroundColor Gray
}

function Write-Warn([string]$Msg) {
    Write-Host "    [warn] $Msg" -ForegroundColor Yellow
}

function Write-Ok([string]$Msg) {
    Write-Host "    [ok] $Msg" -ForegroundColor Green
}

function Invoke-Native {
    <#
    Runs a native executable safely under Windows PowerShell 5.1 even when
    the program writes normal progress messages (like git fetch) to stderr.
    Returns exit code via $LASTEXITCODE.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $FilePath @Arguments 2>$null
        return [pscustomobject]@{
            ExitCode = $LASTEXITCODE
            Output   = if ($null -eq $out) { "" } else { ($out -join "`n").Trim() }
        }
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Invoke-WithRetry {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$MaxAttempts = 3,
        [int]$BaseDelaySec = 2
    )
    $attempts = [Math]::Max(1, $MaxAttempts)
    for ($i = 1; $i -le $attempts; $i++) {
        $rc = Invoke-Native -FilePath $FilePath -Arguments $Arguments
        if ($rc -eq 0) {
            if ($i -gt 1) {
                Write-Ok "$Label succeeded on attempt $i/$attempts."
            }
            return 0
        }
        if ($i -lt $attempts) {
            $delay = $BaseDelaySec * [Math]::Pow(2, $i - 1)
            Write-Warn "$Label failed (attempt $i/$attempts, exit $rc). Retrying in ${delay}s..."
            Start-Sleep -Seconds $delay
        }
    }
    return 1
}

function Get-TorchIndexForTag([string]$Version) {
    if ($Version -match "\+(cu\d+)") {
        return "https://download.pytorch.org/whl/$($Matches[1])"
    }
    if ($Version -match "\+xpu") {
        return "https://download.pytorch.org/whl/xpu"
    }
    if ($Version -match "\+(rocm[\d\.]+)") {
        return "https://download.pytorch.org/whl/$($Matches[1])"
    }
    if ($Version -match "\+cpu") {
        return "https://download.pytorch.org/whl/cpu"
    }
    return ""
}

Push-Location $Root
try {
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "  Remove AI Watermarks Studio - GitHub Updater" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan

    $GitCmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $GitCmd) {
        throw "Git is not installed or not on PATH. Install Git from https://git-scm.com/downloads"
    }
    $GitExe = $GitCmd.Source

    $repoCheck = Invoke-NativeCapture -FilePath $GitExe -Arguments @("rev-parse", "--is-inside-work-tree")
    if ($repoCheck.ExitCode -ne 0 -or $repoCheck.Output -ne "true") {
        throw "This folder is not a Git repository. Clone the repo with 'git clone' to enable 1-click updates."
    }

    # 1. Check tracked working tree state
    Write-Step "Checking repository state"
    $dirtyRes = Invoke-NativeCapture -FilePath $GitExe -Arguments @("status", "--porcelain", "--untracked-files=no")
    if ($dirtyRes.Output) {
        if ($AutoStash -and -not $CheckOnly) {
            Write-Warn "Uncommitted tracked changes detected; stashing cleanly (-AutoStash)..."
            $stashRc = Invoke-Native -FilePath $GitExe -Arguments @("stash", "push", "-m", "studio-auto-update")
            if ($stashRc -ne 0) { throw "git stash failed." }
            $Stashed = $true
            Write-Ok "Local changes stashed safely."
        } else {
            Write-Host ""
            Write-Host "Update aborted: you have uncommitted changes to tracked files:" -ForegroundColor Red
            $dirtyRes.Output -split "`n" | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
            Write-Host ""
            Write-Host "Save, discard, or pass -AutoStash to temporarily shelve changes:" -ForegroundColor White
            Write-Host "  .\update.ps1 -AutoStash              # auto-stash and restore after update" -ForegroundColor Gray
            Write-Host "  git stash push -m `"local edits`"      # or stash manually" -ForegroundColor Gray
            exit 1
        }
    }

    $currentBranch = if ($Branch) { $Branch } else { (Invoke-NativeCapture -FilePath $GitExe -Arguments @("rev-parse", "--abbrev-ref", "HEAD")).Output }
    if (-not $currentBranch -or $currentBranch -eq "HEAD") {
        throw "Repository is in detached HEAD state. Checkout a branch (e.g. 'git checkout main') first."
    }
    $oldCommit = (Invoke-NativeCapture -FilePath $GitExe -Arguments @("rev-parse", "--short", "HEAD")).Output
    Write-Ok "Branch: $currentBranch  |  Commit: $oldCommit  |  Max retries: $Retries"

    # Snapshot currently installed PyTorch wheel so it is NEVER downgraded/replaced
    $savedTorch = ""
    $savedVision = ""
    if (Test-Path $VenvPy) {
        $tRes = Invoke-NativeCapture -FilePath $VenvPy -Arguments @("-c", "import torch; print(torch.__version__)")
        if ($tRes.ExitCode -eq 0) { $savedTorch = $tRes.Output }
        $vRes = Invoke-NativeCapture -FilePath $VenvPy -Arguments @("-c", "import torchvision; print(torchvision.__version__)")
        if ($vRes.ExitCode -eq 0) { $savedVision = $vRes.Output }
        if ($savedTorch) {
            Write-Info "Protected PyTorch wheel: torch==$savedTorch"
        }
    }

    # 2. Fetch & inspect or apply update (with automatic retry & low-speed timeout protection)
    $updated = $false
    $netGitOpts = @("-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=20")

    if ($Upstream) {
        Write-Step "Fetching upstream (wiltodelta/remove-ai-watermarks)"
        $remotes = (Invoke-NativeCapture -FilePath $GitExe -Arguments @("remote")).Output -split "`n"
        if ($remotes -notcontains "upstream") {
            Write-Info "Adding 'upstream' remote -> $UpstreamUrl"
            $rcAdd = Invoke-Native -FilePath $GitExe -Arguments @("remote", "add", "upstream", $UpstreamUrl)
            if ($rcAdd -ne 0) { throw "Failed to add upstream remote." }
        }
        $fetchRc = Invoke-WithRetry -Label "git fetch upstream" -FilePath $GitExe -Arguments ($netGitOpts + @("fetch", "--tags", "upstream")) -MaxAttempts $Retries
        if ($fetchRc -ne 0) {
            throw "git fetch upstream failed after $Retries attempts. Check your internet connection and try again."
        }

        $upstreamRef = "upstream/main"
        $refChk = Invoke-NativeCapture -FilePath $GitExe -Arguments @("rev-parse", "--verify", "--quiet", $upstreamRef)
        if ($refChk.ExitCode -ne 0) { $upstreamRef = "upstream/master" }

        $behind = [int](Invoke-NativeCapture -FilePath $GitExe -Arguments @("rev-list", "--count", "HEAD..$upstreamRef")).Output
        Write-Info "Commits behind ${upstreamRef}: $behind"

        if ($CheckOnly) {
            if ($behind -gt 0) {
                $null = Invoke-Native -FilePath $GitExe -Arguments @("log", "--oneline", "-n", "10", "HEAD..$upstreamRef")
            } else {
                Write-Ok "Already up to date with $upstreamRef."
            }
            exit 0
        }

        if ($behind -eq 0) {
            Write-Ok "Already up to date with $upstreamRef."
        } else {
            Write-Step "Merging $upstreamRef"
            $ffRc = Invoke-Native -FilePath $GitExe -Arguments @("merge", "--ff-only", $upstreamRef)
            if ($ffRc -ne 0) {
                Write-Info "Fast-forward not possible (fork has local commits); performing merge..."
                $mRc = Invoke-Native -FilePath $GitExe -Arguments @("merge", "--no-edit", $upstreamRef)
                if ($mRc -ne 0) {
                    Write-Warn "Merge conflict detected; aborting merge cleanly to keep your workspace intact."
                    $null = Invoke-Native -FilePath $GitExe -Arguments @("merge", "--abort")
                    Write-Host ""
                    Write-Host "Resolve manually with:" -ForegroundColor Yellow
                    Write-Host "  git merge $upstreamRef" -ForegroundColor White
                    exit 1
                }
            }
            $updated = $true
        }
    } else {
        $remotes = (Invoke-NativeCapture -FilePath $GitExe -Arguments @("remote")).Output -split "`n"
        if ($remotes -notcontains "origin") {
            throw "No 'origin' remote is configured. Use '.\update.ps1 -Upstream' or add an 'origin' remote first."
        }
        Write-Step "Fetching origin ($currentBranch)"
        $fetchRc = Invoke-WithRetry -Label "git fetch origin" -FilePath $GitExe -Arguments ($netGitOpts + @("fetch", "--tags", "origin")) -MaxAttempts $Retries
        if ($fetchRc -ne 0) {
            throw "git fetch origin failed after $Retries attempts. Check your internet connection and try again."
        }

        $targetRef = "origin/$currentBranch"
        $refCheck = Invoke-NativeCapture -FilePath $GitExe -Arguments @("rev-parse", "--verify", "--quiet", $targetRef)
        if ($refCheck.ExitCode -ne 0) {
            throw "Remote branch '$targetRef' not found."
        }

        $behind = [int](Invoke-NativeCapture -FilePath $GitExe -Arguments @("rev-list", "--count", "HEAD..$targetRef")).Output
        Write-Info "Commits behind ${targetRef}: $behind"

        if ($CheckOnly) {
            if ($behind -gt 0) {
                $null = Invoke-Native -FilePath $GitExe -Arguments @("log", "--oneline", "-n", "10", "HEAD..$targetRef")
            } else {
                Write-Ok "Already up to date with $targetRef."
            }
            exit 0
        }

        if ($behind -eq 0) {
            Write-Ok "Already up to date with $targetRef."
        } else {
            Write-Step "Applying updates locally (--ff-only from fetched $targetRef)"
            $ffRc = Invoke-Native -FilePath $GitExe -Arguments @("merge", "--ff-only", $targetRef)
            if ($ffRc -ne 0) {
                Write-Host ""
                Write-Host "Fast-forward merge failed (your local branch has diverged from $targetRef)." -ForegroundColor Red
                Write-Host "Reconcile with 'git pull --rebase' or 'git merge $targetRef'." -ForegroundColor Yellow
                exit 1
            }
            $updated = $true
        }
    }

    $newCommit = (Invoke-NativeCapture -FilePath $GitExe -Arguments @("rev-parse", "--short", "HEAD")).Output
    if ($updated) {
        Write-Ok "Updated: $oldCommit -> $newCommit"
    }

    # 3. Sync Python dependencies & editable metadata while preserving GPU PyTorch wheel
    if (-not $SkipDeps -and (Test-Path $VenvPy)) {
        $UvCmd = Get-Command uv -ErrorAction SilentlyContinue
        $pyprojectChanged = $false
        if ($updated) {
            $diffRes = Invoke-NativeCapture -FilePath $GitExe -Arguments @("diff", "--name-only", $oldCommit, $newCommit)
            $changedFiles = $diffRes.Output -split "`n"
            if ($changedFiles -contains "pyproject.toml") {
                $pyprojectChanged = $true
            }
        }

        if ($pyprojectChanged) {
            Write-Step "pyproject.toml changed; syncing dependencies (preserving PyTorch wheel)"
            $torchIndex = Get-TorchIndexForTag $savedTorch
            $depArgs = @()
            if ($torchIndex) {
                $depArgs += @("--extra-index-url", $torchIndex)
            }
            $depArgs += ".[studio,visible,video,heif,detect,lama,migan,source-classify]"
            if ($UvCmd) {
                $depRc = Invoke-WithRetry -Label "uv pip sync" -FilePath $UvCmd.Source -Arguments (@("pip", "install", "--python", $VenvPy) + $depArgs) -MaxAttempts $Retries
            } else {
                $depRc = Invoke-WithRetry -Label "pip sync" -FilePath $VenvPy -Arguments (@("-m", "pip", "install") + $depArgs) -MaxAttempts $Retries
            }
            if ($depRc -ne 0) { Write-Warn "Dependency sync encountered a network error; continuing with existing packages." }

            # Verify GPU PyTorch wheel remained intact
            if ($savedTorch) {
                $afterTorch = (Invoke-NativeCapture -FilePath $VenvPy -Arguments @("-c", "import torch; print(torch.__version__)")).Output
                if ($afterTorch -ne $savedTorch -and $torchIndex) {
                    Write-Warn "PyTorch changed ($savedTorch -> $afterTorch); restoring $savedTorch..."
                    $baseTorch = ($savedTorch -split "\+")[0]
                    $restoreSpecs = @("torch==$baseTorch")
                    if ($savedVision) {
                        $baseVision = ($savedVision -split "\+")[0]
                        $restoreSpecs += "torchvision==$baseVision"
                    }
                    $rArgs = @("--index-url", $torchIndex, "--force-reinstall", "--no-deps") + $restoreSpecs
                    if ($UvCmd) {
                        $null = Invoke-WithRetry -Label "restore PyTorch wheel" -FilePath $UvCmd.Source -Arguments (@("pip", "install", "--python", $VenvPy) + $rArgs) -MaxAttempts $Retries
                    } else {
                        $null = Invoke-WithRetry -Label "restore PyTorch wheel" -FilePath $VenvPy -Arguments (@("-m", "pip", "install") + $rArgs) -MaxAttempts $Retries
                    }
                }
            }
        }

        Write-Step "Refreshing editable package metadata (--no-deps -e .)"
        if ($UvCmd) {
            $edRc = Invoke-WithRetry -Label "editable install" -FilePath $UvCmd.Source -Arguments @("pip", "install", "--python", $VenvPy, "--no-deps", "-e", ".") -MaxAttempts 2
        } else {
            $edRc = Invoke-WithRetry -Label "editable install" -FilePath $VenvPy -Arguments @("-m", "pip", "install", "--no-deps", "-e", ".") -MaxAttempts 2
        }
        if ($edRc -ne 0) { throw "Editable install failed." }

        # 4. Quick self-check
        Write-Step "Running self-check"
        $SelfCheck = @"
import remove_ai_watermarks as raiw
print('Version         :', getattr(raiw, '__version__', 'installed'))
try:
    import torch
    print('PyTorch         :', torch.__version__)
except Exception:
    print('PyTorch         : not installed')
try:
    from remove_ai_watermarks._internal.accelerator import detect_hardware_summary
    hw = detect_hardware_summary()
    print('Accelerator     :', hw.get('accelerator_kind'), '|', hw.get('device_name'))
    print('ONNX Provider   :', hw.get('active_onnx_provider'))
except Exception:
    pass
"@
        $scRc = Invoke-Native -FilePath $VenvPy -Arguments @("-c", $SelfCheck)
        if ($scRc -ne 0) { throw "Self-check failed." }
    } elseif (-not (Test-Path $VenvPy)) {
        Write-Warn "No .venv found. Run .\install.ps1 to install dependencies."
    }

    Write-Host ""
    if ($updated) {
        Write-Host "Update complete ($oldCommit -> $newCommit). Restart Remove AI Watermarks Studio if it is running." -ForegroundColor Green
    } else {
        Write-Host "Everything is up to date ($newCommit)." -ForegroundColor Green
    }
} finally {
    if ($Stashed) {
        Write-Step "Restoring auto-stashed local changes"
        $popRc = Invoke-Native -FilePath "git" -Arguments @("stash", "pop")
        if ($popRc -ne 0) {
            Write-Warn "git stash pop reported conflicts; your edits remain safely saved in 'git stash list'."
        } else {
            Write-Ok "Local changes restored cleanly."
        }
    }
    Pop-Location
}
