<#
.SYNOPSIS
    Safe 1-click GitHub & upstream updater for Remove AI Watermarks Studio.
    Preserves your installed GPU PyTorch wheel (cu128 / xpu / rocm / directml / mps).

.EXAMPLE
    .\update.ps1                 # Pull latest updates from your fork (origin)
    .\update.ps1 -Upstream       # Sync latest releases from wiltodelta/remove-ai-watermarks
    .\update.ps1 -CheckOnly      # Check for updates without modifying files
#>
[CmdletBinding()]
param(
    [switch]$Upstream,
    [switch]$CheckOnly,
    [string]$Branch = "",
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:HF_HUB_DISABLE_XET = "1"

$Root = $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$UpstreamUrl = "https://github.com/wiltodelta/remove-ai-watermarks.git"

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

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is not installed or not on PATH. Install Git from https://git-scm.com/downloads"
    }

    $isRepo = (& git rev-parse --is-inside-work-tree 2>$null)
    if ($LASTEXITCODE -ne 0 -or $isRepo.Trim() -ne "true") {
        throw "This folder is not a Git repository. Clone the repo with 'git clone' to enable 1-click updates."
    }

    # 1. Refuse cleanly if tracked working tree has uncommitted modifications
    Write-Step "Checking repository state"
    $dirty = (& git status --porcelain --untracked-files=no)
    if ($dirty) {
        Write-Host ""
        Write-Host "Update aborted: you have uncommitted changes to tracked files:" -ForegroundColor Red
        $dirty | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
        Write-Host ""
        Write-Host "Save or discard them first, then re-run update:" -ForegroundColor White
        Write-Host "  git stash push -m `"local edits`"    # temporarily shelve changes" -ForegroundColor Gray
        Write-Host "  git commit -am `"my changes`"        # or commit them" -ForegroundColor Gray
        exit 1
    }

    $currentBranch = if ($Branch) { $Branch } else { (& git rev-parse --abbrev-ref HEAD).Trim() }
    $oldCommit = (& git rev-parse --short HEAD).Trim()
    Write-Ok "Branch: $currentBranch  |  Commit: $oldCommit"

    # Snapshot currently installed PyTorch wheel so it is NEVER downgraded/replaced
    $savedTorch = ""
    $savedVision = ""
    if (Test-Path $VenvPy) {
        $savedTorch = (& $VenvPy -c "import torch; print(torch.__version__)" 2>$null)
        if ($savedTorch) { $savedTorch = $savedTorch.Trim() }
        $savedVision = (& $VenvPy -c "import torchvision; print(torchvision.__version__)" 2>$null)
        if ($savedVision) { $savedVision = $savedVision.Trim() }
        if ($savedTorch) {
            Write-Info "Protected PyTorch wheel: torch==$savedTorch"
        }
    }

    # 2. Fetch & inspect or apply update
    $updated = $false
    if ($Upstream) {
        Write-Step "Fetching upstream (wiltodelta/remove-ai-watermarks)"
        $hasUpstream = (& git remote 2>$null) -contains "upstream"
        if (-not $hasUpstream) {
            Write-Info "Adding 'upstream' remote -> $UpstreamUrl"
            & git remote add upstream $UpstreamUrl
        }
        & git fetch --tags upstream
        if ($LASTEXITCODE -ne 0) { throw "git fetch upstream failed." }

        $behind = [int](& git rev-list --count "HEAD..upstream/main")
        Write-Info "Commits behind upstream/main: $behind"

        if ($CheckOnly) {
            if ($behind -gt 0) {
                & git log --oneline -n 10 "HEAD..upstream/main"
            } else {
                Write-Ok "Already up to date with upstream/main."
            }
            exit 0
        }

        if ($behind -eq 0) {
            Write-Ok "Already up to date with upstream/main."
        } else {
            Write-Step "Merging upstream/main"
            & git merge --ff-only upstream/main 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Info "Fast-forward not possible (fork has local commits); performing merge..."
                & git merge --no-edit upstream/main
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn "Merge conflict detected; aborting merge cleanly to keep your workspace intact."
                    & git merge --abort 2>$null
                    Write-Host ""
                    Write-Host "Resolve manually with:" -ForegroundColor Yellow
                    Write-Host "  git merge upstream/main" -ForegroundColor White
                    exit 1
                }
            }
            $updated = $true
        }
    } else {
        $remotes = @(& git remote 2>$null)
        if ($remotes -notcontains "origin") {
            throw "No 'origin' remote is configured. Use '.\update.ps1 -Upstream' or add an 'origin' remote first."
        }
        Write-Step "Fetching origin ($currentBranch)"
        & git fetch --tags origin
        if ($LASTEXITCODE -ne 0) { throw "git fetch origin failed." }

        $targetRef = "origin/$currentBranch"
        $refCheck = (& git rev-parse --verify $targetRef 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $refCheck) {
            throw "Remote branch '$targetRef' not found."
        }

        $behind = [int](& git rev-list --count "HEAD..$targetRef")
        Write-Info "Commits behind ${targetRef}: $behind"

        if ($CheckOnly) {
            if ($behind -gt 0) {
                & git log --oneline -n 10 "HEAD..$targetRef"
            } else {
                Write-Ok "Already up to date with $targetRef."
            }
            exit 0
        }

        if ($behind -eq 0) {
            Write-Ok "Already up to date with $targetRef."
        } else {
            Write-Step "Pulling updates (--ff-only)"
            & git pull --ff-only origin $currentBranch
            if ($LASTEXITCODE -ne 0) {
                Write-Host ""
                Write-Host "Fast-forward pull failed (your local branch has diverged from $targetRef)." -ForegroundColor Red
                Write-Host "Reconcile with 'git pull --rebase' or 'git merge $targetRef'." -ForegroundColor Yellow
                exit 1
            }
            $updated = $true
        }
    }

    $newCommit = (& git rev-parse --short HEAD).Trim()
    if ($updated) {
        Write-Ok "Updated: $oldCommit -> $newCommit"
    }

    # 3. Sync Python dependencies & editable metadata while preserving GPU PyTorch wheel
    if (-not $SkipDeps -and (Test-Path $VenvPy)) {
        $UvCmd = Get-Command uv -ErrorAction SilentlyContinue
        $pyprojectChanged = $false
        if ($updated) {
            $changedFiles = @(& git diff --name-only $oldCommit $newCommit 2>$null)
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
            if ($UvCmd) {
                & $UvCmd.Source pip install --python $VenvPy @depArgs ".[studio,visible,video,heif,detect,lama,migan,source-classify]"
            } else {
                & $VenvPy -m pip install @depArgs ".[studio,visible,video,heif,detect,lama,migan,source-classify]"
            }

            # Verify GPU PyTorch wheel remained intact
            if ($savedTorch) {
                $afterTorch = (& $VenvPy -c "import torch; print(torch.__version__)" 2>$null)
                if ($afterTorch) { $afterTorch = $afterTorch.Trim() }
                if ($afterTorch -ne $savedTorch -and $torchIndex) {
                    Write-Warn "PyTorch changed ($savedTorch -> $afterTorch); restoring $savedTorch..."
                    $baseTorch = ($savedTorch -split "\+")[0]
                    $restoreSpecs = @("torch==$baseTorch")
                    if ($savedVision) {
                        $baseVision = ($savedVision -split "\+")[0]
                        $restoreSpecs += "torchvision==$baseVision"
                    }
                    if ($UvCmd) {
                        & $UvCmd.Source pip install --python $VenvPy --index-url $torchIndex --force-reinstall --no-deps @restoreSpecs
                    } else {
                        & $VenvPy -m pip install --index-url $torchIndex --force-reinstall --no-deps @restoreSpecs
                    }
                }
            }
        }

        Write-Step "Refreshing editable package metadata (--no-deps -e .)"
        if ($UvCmd) {
            & $UvCmd.Source pip install --python $VenvPy --no-deps -e .
        } else {
            & $VenvPy -m pip install --no-deps -e .
        }
        if ($LASTEXITCODE -ne 0) { throw "Editable install failed." }

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
        & $VenvPy -c $SelfCheck
        if ($LASTEXITCODE -ne 0) { throw "Self-check failed." }
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
    Pop-Location
}
