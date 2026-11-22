#!/usr/bin/env bash
# Safe 1-click GitHub & upstream updater for Remove AI Watermarks Studio (macOS/Linux).
# Features automatic network retries with exponential backoff, optional --auto-stash,
# and full protection for your installed GPU PyTorch wheel (cu128 / xpu / rocm / mps).
#
# Usage:
#   ./update.sh                 # Pull latest updates from origin
#   ./update.sh --upstream      # Sync from wiltodelta/remove-ai-watermarks
#   ./update.sh --check         # Check for updates without modifying files
#   ./update.sh --auto-stash    # Temporarily stash local tracked changes & restore after
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONUTF8=1
export HF_HUB_DISABLE_XET=1
export GIT_TERMINAL_PROMPT=0
export GCM_INTERACTIVE=never

UPSTREAM=0
CHECK_ONLY=0
SKIP_DEPS=0
AUTO_STASH=0
RETRIES=3
BRANCH=""
STASHED=0
UPSTREAM_URL="https://github.com/wiltodelta/remove-ai-watermarks.git"

usage() {
  cat <<'EOF'
Usage: ./update.sh [options]

Options:
  --upstream        Sync latest changes from wiltodelta/remove-ai-watermarks
  --check           Check for available updates without modifying files
  --branch <name>   Branch to pull from origin (default: current branch)
  --auto-stash      Auto-stash tracked local changes before updating & restore after
  --retries <N>     Number of network retry attempts (default: 3)
  --skip-deps       Skip Python dependency & editable metadata refresh
  -h, --help        Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upstream)
      UPSTREAM=1
      shift
      ;;
    --check)
      CHECK_ONLY=1
      shift
      ;;
    --branch)
      BRANCH="${2:?--branch requires a value}"
      shift 2
      ;;
    --auto-stash)
      AUTO_STASH=1
      shift
      ;;
    --retries)
      RETRIES="${2:?--retries requires a value}"
      shift 2
      ;;
    --skip-deps)
      SKIP_DEPS=1
      shift
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

step() { printf '\n==> %s\n' "$1"; }
info() { printf '    %s\n' "$1"; }
warn() { printf '    [warn] %s\n' "$1"; }

cleanup_stash() {
  if [[ "$STASHED" -eq 1 ]]; then
    step "Restoring auto-stashed local changes"
    if git stash pop; then
      info "Local changes restored cleanly."
    else
      warn "git stash pop reported conflicts; your edits remain safely saved in 'git stash list'."
    fi
  fi
}
trap cleanup_stash EXIT

retry_cmd() {
  local label="$1"
  shift
  local attempt=1
  local delay=2
  while true; do
    if "$@"; then
      if [[ "$attempt" -gt 1 ]]; then
        info "[ok] $label succeeded on attempt $attempt/$RETRIES."
      fi
      return 0
    fi
    if [[ "$attempt" -ge "$RETRIES" ]]; then
      echo "    [error] $label failed after $RETRIES attempts." >&2
      return 1
    fi
    warn "$label failed (attempt $attempt/$RETRIES). Retrying in ${delay}s..."
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

torch_index_for_tag() {
  local ver="$1"
  if [[ "$ver" =~ \+(cu[0-9]+) ]]; then
    echo "https://download.pytorch.org/whl/${BASH_REMATCH[1]}"
  elif [[ "$ver" == *"+xpu"* ]]; then
    echo "https://download.pytorch.org/whl/xpu"
  elif [[ "$ver" =~ \+(rocm[0-9.]+) ]]; then
    echo "https://download.pytorch.org/whl/${BASH_REMATCH[1]}"
  elif [[ "$ver" == *"+cpu"* ]]; then
    echo "https://download.pytorch.org/whl/cpu"
  else
    echo ""
  fi
}

echo "============================================================"
echo "  Remove AI Watermarks Studio - GitHub Updater"
echo "============================================================"

if ! command -v git >/dev/null 2>&1; then
  echo "Git is not installed." >&2
  exit 1
fi

if [[ "$(git rev-parse --is-inside-work-tree 2>/dev/null || true)" != "true" ]]; then
  echo "This directory is not a Git repository." >&2
  exit 1
fi

step "Checking repository state"
DIRTY="$(git status --porcelain --untracked-files=no)"
if [[ -n "$DIRTY" ]]; then
  if [[ "$AUTO_STASH" -eq 1 && "$CHECK_ONLY" -eq 0 ]]; then
    warn "Uncommitted tracked changes detected; stashing cleanly (--auto-stash)..."
    git stash push -m "studio-auto-update"
    STASHED=1
  else
    echo "" >&2
    echo "Update aborted: you have uncommitted changes to tracked files:" >&2
    echo "$DIRTY" >&2
    echo "" >&2
    echo "Save/discard them or pass --auto-stash to temporarily shelve changes." >&2
    exit 1
  fi
fi

CURRENT_BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
if [[ -z "$CURRENT_BRANCH" || "$CURRENT_BRANCH" == "HEAD" ]]; then
  echo "Repository is in detached HEAD state. Checkout a branch first." >&2
  exit 1
fi
OLD_COMMIT="$(git rev-parse --short HEAD)"
info "Branch: $CURRENT_BRANCH  |  Commit: $OLD_COMMIT  |  Max retries: $RETRIES"

VENV_PY=""
if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  VENV_PY="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]]; then
  VENV_PY="$SCRIPT_DIR/.venv/Scripts/python.exe"
fi

SAVED_TORCH=""
SAVED_VISION=""
if [[ -n "$VENV_PY" ]]; then
  SAVED_TORCH="$("$VENV_PY" -c 'import torch; print(torch.__version__)' 2>/dev/null || true)"
  SAVED_VISION="$("$VENV_PY" -c 'import torchvision; print(torchvision.__version__)' 2>/dev/null || true)"
  if [[ -n "$SAVED_TORCH" ]]; then
    info "Protected PyTorch wheel: torch==$SAVED_TORCH"
  fi
fi

NET_GIT_OPTS=(-c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20)
UPDATED=0

if [[ "$UPSTREAM" -eq 1 ]]; then
  step "Fetching upstream (wiltodelta/remove-ai-watermarks)"
  if ! git remote | grep -qx 'upstream'; then
    info "Adding 'upstream' remote -> $UPSTREAM_URL"
    git remote add upstream "$UPSTREAM_URL"
  fi
  retry_cmd "git fetch upstream" git "${NET_GIT_OPTS[@]}" fetch --tags upstream
  UPSTREAM_REF="upstream/main"
  if ! git rev-parse --verify --quiet "$UPSTREAM_REF" >/dev/null 2>&1; then
    UPSTREAM_REF="upstream/master"
  fi
  BEHIND="$(git rev-list --count "HEAD..$UPSTREAM_REF")"
  info "Commits behind ${UPSTREAM_REF}: $BEHIND"

  if [[ "$CHECK_ONLY" -eq 1 ]]; then
    if [[ "$BEHIND" -gt 0 ]]; then
      git log --oneline -n 10 "HEAD..$UPSTREAM_REF"
    else
      info "Already up to date with $UPSTREAM_REF."
    fi
    exit 0
  fi

  if [[ "$BEHIND" -gt 0 ]]; then
    step "Merging $UPSTREAM_REF"
    if ! git merge --ff-only "$UPSTREAM_REF" 2>/dev/null; then
      info "Fast-forward not possible (fork has local commits); performing merge..."
      if ! git merge --no-edit "$UPSTREAM_REF"; then
        warn "Merge conflict detected; aborting merge cleanly."
        git merge --abort 2>/dev/null || true
        echo "Resolve manually with: git merge $UPSTREAM_REF" >&2
        exit 1
      fi
    fi
    UPDATED=1
  else
    info "Already up to date with $UPSTREAM_REF."
  fi
else
  if ! git remote | grep -qx 'origin'; then
    echo "No 'origin' remote configured. Run './update.sh --upstream' or add an 'origin' remote." >&2
    exit 1
  fi
  step "Fetching origin ($CURRENT_BRANCH)"
  retry_cmd "git fetch origin" git "${NET_GIT_OPTS[@]}" fetch --tags origin
  TARGET_REF="origin/$CURRENT_BRANCH"
  if ! git rev-parse --verify --quiet "$TARGET_REF" >/dev/null 2>&1; then
    echo "Remote branch '$TARGET_REF' not found." >&2
    exit 1
  fi

  BEHIND="$(git rev-list --count "HEAD..$TARGET_REF")"
  info "Commits behind ${TARGET_REF}: $BEHIND"

  if [[ "$CHECK_ONLY" -eq 1 ]]; then
    if [[ "$BEHIND" -gt 0 ]]; then
      git log --oneline -n 10 "HEAD..$TARGET_REF"
    else
      info "Already up to date with $TARGET_REF."
    fi
    exit 0
  fi

  if [[ "$BEHIND" -gt 0 ]]; then
    step "Applying updates locally (--ff-only from fetched $TARGET_REF)"
    if ! git merge --ff-only "$TARGET_REF"; then
      echo "Fast-forward merge failed (branch diverged from $TARGET_REF)." >&2
      echo "Reconcile manually with 'git pull --rebase' or 'git merge $TARGET_REF'." >&2
      exit 1
    fi
    UPDATED=1
  else
    info "Already up to date with $TARGET_REF."
  fi
fi

NEW_COMMIT="$(git rev-parse --short HEAD)"
if [[ "$UPDATED" -eq 1 ]]; then
  info "Updated: $OLD_COMMIT -> $NEW_COMMIT"
fi

if [[ "$SKIP_DEPS" -eq 0 && -n "$VENV_PY" ]]; then
  UV_BIN=""
  if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
  fi

  pip_install() {
    if [[ -n "$UV_BIN" ]]; then
      "$UV_BIN" pip install --python "$VENV_PY" "$@"
    else
      "$VENV_PY" -m pip install "$@"
    fi
  }

  if [[ "$UPDATED" -eq 1 ]] && git diff --name-only "$OLD_COMMIT" "$NEW_COMMIT" | grep -qx 'pyproject.toml'; then
    step "pyproject.toml changed; syncing dependencies (preserving PyTorch wheel)"
    TORCH_INDEX="$(torch_index_for_tag "$SAVED_TORCH")"
    DEP_ARGS=()
    if [[ -n "$TORCH_INDEX" ]]; then
      DEP_ARGS+=(--extra-index-url "$TORCH_INDEX")
    fi
    retry_cmd "dependency sync" pip_install "${DEP_ARGS[@]}" ".[studio,visible,video,heif,detect,lama,migan,source-classify]" || warn "Dependency sync failed; keeping existing packages."

    if [[ -n "$SAVED_TORCH" && -n "$TORCH_INDEX" ]]; then
      AFTER_TORCH="$("$VENV_PY" -c 'import torch; print(torch.__version__)' 2>/dev/null || true)"
      if [[ "$AFTER_TORCH" != "$SAVED_TORCH" ]]; then
        warn "PyTorch changed ($SAVED_TORCH -> $AFTER_TORCH); restoring $SAVED_TORCH..."
        BASE_TORCH="${SAVED_TORCH%%+*}"
        RESTORE_SPECS=("torch==${BASE_TORCH}")
        if [[ -n "$SAVED_VISION" ]]; then
          BASE_VISION="${SAVED_VISION%%+*}"
          RESTORE_SPECS+=("torchvision==${BASE_VISION}")
        fi
        retry_cmd "restore PyTorch wheel" pip_install --index-url "$TORCH_INDEX" --force-reinstall --no-deps "${RESTORE_SPECS[@]}"
      fi
    fi
  fi

  step "Refreshing editable package metadata (--no-deps -e .)"
  retry_cmd "editable install" pip_install --no-deps -e .

  step "Running self-check"
  "$VENV_PY" - <<'PY'
import remove_ai_watermarks as raiw
print("Version         :", getattr(raiw, "__version__", "installed"))
try:
    import torch
    print("PyTorch         :", torch.__version__)
except Exception:
    print("PyTorch         : not installed")
try:
    from remove_ai_watermarks._internal.accelerator import detect_hardware_summary
    hw = detect_hardware_summary()
    print("Accelerator     :", hw.get("accelerator_kind"), "|", hw.get("device_name"))
    print("ONNX Provider   :", hw.get("active_onnx_provider"))
except Exception:
    pass
PY
elif [[ -z "$VENV_PY" ]]; then
  warn "No .venv found. Run ./install.sh to install dependencies."
fi

echo ""
if [[ "$UPDATED" -eq 1 ]]; then
  echo "Update complete ($OLD_COMMIT -> $NEW_COMMIT). Restart Remove AI Watermarks Studio if it is running."
else
  echo "Everything is up to date ($NEW_COMMIT)."
fi
