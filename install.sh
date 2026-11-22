#!/usr/bin/env bash
# Universal macOS & Linux installer for Remove AI Watermarks Studio.
# Auto-detects Apple Silicon (MPS), NVIDIA CUDA (Blackwell/RTX/GTX),
# AMD Radeon (ROCm), Intel Arc (XPU & OpenVINO), or CPU fallback.
#
# Usage:
#   ./install.sh
#   ./install.sh --backend auto|nvidia|nvidia-blackwell|amd-rocm|amd-dml|intel-xpu|intel-npu|apple-mps|cpu
#   ./install.sh --skip-deep-clean
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONUTF8=1
export HF_HUB_DISABLE_XET=1

BACKEND="auto"
SKIP_DEEP_CLEAN=0
PYTHON_BIN=""

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --backend <kind>    Hardware backend:
                        auto (default), nvidia, nvidia-blackwell, amd-rocm,
                        intel-xpu, intel-npu, apple-mps, cpu
  --skip-deep-clean   Install lightweight Quick Clean / Video / ONNX stack only
  --python <path>     Explicit Python 3.11-3.14 executable path
  -h, --help          Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)
      BACKEND="${2:?--backend requires a value}"
      shift 2
      ;;
    --skip-deep-clean)
      SKIP_DEEP_CLEAN=1
      shift
      ;;
    --python)
      PYTHON_BIN="${2:?--python requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$BACKEND" in
  auto|nvidia|nvidia-blackwell|amd-rocm|amd-dml|intel-xpu|intel-npu|apple-mps|cpu) ;;
  *)
    echo "Unsupported backend: $BACKEND" >&2
    usage >&2
    exit 2
    ;;
esac

step() { printf '\n==> %s\n' "$1"; }
info() { printf '    %s\n' "$1"; }
warn() { printf '    [warn] %s\n' "$1"; }

check_python_ver() {
  local exe="$1"
  "$exe" -c 'import sys; v=sys.version_info[:2]; sys.exit(0 if (3,11) <= v < (3,15) else 1)' 2>/dev/null
}

find_host_python() {
  if [[ -n "$PYTHON_BIN" ]]; then
    if check_python_ver "$PYTHON_BIN"; then
      echo "$PYTHON_BIN"
      return 0
    fi
    echo "Specified Python '$PYTHON_BIN' is not Python 3.11-3.14." >&2
    exit 1
  fi
  for cand in python3.12 python3.13 python3.11 python3.14 python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && check_python_ver "$cand"; then
      command -v "$cand"
      return 0
    fi
  done
  return 1
}

detect_hardware() {
  local os_name arch
  os_name="$(uname -s)"
  arch="$(uname -m)"

  if [[ "$os_name" == "Darwin" ]]; then
    if [[ "$arch" == "arm64" ]]; then
      echo "apple-mps"
    else
      echo "cpu"
    fi
    return 0
  fi

  # Linux detection
  if command -v nvidia-smi >/dev/null 2>&1; then
    local nv_names
    nv_names="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || true)"
    if [[ -n "$nv_names" ]]; then
      if echo "$nv_names" | grep -Eqi 'RTX[[:space:]]*50[0-9]{2}|RTX[[:space:]]*PRO.*Blackwell|B100|B200|GB200|Blackwell'; then
        echo "nvidia-blackwell"
      else
        echo "nvidia"
      fi
      return 0
    fi
  fi

  if command -v rocminfo >/dev/null 2>&1 || command -v rocm-smi >/dev/null 2>&1 || [[ -e /dev/kfd ]]; then
    echo "amd-rocm"
    return 0
  fi

  if command -v lspci >/dev/null 2>&1; then
    if lspci 2>/dev/null | grep -Eqi 'VGA|3D|Display' && lspci 2>/dev/null | grep -Eqi 'Intel.*(Arc|DG2|Battlemage|Meteor Lake|Lunar Lake|Arrow Lake)'; then
      echo "intel-xpu"
      return 0
    fi
  fi

  echo "cpu"
}

echo "============================================================"
echo "  Remove AI Watermarks Studio - Universal Installer"
echo "============================================================"

step "Checking Python / uv environment"
UV_BIN=""
if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
  info "Found uv: $UV_BIN"
fi

HOST_PY=""
if HOST_PY="$(find_host_python)"; then
  info "Found Python: $HOST_PY ($("$HOST_PY" --version 2>&1))"
fi

if [[ -z "$UV_BIN" && -z "$HOST_PY" ]]; then
  echo "" >&2
  echo "Neither 'uv' nor Python 3.11-3.14 was found." >&2
  echo "Install uv in one command, then re-run ./install.sh:" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "Or install Python 3.12 via Homebrew (macOS) or apt/dnf (Linux)." >&2
  exit 1
fi

step "Preparing virtual environment (.venv)"
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  if [[ -n "$UV_BIN" && -z "$PYTHON_BIN" ]]; then
    "$UV_BIN" venv "$VENV_DIR" --python 3.12 || "$HOST_PY" -m venv "$VENV_DIR"
  else
    "$HOST_PY" -m venv "$VENV_DIR"
  fi
  info "Created .venv"
else
  info "Using existing .venv ($VENV_PY)"
fi

pip_install() {
  if [[ -n "$UV_BIN" ]]; then
    "$UV_BIN" pip install --python "$VENV_PY" "$@"
  else
    "$VENV_PY" -m pip install "$@"
  fi
}

if [[ -z "$UV_BIN" ]]; then
  "$VENV_PY" -m pip install --upgrade pip wheel >/dev/null
fi

step "Detecting hardware accelerator"
if [[ "$BACKEND" == "auto" ]]; then
  SELECTED="$(detect_hardware)"
  info "Auto-detected backend: $SELECTED"
else
  SELECTED="$BACKEND"
  info "Using requested backend: $SELECTED"
fi

if [[ "$SELECTED" == "amd-dml" ]]; then
  warn "DirectML is Windows-only; using 'amd-rocm' on Linux or 'cpu' on macOS."
  if [[ "$(uname -s)" == "Linux" ]]; then
    SELECTED="amd-rocm"
  else
    SELECTED="cpu"
  fi
fi

step "Installing PyTorch & ONNX Runtime for '$SELECTED'"
TORCH_INDEX=""
TORCH_SPECS=()
EXPECTED_TAG=""
ONNX_PKG="onnxruntime>=1.24.0"

case "$SELECTED" in
  apple-mps)
    TORCH_SPECS=("torch>=2.6.0" "torchvision>=0.21.0")
    ONNX_PKG="onnxruntime>=1.24.0"
    info "Installing PyTorch (Apple Silicon MPS) + onnxruntime (CoreML EP built-in)."
    ;;
  nvidia-blackwell)
    TORCH_INDEX="https://download.pytorch.org/whl/cu128"
    TORCH_SPECS=("torch==2.11.0" "torchvision==0.26.0")
    EXPECTED_TAG="+cu128"
    ONNX_PKG="onnxruntime>=1.24.0"
    info "Pinning torch==2.11.0+cu128 & torchvision==0.26.0+cu128 (Blackwell-safe)."
    ;;
  nvidia)
    TORCH_INDEX="https://download.pytorch.org/whl/cu128"
    TORCH_SPECS=("torch==2.11.0" "torchvision==0.26.0")
    EXPECTED_TAG="+cu128"
    ONNX_PKG="onnxruntime>=1.24.0"
    info "Installing PyTorch CUDA 12.8 + onnxruntime."
    ;;
  amd-rocm)
    TORCH_INDEX="https://download.pytorch.org/whl/rocm6.2"
    TORCH_SPECS=("torch" "torchvision")
    EXPECTED_TAG="+rocm"
    ONNX_PKG="onnxruntime>=1.24.0"
    info "Installing PyTorch ROCm 6.2 + onnxruntime."
    ;;
  intel-xpu)
    TORCH_INDEX="https://download.pytorch.org/whl/xpu"
    TORCH_SPECS=("torch" "torchvision")
    EXPECTED_TAG="+xpu"
    ONNX_PKG="onnxruntime-openvino"
    info "Installing PyTorch Intel XPU + onnxruntime-openvino."
    ;;
  intel-npu)
    TORCH_INDEX="https://download.pytorch.org/whl/cpu"
    TORCH_SPECS=("torch" "torchvision")
    EXPECTED_TAG="+cpu"
    ONNX_PKG="onnxruntime-openvino"
    info "Installing PyTorch CPU + onnxruntime-openvino."
    ;;
  cpu)
    if [[ "$(uname -s)" == "Linux" ]]; then
      TORCH_INDEX="https://download.pytorch.org/whl/cpu"
      EXPECTED_TAG="+cpu"
    fi
    TORCH_SPECS=("torch" "torchvision")
    ONNX_PKG="onnxruntime>=1.24.0"
    info "Installing CPU-only PyTorch + onnxruntime."
    ;;
esac

if [[ "$SKIP_DEEP_CLEAN" -eq 0 ]]; then
  if [[ -n "$TORCH_INDEX" ]]; then
    pip_install --index-url "$TORCH_INDEX" "${TORCH_SPECS[@]}"
  else
    pip_install "${TORCH_SPECS[@]}"
  fi
else
  info "Skipping PyTorch Deep Clean stack (--skip-deep-clean)."
fi

if ! pip_install "$ONNX_PKG"; then
  warn "Failed to install '$ONNX_PKG'; falling back to standard 'onnxruntime'."
  pip_install "onnxruntime>=1.24.0"
fi

step "Installing Remove AI Watermarks Studio dependencies"
if [[ "$SKIP_DEEP_CLEAN" -eq 1 ]]; then
  EXTRAS="studio,visible,video,heif,detect,lama,migan,source-classify"
else
  EXTRAS="studio,visible,video,heif,detect,lama,migan,source-classify,qwen-zimage"
fi

DEP_ARGS=()
if [[ -n "$TORCH_INDEX" ]]; then
  DEP_ARGS+=(--extra-index-url "$TORCH_INDEX")
fi

pip_install "${DEP_ARGS[@]}" "fastapi>=0.115.0" "uvicorn>=0.32.0" "python-multipart>=0.0.18"
pip_install "${DEP_ARGS[@]}" ".[${EXTRAS}]"

# Verify GPU PyTorch wheel was preserved
if [[ "$SKIP_DEEP_CLEAN" -eq 0 && -n "$EXPECTED_TAG" && -n "$TORCH_INDEX" ]]; then
  CUR_TORCH="$("$VENV_PY" -c 'import torch; print(torch.__version__)' 2>/dev/null || true)"
  if [[ "$CUR_TORCH" != *"$EXPECTED_TAG"* ]]; then
    warn "PyTorch wheel changed to '$CUR_TORCH'; restoring '$EXPECTED_TAG' build..."
    pip_install --index-url "$TORCH_INDEX" --force-reinstall --no-deps "${TORCH_SPECS[@]}"
  fi
fi

step "Registering editable package (--no-deps -e .)"
pip_install --no-deps -e .

step "Checking Studio settings & script permissions"
if [[ ! -f "$SCRIPT_DIR/webapp/settings.json" && -f "$SCRIPT_DIR/webapp/settings.example.json" ]]; then
  cp "$SCRIPT_DIR/webapp/settings.example.json" "$SCRIPT_DIR/webapp/settings.json"
  info "Created webapp/settings.json from settings.example.json"
else
  info "Keeping existing webapp/settings.json"
fi

chmod +x "$SCRIPT_DIR/run_webapp.sh" "$SCRIPT_DIR/update.sh" "$SCRIPT_DIR/install.sh" 2>/dev/null || true

step "Verifying installation & hardware summary"
"$VENV_PY" - <<'PY'
import remove_ai_watermarks as raiw
print("Package version :", getattr(raiw, "__version__", "installed"))
try:
    import torch
    print("PyTorch         :", torch.__version__)
except Exception:
    print("PyTorch         : not installed (Quick Clean mode)")
try:
    from remove_ai_watermarks._internal.accelerator import detect_hardware_summary
    hw = detect_hardware_summary()
    print("Accelerator     :", hw.get("accelerator_kind"), "|", hw.get("device_name"))
    print("ONNX Provider   :", hw.get("active_onnx_provider"))
    if hw.get("npu_detected"):
        print("AI NPU          : detected")
except Exception as exc:
    print(f"Hardware probe  : basic mode ({exc})")
PY

echo ""
echo "============================================================"
echo "  Installation complete!"
echo "  Launch Studio : ./run_webapp.sh --open"
echo "  Update later  : ./update.sh"
echo "============================================================"
