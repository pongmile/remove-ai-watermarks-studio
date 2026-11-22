<#
.SYNOPSIS
    Universal Windows installer for Remove AI Watermarks Studio.
    Auto-detects NVIDIA (Blackwell/RTX/GTX), AMD Radeon (DirectML), Intel Arc /
    Core Ultra (XPU & OpenVINO NPU), Qualcomm / Ryzen AI NPU, or CPU-only.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Backend nvidia-blackwell
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Backend amd-dml
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Backend intel-xpu
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Backend cpu -SkipDeepClean
#>
[CmdletBinding()]
param(
    [ValidateSet("auto", "nvidia", "nvidia-blackwell", "amd-rocm", "amd-dml", "intel-xpu", "intel-npu", "apple-mps", "cpu")]
    [string]$Backend = "auto",

    [switch]$SkipDeepClean,

    [switch]$NoShortcut,

    [switch]$Yes,

    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:HF_HUB_DISABLE_XET = "1"

$Root = $PSScriptRoot
$VenvDir = Join-Path $Root ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"

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

function Test-PythonVersion([string]$Exe, [string[]]$PrefixArgs = @()) {
    try {
        $ver = & $Exe @PrefixArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $ver) { return $null }
        $v = [version]$ver.Trim()
        if ($v -ge [version]"3.11" -and $v -lt [version]"3.15") {
            return $ver.Trim()
        }
    } catch {}
    return $null
}

function Find-HostPython {
    if ($Python) {
        $v = Test-PythonVersion $Python
        if ($v) { return @{ Exe = $Python; Args = @(); Version = $v } }
        throw "Specified Python '$Python' is not Python 3.11-3.14."
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($minor in @("3.12", "3.13", "3.11", "3.14")) {
            $v = Test-PythonVersion "py" @("-$minor")
            if ($v) { return @{ Exe = "py"; Args = @("-$minor"); Version = $v } }
        }
    }

    foreach ($cand in @("python", "python3")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) {
            $v = Test-PythonVersion $cmd.Source
            if ($v) { return @{ Exe = $cmd.Source; Args = @(); Version = $v } }
        }
    }
    return $null
}

function Detect-WindowsHardware {
    $result = @{
        Backend     = "cpu"
        Summary     = "CPU only"
        HasNpu      = $false
        NpuName     = ""
        IsArm64     = ($env:PROCESSOR_ARCHITECTURE -eq "ARM64")
        GpuNames    = @()
    }

    # 1. Check NVIDIA GPU via nvidia-smi
    $nvSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvSmi) {
        try {
            $nvOut = & $nvSmi.Source --query-gpu=name --format=csv,noheader 2>$null
            if ($LASTEXITCODE -eq 0 -and $nvOut) {
                $names = @($nvOut | ForEach-Object { $_.Trim() } | Where-Object { $_ })
                if ($names.Count -gt 0) {
                    $result.GpuNames = $names
                    $joined = ($names -join ", ")
                    if ($joined -match "RTX\s*50\d\d|RTX\s*PRO.*Blackwell|B100|B200|GB200|Blackwell") {
                        $result.Backend = "nvidia-blackwell"
                        $result.Summary = "NVIDIA Blackwell ($joined)"
                    } else {
                        $result.Backend = "nvidia"
                        $result.Summary = "NVIDIA CUDA ($joined)"
                    }
                    return $result
                }
            }
        } catch {}
    }

    # 2. Query Windows Video Controllers & PnP NPU devices
    $gpus = @()
    try {
        $gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Name |
            Where-Object { $_ -and $_ -notmatch "Microsoft Basic Display|Remote Desktop|Virtual|Parsec|Citrix" })
    } catch {}
    $result.GpuNames = $gpus

    try {
        $npus = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "AI Boost|NPU|Neural Processing|Ryzen AI|Hexagon|IPU" } |
            Select-Object -ExpandProperty Name)
        if ($npus.Count -gt 0) {
            $result.HasNpu = $true
            $result.NpuName = ($npus | Select-Object -First 1)
        }
    } catch {}

    $gpuJoined = ($gpus -join "; ")
    if ($gpuJoined -match "NVIDIA") {
        if ($gpuJoined -match "RTX\s*50\d\d|Blackwell") {
            $result.Backend = "nvidia-blackwell"
            $result.Summary = "NVIDIA Blackwell ($gpuJoined)"
        } else {
            $result.Backend = "nvidia"
            $result.Summary = "NVIDIA CUDA ($gpuJoined)"
        }
        return $result
    }

    if ($gpuJoined -match "AMD|Radeon") {
        $result.Backend = "amd-dml"
        $result.Summary = "AMD Radeon via DirectML ($gpuJoined)"
        return $result
    }

    if ($gpuJoined -match "Intel.*Arc|Intel.*Graphics.*Core Ultra|Intel.*Xe") {
        $result.Backend = "intel-xpu"
        $result.Summary = "Intel Arc / Xe GPU ($gpuJoined)"
        return $result
    }

    if ($result.HasNpu -and $result.NpuName -match "Intel|AI Boost") {
        $result.Backend = "intel-npu"
        $result.Summary = "Intel Core Ultra NPU ($($result.NpuName))"
        return $result
    }

    if ($result.HasNpu -or ($gpuJoined -match "Qualcomm|Adreno")) {
        $result.Backend = "amd-dml"
        $result.Summary = if ($result.NpuName) { "Windows AI NPU / DirectML ($($result.NpuName))" } else { "Qualcomm / DirectML ($gpuJoined)" }
        return $result
    }

    return $result
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Remove AI Watermarks Studio - Universal Windows Installer" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Step 1: Detect uv or Python 3.11-3.14
Write-Step "Checking Python / uv environment"
$UvCmd = Get-Command uv -ErrorAction SilentlyContinue
$HostPy = Find-HostPython

if (-not $UvCmd -and -not $HostPy) {
    Write-Host ""
    Write-Host "Neither 'uv' nor Python 3.11-3.14 was found on PATH." -ForegroundColor Red
    Write-Host "Install one of them in a single command, then re-run .\install.ps1:" -ForegroundColor Yellow
    Write-Host "  Option A (fastest, recommended):  winget install --id astral-sh.uv -e" -ForegroundColor White
    Write-Host "  Option B (Python 3.12):           winget install --id Python.Python.3.12 -e" -ForegroundColor White
    exit 1
}

if ($UvCmd) {
    Write-Ok "Found uv: $($UvCmd.Source)"
}
if ($HostPy) {
    Write-Ok "Found Python $($HostPy.Version): $($HostPy.Exe)"
}

# Step 2: Create virtual environment
Write-Step "Preparing virtual environment (.venv)"
if (-not (Test-Path $VenvPy)) {
    if ($UvCmd -and -not $Python) {
        & $UvCmd.Source venv $VenvDir --python 3.12
        if ($LASTEXITCODE -ne 0) {
            if ($HostPy) {
                & $HostPy.Exe @($HostPy.Args) -m venv $VenvDir
            } else {
                throw "Failed to create .venv with uv."
            }
        }
    } else {
        & $HostPy.Exe @($HostPy.Args) -m venv $VenvDir
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) {
        throw "Failed to create virtual environment at $VenvDir"
    }
    Write-Ok "Created .venv"
} else {
    Write-Ok "Using existing .venv ($VenvPy)"
}

function Invoke-Pip {
    param([string[]]$Arguments)
    if ($UvCmd) {
        & $UvCmd.Source pip install --python $VenvPy @Arguments
    } else {
        & $VenvPy -m pip install @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Package installation failed: $($Arguments -join ' ')"
    }
}

if (-not $UvCmd) {
    & $VenvPy -m pip install --upgrade pip wheel | Out-Null
}

# Step 3: Hardware detection
Write-Step "Detecting hardware accelerator"
$Detected = Detect-WindowsHardware
if ($Backend -eq "auto") {
    $SelectedBackend = $Detected.Backend
    Write-Ok "Auto-detected: $($Detected.Summary) -> backend '$SelectedBackend'"
    if ($Detected.HasNpu) {
        Write-Info "AI NPU detected: $($Detected.NpuName)"
    }
} else {
    $SelectedBackend = $Backend
    Write-Ok "Using requested backend: '$SelectedBackend' (detected: $($Detected.Summary))"
}

if ($SelectedBackend -eq "apple-mps") {
    Write-Warn "apple-mps is macOS Apple Silicon only; falling back to 'cpu' on Windows."
    $SelectedBackend = "cpu"
}

# Step 4: Install PyTorch + ONNX Runtime for target backend
Write-Step "Installing PyTorch & ONNX Runtime for '$SelectedBackend'"
$TorchIndexUrl = ""
$TorchSpecs = @()
$ExpectedTorchTag = ""
$OnnxPkg = "onnxruntime>=1.24.0"

switch ($SelectedBackend) {
    "nvidia-blackwell" {
        # Battle-tested cu128 wheel avoids cu130 Z-Image Blackwell segfault (0xC0000005).
        $TorchIndexUrl = "https://download.pytorch.org/whl/cu128"
        $TorchSpecs = @("torch==2.11.0", "torchvision==0.26.0")
        $ExpectedTorchTag = "+cu128"
        $OnnxPkg = "onnxruntime>=1.24.0"
        Write-Info "Pinning torch==2.11.0+cu128 & torchvision==0.26.0+cu128 (Blackwell-safe)."
    }
    "nvidia" {
        $TorchIndexUrl = "https://download.pytorch.org/whl/cu128"
        $TorchSpecs = @("torch==2.11.0", "torchvision==0.26.0")
        $ExpectedTorchTag = "+cu128"
        $OnnxPkg = "onnxruntime>=1.24.0"
        Write-Info "Installing CUDA 12.8 PyTorch (supports RTX 20/30/40/50 & GTX 10/16)."
    }
    "amd-rocm" {
        Write-Warn "Native PyTorch ROCm wheels are primarily for Linux/WSL2."
        Write-Warn "Installing DirectML stack (torch-directml + onnxruntime-directml) for native Windows AMD GPU acceleration."
        $TorchSpecs = @("torch-directml", "torchvision")
        $OnnxPkg = "onnxruntime-directml"
    }
    "amd-dml" {
        $TorchSpecs = @("torch-directml", "torchvision")
        if ($Detected.IsArm64) {
            $OnnxPkg = "onnxruntime-qnn"
            Write-Info "ARM64 Windows detected: installing onnxruntime-qnn for Qualcomm NPU acceleration."
        } else {
            $OnnxPkg = "onnxruntime-directml"
            Write-Info "Installing torch-directml + onnxruntime-directml for Windows AMD / DirectML acceleration."
        }
    }
    "intel-xpu" {
        $TorchIndexUrl = "https://download.pytorch.org/whl/xpu"
        $TorchSpecs = @("torch", "torchvision")
        $ExpectedTorchTag = "+xpu"
        $OnnxPkg = "onnxruntime-openvino"
        Write-Info "Installing PyTorch Intel XPU + onnxruntime-openvino (Intel Arc GPU & Core Ultra NPU)."
    }
    "intel-npu" {
        $TorchIndexUrl = "https://download.pytorch.org/whl/cpu"
        $TorchSpecs = @("torch", "torchvision")
        $ExpectedTorchTag = "+cpu"
        $OnnxPkg = "onnxruntime-openvino"
        Write-Info "Installing PyTorch CPU + onnxruntime-openvino (Intel Core Ultra NPU acceleration for ONNX)."
    }
    default {
        $TorchIndexUrl = "https://download.pytorch.org/whl/cpu"
        $TorchSpecs = @("torch", "torchvision")
        $ExpectedTorchTag = "+cpu"
        $OnnxPkg = "onnxruntime>=1.24.0"
        Write-Info "Installing CPU-only PyTorch + onnxruntime."
    }
}

if (-not $SkipDeepClean) {
    if ($TorchIndexUrl) {
        Invoke-Pip (@("--index-url", $TorchIndexUrl) + $TorchSpecs)
    } else {
        Invoke-Pip $TorchSpecs
    }
} else {
    Write-Info "Skipping PyTorch Deep Clean stack (-SkipDeepClean)."
}

try {
    Invoke-Pip @($OnnxPkg)
} catch {
    Write-Warn "Failed to install '$OnnxPkg'; falling back to standard 'onnxruntime'."
    Invoke-Pip @("onnxruntime>=1.24.0")
}

# Step 5: Install Studio & feature extras without overwriting GPU PyTorch
Write-Step "Installing Remove AI Watermarks Studio dependencies"
$Extras = if ($SkipDeepClean) {
    "studio,visible,video,heif,detect,lama,migan,source-classify"
} else {
    "studio,visible,video,heif,detect,lama,migan,source-classify,qwen-zimage"
}

$DepArgs = @()
if ($TorchIndexUrl) {
    $DepArgs += @("--extra-index-url", $TorchIndexUrl)
}
# Ensure web server runtime is always installed even before extras sync
Invoke-Pip ($DepArgs + @("fastapi>=0.115.0", "uvicorn>=0.32.0", "python-multipart>=0.0.18"))

Push-Location $Root
try {
    Invoke-Pip ($DepArgs + @(".[$Extras]"))
} finally {
    Pop-Location
}

# Verify GPU PyTorch wheel was not replaced by a CPU/cu130 build
if (-not $SkipDeepClean -and $ExpectedTorchTag -and $TorchIndexUrl) {
    $curTorch = (& $VenvPy -c "import torch; print(torch.__version__)" 2>$null)
    if (-not $curTorch -or ($curTorch.Trim() -notlike "*$ExpectedTorchTag*")) {
        Write-Warn "PyTorch wheel changed to '$curTorch'; restoring '$ExpectedTorchTag' build..."
        Invoke-Pip (@("--index-url", $TorchIndexUrl, "--force-reinstall", "--no-deps") + $TorchSpecs)
    }
}

# Final editable install with --no-deps so PyTorch is NEVER touched
Write-Step "Registering editable package (--no-deps -e .)"
Push-Location $Root
try {
    Invoke-Pip @("--no-deps", "-e", ".")
} finally {
    Pop-Location
}

# Step 6: Create webapp/settings.json if missing
Write-Step "Checking Studio settings"
$SettingsPath = Join-Path $Root "webapp\settings.json"
$SettingsExample = Join-Path $Root "webapp\settings.example.json"
if (-not (Test-Path $SettingsPath) -and (Test-Path $SettingsExample)) {
    Copy-Item $SettingsExample $SettingsPath
    Write-Ok "Created webapp\settings.json from settings.example.json"
} else {
    Write-Ok "Keeping existing webapp\settings.json"
}

# Step 7: Quick self-check
Write-Step "Verifying installation & hardware summary"
$CheckScript = @"
import remove_ai_watermarks as raiw
print('Package version :', getattr(raiw, '__version__', 'installed'))
try:
    import torch
    print('PyTorch         :', torch.__version__)
except Exception:
    print('PyTorch         : not installed (Quick Clean mode)')
try:
    from remove_ai_watermarks._internal.accelerator import detect_hardware_summary
    hw = detect_hardware_summary()
    print('Accelerator     :', hw.get('accelerator_kind'), '|', hw.get('device_name'))
    print('ONNX Provider   :', hw.get('active_onnx_provider'))
    if hw.get('npu_detected'):
        print('AI NPU          : detected')
except Exception as exc:
    print('Hardware probe  : basic mode (' + str(exc) + ')')
"@
& $VenvPy -c $CheckScript

# Step 8: Optional Desktop shortcut
if (-not $NoShortcut) {
    $ShortcutScript = Join-Path $Root "make_shortcut.ps1"
    if (Test-Path $ShortcutScript) {
        $createShortcut = $Yes.IsPresent
        if (-not $createShortcut) {
            Write-Host ""
            $ans = Read-Host "Create a Desktop shortcut 'Remove AI Watermarks Studio'? [Y/n]"
            if ([string]::IsNullOrWhiteSpace($ans) -or $ans -match "^[Yy]") {
                $createShortcut = $true
            }
        }
        if ($createShortcut) {
            & $ShortcutScript
        }
    }
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "  Launch Studio : double-click 'Start Studio.cmd'" -ForegroundColor White
Write-Host "                  or run .\run_webapp.ps1" -ForegroundColor White
Write-Host "  Update later  : double-click 'Update Studio.cmd'" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green
