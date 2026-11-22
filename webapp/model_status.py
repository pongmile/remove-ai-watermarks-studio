"""Model inventory, download progress, and storage manager for the web app.

Tracks both:
  1. Lightweight local ONNX models (~295 MB total):
     - MI-GAN (~28 MB): ultra-fast learned visible-watermark & region inpainting
     - big-LaMa (~208 MB): highest-quality learned inpainting (textures, 16-bit)
     - Source Classify v8 (~59 MB): 10-provider AI source/version + synthetic detector
  2. Deep-clean diffusion profiles (Universal GPU / CPU):
     - sdxl-zimage   : Lightest & fastest (~10 GB fp16 global, works on CUDA/ROCm/XPU/MPS/DirectML/CPU)
     - qwen21-zimage : Smarter 7B + texture-fix VAE + guarded LPIPS/MSE fidelity (~41 GB, personal/research)
     - qwen-zimage   : Apache-2.0 20B Qwen-Image-2512 + Canny + Lightning (~57 GB)
     - chroma-zimage : Apache-2.0 FLUX-family Chroma1-HD (~28 GB; needs >=24 GB VRAM)
     - auto          : Smart commercial-safe router (Google->SDXL, OpenAI/Meta/Unknown->Qwen-2512,
                       Microsoft->Chroma1 when >=24 GB VRAM)

All model IDs are imported directly from the installed ``remove_ai_watermarks``
library with safe fallbacks so metadata-only environments never fail on import.
"""

from __future__ import annotations

import contextlib
import copy
import fnmatch
import json
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- Optional upstream imports with safe fallbacks ---------------------------

try:
    from remove_ai_watermarks._internal.chroma_zimage_pipeline import CHROMA_MODEL_ID
except Exception:
    CHROMA_MODEL_ID = "lodestones/Chroma1-HD"

try:
    from remove_ai_watermarks._internal.qwen_zimage_pipeline import (
        QWEN21_CANNY_CONTROLNET_MODEL_ID,
        QWEN21_CANNY_CONTROLNET_PATTERN,
        QWEN21_TEXTURE_FIX_VAE_FILENAME,
        QWEN21_TEXTURE_FIX_VAE_MODEL_ID,
        QWEN_CANNY_CONTROLNET_MODEL_ID,
        QWEN_IMAGE_21_MODEL_ID,
        QWEN_IMAGE_2512_MODEL_ID,
        QWEN_LIGHTNING_MODEL_ID,
        QWEN_LIGHTNING_PATTERN,
    )
except Exception:
    QWEN_IMAGE_2512_MODEL_ID = "Qwen/Qwen-Image-2512"
    QWEN_IMAGE_21_MODEL_ID = "Qwen/Qwen-Image-2.1"
    QWEN21_TEXTURE_FIX_VAE_MODEL_ID = "Qwen/Qwen-Image-2.1-Texture-Fix-VAE"
    QWEN21_TEXTURE_FIX_VAE_FILENAME = "diffusion_pytorch_model.safetensors"
    QWEN21_CANNY_CONTROLNET_MODEL_ID = "alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union"
    QWEN21_CANNY_CONTROLNET_PATTERN = "*.safetensors"
    QWEN_CANNY_CONTROLNET_MODEL_ID = "InstantX/Qwen-Image-ControlNet-Union"
    QWEN_LIGHTNING_MODEL_ID = "lightx2v/Qwen-Image-Lightning"
    QWEN_LIGHTNING_PATTERN = "Qwen-Image-Lightning-4steps-V1.0.safetensors"

try:
    from remove_ai_watermarks._internal.sdxl_zimage_pipeline import SDXL_VAE_MODEL_ID
except Exception:
    SDXL_VAE_MODEL_ID = "madebyollin/sdxl-vae-fp16-fix"

try:
    from remove_ai_watermarks._internal.two_stage_pipeline import (
        SAM_MODEL_ID,
        ZIMAGE_TURBO_MODEL_ID,
    )
except Exception:
    ZIMAGE_TURBO_MODEL_ID = "Tongyi-MAI/Z-Image-Turbo"
    SAM_MODEL_ID = "facebook/sam-vit-base"

try:
    from remove_ai_watermarks._internal.watermark_profiles import (
        AUTO_PROFILE,
        CHROMA_ZIMAGE_PROFILE,
        CONTROLNET_CANNY_MODEL,
        QWEN21_ZIMAGE_PROFILE,
        QWEN_ZIMAGE_PROFILE,
        SDXL_LIGHTNING_MODEL_ID,
        SDXL_LIGHTNING_PATTERN,
        SDXL_MODEL_ID,
        SDXL_ZIMAGE_PROFILE,
    )
except Exception:
    AUTO_PROFILE = "auto"
    CHROMA_ZIMAGE_PROFILE = "chroma-zimage"
    QWEN21_ZIMAGE_PROFILE = "qwen21-zimage"
    QWEN_ZIMAGE_PROFILE = "qwen-zimage"
    SDXL_ZIMAGE_PROFILE = "sdxl-zimage"
    SDXL_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
    CONTROLNET_CANNY_MODEL = "xinsir/controlnet-canny-sdxl-1.0"
    SDXL_LIGHTNING_MODEL_ID = "ByteDance/SDXL-Lightning"
    SDXL_LIGHTNING_PATTERN = "sdxl_lightning_4step_lora.safetensors"

try:
    from remove_ai_watermarks.region_eraser import (
        _LAMA_FILE,
        _LAMA_REPO,
        _MIGAN_FILE,
        _MIGAN_REPO,
    )
except Exception:
    _LAMA_REPO = "Carve/LaMa-ONNX"
    _LAMA_FILE = "lama_fp32.onnx"
    _MIGAN_REPO = "andraniksargsyan/migan"
    _MIGAN_FILE = "migan.onnx"

try:
    from remove_ai_watermarks.source_classify import (
        MODEL_FILE as SOURCE_CLASSIFY_FILE,
    )
    from remove_ai_watermarks.source_classify import (
        WEIGHTS_REPO as SOURCE_CLASSIFY_REPO,
    )
    from remove_ai_watermarks.source_classify import (
        WEIGHTS_REVISION as SOURCE_CLASSIFY_REVISION,
    )
except Exception:
    SOURCE_CLASSIFY_REPO = "wiltodelta/raiw-source-classify"
    SOURCE_CLASSIFY_FILE = "multi-provider-source-v8.npz"
    SOURCE_CLASSIFY_REVISION = "ebc2dcf0cface677535fe7c1903dd68793ee1f30"

# Default deep-clean profile for the web UI: lightest, fastest, fits 100% resident
# in 16 GB VRAM (RTX 5070 Ti), and wins Google SynthID on paired quality.
DEFAULT_PROFILE = SDXL_ZIMAGE_PROFILE


@dataclass(frozen=True)
class ModelSpec:
    """One HuggingFace repo a profile or tool loads, and the files it takes from it."""

    repo_id: str
    patterns: tuple[str, ...]
    label: str
    stage: str  # "global" | "face" | "lightweight"
    store: str = "hf"  # "hf" | "diffsynth"
    revision: str | None = None


_MIGAN_SPEC = ModelSpec(
    _MIGAN_REPO,
    (_MIGAN_FILE,),
    "MI-GAN ONNX (fast neural inpaint · 28 MB)",
    "lightweight",
    store="hf",
)
_LAMA_SPEC = ModelSpec(
    _LAMA_REPO,
    (_LAMA_FILE,),
    "big-LaMa ONNX (best neural inpaint · 208 MB)",
    "lightweight",
    store="hf",
)
_SOURCE_CLASSIFY_SPEC = ModelSpec(
    SOURCE_CLASSIFY_REPO,
    (SOURCE_CLASSIFY_FILE,),
    "Source Classify v8 (10-provider AI detector · 59 MB)",
    "lightweight",
    store="hf",
    revision=SOURCE_CLASSIFY_REVISION,
)

LIGHTWEIGHT_MODELS: tuple[ModelSpec, ...] = (
    _MIGAN_SPEC,
    _LAMA_SPEC,
    _SOURCE_CLASSIFY_SPEC,
)

_FACE_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        ZIMAGE_TURBO_MODEL_ID,
        ("transformer/*.safetensors", "text_encoder/*.safetensors", "vae/*.safetensors"),
        "Z-Image-Turbo (face repair)",
        "face",
        store="diffsynth",
    ),
    ModelSpec(SAM_MODEL_ID, ("model.safetensors",), "SAM ViT-Base (face masking)", "face"),
)

_SDXL_GLOBAL: tuple[ModelSpec, ...] = (
    ModelSpec(
        SDXL_MODEL_ID,
        (
            "unet/diffusion_pytorch_model.fp16.safetensors",
            "text_encoder/model.fp16.safetensors",
            "text_encoder_2/model.fp16.safetensors",
            "vae/diffusion_pytorch_model.fp16.safetensors",
        ),
        "SDXL Base 1.0 fp16 (fast global diffusion)",
        "global",
    ),
    ModelSpec(
        CONTROLNET_CANNY_MODEL,
        ("diffusion_pytorch_model.safetensors",),
        "SDXL Canny ControlNet (keeps structure)",
        "global",
    ),
    ModelSpec(
        SDXL_VAE_MODEL_ID,
        ("diffusion_pytorch_model.safetensors",),
        "SDXL fp16 VAE fix",
        "global",
    ),
    ModelSpec(
        SDXL_LIGHTNING_MODEL_ID,
        (SDXL_LIGHTNING_PATTERN,),
        "SDXL Lightning LoRA (4-step speedup)",
        "global",
    ),
)

_QWEN21_GLOBAL: tuple[ModelSpec, ...] = (
    ModelSpec(
        QWEN_IMAGE_21_MODEL_ID,
        (
            "transformer/diffusion_pytorch_model*.safetensors",
            "text_encoder/model*.safetensors",
            "processor/",
        ),
        "Qwen-Image-2.1 (7B smarter & lighter base)",
        "global",
        store="diffsynth",
    ),
    ModelSpec(
        QWEN21_TEXTURE_FIX_VAE_MODEL_ID,
        (QWEN21_TEXTURE_FIX_VAE_FILENAME,),
        "Qwen-2.1 Texture-Fix VAE (64-ch crisp detail)",
        "global",
        store="diffsynth",
    ),
    ModelSpec(
        QWEN21_CANNY_CONTROLNET_MODEL_ID,
        (QWEN21_CANNY_CONTROLNET_PATTERN,),
        "Qwen-2.1 Fun ControlNet Union (Canny structure)",
        "global",
        store="diffsynth",
    ),
)

_QWEN2512_GLOBAL: tuple[ModelSpec, ...] = (
    ModelSpec(
        QWEN_IMAGE_2512_MODEL_ID,
        (
            "transformer/diffusion_pytorch_model*.safetensors",
            "text_encoder/model*.safetensors",
            "vae/diffusion_pytorch_model.safetensors",
            "tokenizer/",
        ),
        "Qwen-Image-2512 (20B Apache-2.0 diffusion)",
        "global",
        store="diffsynth",
    ),
    ModelSpec(
        QWEN_CANNY_CONTROLNET_MODEL_ID,
        ("model.safetensors",),
        "Qwen Canny ControlNet (keeps structure)",
        "global",
        store="diffsynth",
    ),
    ModelSpec(
        QWEN_LIGHTNING_MODEL_ID,
        (QWEN_LIGHTNING_PATTERN,),
        "Qwen Lightning LoRA (4-step speedup)",
        "global",
        store="diffsynth",
    ),
)

_CHROMA_GLOBAL: tuple[ModelSpec, ...] = (
    ModelSpec(
        CHROMA_MODEL_ID,
        ("transformer/*.safetensors", "text_encoder/*.safetensors", "vae/*.safetensors"),
        "Chroma1-HD (Apache-2.0 FLUX-family · needs >=24 GB VRAM)",
        "global",
        store="hf",
    ),
)

PROFILE_MODELS: dict[str, tuple[ModelSpec, ...]] = {
    SDXL_ZIMAGE_PROFILE: (*_SDXL_GLOBAL, *_FACE_MODELS),
    QWEN21_ZIMAGE_PROFILE: (*_QWEN21_GLOBAL, *_FACE_MODELS),
    QWEN_ZIMAGE_PROFILE: (*_QWEN2512_GLOBAL, *_FACE_MODELS),
    AUTO_PROFILE: (*_SDXL_GLOBAL, *_QWEN2512_GLOBAL, *_FACE_MODELS),
    CHROMA_ZIMAGE_PROFILE: (*_CHROMA_GLOBAL, *_FACE_MODELS),
}

PROFILE_META: dict[str, dict[str, Any]] = {
    SDXL_ZIMAGE_PROFILE: {
        "label": "SDXL 1.0 + Z-Image — Lightest & Fastest (~10 GB, works on all GPUs & CPU)",
        "short": "SDXL + Z-Image",
        "badge": "Universal · Fastest",
        "desc": "Fits fully in 16 GB VRAM with zero disk streaming. Wins Google SynthID on paired quality.",
        "min_vram_gb": 8,
        "license": "Commercial-safe",
        "supports_non_cuda": True,
        "bf16_preferred": False,
        "notes": (
            "Works everywhere: NVIDIA RTX/GTX (fp16), AMD Radeon ROCm & DirectML, "
            "Intel Arc XPU, Apple Silicon MPS, and CPU fallback (fp32)."
        ),
    },
    QWEN21_ZIMAGE_PROFILE: {
        "label": "Qwen-Image-2.1 (7B) + Z-Image — Smarter Fidelity (~41 GB, Personal/Research)",
        "short": "Qwen-2.1 (7B) + Fidelity",
        "badge": "Smarter · 7B Fidelity",
        "desc": (
            "New 7B model (~16 GB lighter than 20B Qwen-2512) with 64-ch texture-fix VAE "
            "& guarded LPIPS/MSE alignment."
        ),
        "min_vram_gb": 12,
        "license": "Non-commercial (Qwen Research)",
        "supports_non_cuda": True,
        "bf16_preferred": True,
        "notes": (
            "Best with bfloat16 on NVIDIA RTX 30/40/50, AMD ROCm, or Intel Arc XPU. "
            "Falls back to fp16 on GTX 10/16, RTX 20, DirectML, and Apple MPS (slower on CPU)."
        ),
    },
    QWEN_ZIMAGE_PROFILE: {
        "label": "Qwen-Image-2512 (20B) + Z-Image — Apache-2.0 High Fidelity (~57 GB)",
        "short": "Qwen-2512 (20B)",
        "badge": "Apache-2.0 · 20B",
        "desc": "Streams fp8/bf16 on 16 GB GPUs. Strong OpenAI & Meta floors with Apache-2.0 license.",
        "min_vram_gb": 12,
        "license": "Apache-2.0",
        "supports_non_cuda": True,
        "bf16_preferred": True,
        "notes": (
            "Best with bfloat16 on NVIDIA RTX 30/40/50, AMD ROCm, or Intel Arc XPU (>=12 GB VRAM). "
            "Large 20B weights; fp16 fallback on older GPUs/MPS/DirectML."
        ),
    },
    AUTO_PROFILE: {
        "label": "Auto Smart Router — Picks best calibrated model per vendor",
        "short": "Auto Router",
        "badge": "Smart Auto",
        "desc": (
            "Pre-downloads SDXL + Qwen-2512 + face repair. Routes Google -> SDXL and "
            "OpenAI/Meta/Unknown -> Qwen-2512 (Microsoft routes to Chroma1 when installed on >=24 GB VRAM)."
        ),
        "min_vram_gb": 12,
        "license": "Commercial-safe",
        "supports_non_cuda": True,
        "bf16_preferred": True,
        "notes": (
            "Uses SDXL (universal fp16) for Google images and Qwen-2512 (bf16 preferred) for OpenAI/Meta/Unknown."
        ),
    },
    CHROMA_ZIMAGE_PROFILE: {
        "label": "Chroma1-HD + Z-Image — Apache-2.0 FLUX-family (~28 GB, >=24 GB VRAM)",
        "short": "Chroma1-HD",
        "badge": ">=24 GB VRAM",
        "desc": "Best Microsoft InvisMark floor (0.125), but loads without global CPU offload (~20-29 GB VRAM).",
        "min_vram_gb": 24,
        "license": "Apache-2.0",
        "supports_non_cuda": True,
        "bf16_preferred": True,
        "notes": (
            "Requires >=24 GB VRAM/unified memory (e.g. RTX 3090/4090/5090, RX 7900 XTX ROCm, "
            "or Apple Silicon >=32 GB). Prefers bfloat16."
        ),
    },
}


def _all_known_specs() -> dict[tuple[str, str], ModelSpec]:
    seen: dict[tuple[str, str], ModelSpec] = {}
    for spec in LIGHTWEIGHT_MODELS:
        seen[(spec.store, spec.repo_id)] = spec
    for specs in PROFILE_MODELS.values():
        for spec in specs:
            seen[(spec.store, spec.repo_id)] = spec
    return seen


def cache_root() -> Path:
    """The HuggingFace hub cache directory diffusers/transformers/ONNX models land in."""
    try:
        from huggingface_hub import constants

        return Path(constants.HF_HUB_CACHE)
    except Exception:
        env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
        if env:
            return Path(env)
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            return Path(hf_home) / "hub"
        return Path.home() / ".cache" / "huggingface" / "hub"


def diffsynth_root() -> Path:
    """Where DiffSynth puts its models. Mirrors ``ModelConfig.reset_local_model_path``."""
    return Path(os.environ.get("DIFFSYNTH_MODEL_BASE_PATH") or "./models").resolve()


# --- Thread-safe, atomic settings persistence --------------------------------

SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"
_settings_lock = threading.Lock()


def _load_settings_unlocked() -> dict[str, Any]:
    try:
        with SETTINGS_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_settings() -> dict[str, Any]:
    with _settings_lock:
        return _load_settings_unlocked()


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    with _settings_lock:
        settings = _load_settings_unlocked()
        settings.update(updates)
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=SETTINGS_PATH.parent,
                prefix=".settings.",
                suffix=".tmp",
                delete=False,
            ) as fh:
                tmp_path = fh.name
                json.dump(settings, fh, indent=2)
                fh.flush()
                with contextlib.suppress(OSError):
                    os.fsync(fh.fileno())
            os.replace(tmp_path, SETTINGS_PATH)
            tmp_path = None
        finally:
            if tmp_path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
    if "default_profile" in updates or "model_dir" in updates:
        invalidate_snapshot_cache()
    return settings


def preferred_profile() -> str:
    saved = load_settings().get("default_profile")
    if isinstance(saved, str) and saved in PROFILE_MODELS:
        return saved
    return DEFAULT_PROFILE


def apply_saved_model_dir() -> None:
    """Re-apply the saved folder at startup, before anything loads a model."""
    if os.environ.get("DIFFSYNTH_MODEL_BASE_PATH"):
        return
    saved = load_settings().get("model_dir")
    if isinstance(saved, str) and saved.strip():
        os.environ["DIFFSYNTH_MODEL_BASE_PATH"] = saved


def set_model_dir(raw: str) -> dict[str, Any]:
    """Point future DiffSynth downloads at ``raw``. Returns ``{ok, folder, error}``."""
    path = (raw or "").strip().strip('"')
    if not path:
        return {"ok": False, "error": "Folder is empty.", "folder": str(diffsynth_root())}
    with _dl_lock:
        if _dl["active"]:
            return {
                "ok": False,
                "error": "A download is running. Pause it first.",
                "folder": str(diffsynth_root()),
            }
    try:
        target = Path(path).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".raiw-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return {"ok": False, "error": f"Cannot use that folder: {exc}", "folder": str(diffsynth_root())}

    resolved = str(target.resolve())
    os.environ["DIFFSYNTH_MODEL_BASE_PATH"] = resolved
    try:
        save_settings({"model_dir": resolved})
    except OSError as exc:
        return {"ok": True, "folder": resolved, "error": f"Could not save the setting: {exc}"}
    recheck()
    return {"ok": True, "folder": resolved, "error": None}


def spec_dir(spec: ModelSpec) -> Path:
    if spec.store == "diffsynth":
        return diffsynth_root() / spec.repo_id
    return cache_root() / ("models--" + spec.repo_id.replace("/", "--"))


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    for pat in patterns:
        if pat.endswith("/"):
            if name.startswith(pat):
                return True
        elif fnmatch.fnmatch(name, pat):
            return True
    return False


# --- Fast os.scandir() tree sizing with hardlink deduplication ---------------


def _is_incomplete_file(name: str) -> bool:
    low = name.lower()
    return low.endswith((".incomplete", ".lock"))


def _tree_bytes_pair(root: Path) -> tuple[int, int]:
    """Single-pass ``os.scandir`` returning ``(all_bytes, complete_bytes)``.

    Uses ``follow_symlinks=False`` and deduplicates hardlinks via ``(st_dev, st_ino)``
    when the filesystem reports non-zero inodes so Windows/NTFS hardlinks are never
    double-counted.
    """
    if not root.is_dir():
        return 0, 0
    total_all = 0
    total_complete = 0
    seen_inodes: set[tuple[int, int]] = set()
    stack: list[str] = [os.fspath(root)]
    while stack:
        cur_dir = stack.pop()
        try:
            with os.scandir(cur_dir) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            # On Windows, DirEntry.stat() leaves st_ino/st_nlink as 0;
                            # query os.stat(..., follow_symlinks=False) for real NTFS hardlink IDs.
                            if st.st_ino == 0:
                                st = os.stat(entry.path, follow_symlinks=False)
                            if st.st_ino != 0:
                                key = (st.st_dev, st.st_ino)
                                if key in seen_inodes:
                                    continue
                                seen_inodes.add(key)
                            sz = st.st_size
                            total_all += sz
                            if not _is_incomplete_file(entry.name):
                                total_complete += sz
                    except OSError:
                        continue
        except OSError:
            continue
    return total_all, total_complete


def _tree_bytes(root: Path, *, exclude_incomplete: bool = False) -> int:
    """Total bytes under ``root`` via fast ``os.scandir()`` without double-counting hardlinks."""
    all_bytes, complete_bytes = _tree_bytes_pair(root)
    return complete_bytes if exclude_incomplete else all_bytes


def _source_classify_alt_file() -> Path | None:
    """Return an already-cached local Source Classify v8 weights path outside HF cache, if any."""
    env_path = os.environ.get("RAIW_SOURCE_CLASSIFY_WEIGHTS")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p
    with contextlib.suppress(Exception):
        from remove_ai_watermarks import source_classify as sc

        probe = getattr(sc, "_probe_github_weights_cache", None)
        if callable(probe):
            hit = probe(
                sc.GITHUB_WEIGHTS_REPO,
                sc.GITHUB_WEIGHTS_TAG,
                sc.MODEL_FILE,
                sc.MODEL_SHA256,
            )
            if isinstance(hit, Path) and hit.is_file():
                return hit
    return None


def _spec_bytes_pair(
    spec: ModelSpec,
    scan_cache: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> tuple[int, int]:
    """Return ``(all_bytes, complete_bytes)`` for ``spec``, memoized per ``(store, repo_id)``."""
    cache_key = (spec.store, spec.repo_id)
    if scan_cache is not None and cache_key in scan_cache:
        return scan_cache[cache_key]

    root = spec_dir(spec)
    pair = _tree_bytes_pair(root) if spec.store == "diffsynth" else _tree_bytes_pair(root / "blobs")

    # Source Classify v8 may also live in RAIW_SOURCE_CLASSIFY_WEIGHTS or GitHub release cache.
    if pair[0] == 0 and spec.repo_id == SOURCE_CLASSIFY_REPO:
        alt = _source_classify_alt_file()
        if alt is not None:
            with contextlib.suppress(OSError):
                sz = alt.stat().st_size
                pair = (sz, sz)

    if scan_cache is not None:
        scan_cache[cache_key] = pair
    return pair


def bytes_on_disk(spec: ModelSpec, *, exclude_incomplete: bool = False) -> int:
    """Bytes present for a spec; optionally excluding ``.incomplete`` / ``.lock`` files."""
    all_bytes, complete_bytes = _spec_bytes_pair(spec)
    return complete_bytes if exclude_incomplete else all_bytes


def _spec_cached_complete_fast(spec: ModelSpec) -> bool:
    """Fast local check for single-file HF specs (e.g. ONNX models) even offline."""
    if spec.repo_id == SOURCE_CLASSIFY_REPO and _source_classify_alt_file() is not None:
        return True
    if spec.store != "hf":
        return False
    if len(spec.patterns) != 1 or "*" in spec.patterns[0] or spec.patterns[0].endswith("/"):
        return False
    try:
        from huggingface_hub import try_to_load_from_cache

        hit = try_to_load_from_cache(
            repo_id=spec.repo_id,
            filename=spec.patterns[0],
            revision=spec.revision,
        )
        return isinstance(hit, str) and Path(hit).is_file()
    except Exception:
        return False


def lightweight_spec_cached(name: str) -> bool:
    """Fast local check for whether a named lightweight backend ('migan' | 'lama' | 'source_classify') is cached."""
    mapping = {
        "migan": _MIGAN_SPEC,
        "lama": _LAMA_SPEC,
        "source_classify": _SOURCE_CLASSIFY_SPEC,
    }
    spec = mapping.get(name)
    if spec is None:
        return False
    return _spec_cached_complete_fast(spec)


# --- Expected Hub sizes with disk persistence & 120s negative-cache cooldown -


def _spec_key(spec: ModelSpec) -> str:
    return f"{spec.store}:{spec.repo_id}:{spec.revision or 'main'}:{','.join(spec.patterns)}"


_NEGATIVE_CACHE_TTL_S = 120.0
_expected: dict[str, int] = {}
_persisted_expected: dict[str, int] = {}
_expected_failed: dict[str, float] = {}
_expected_lock = threading.Lock()
_inflight: set[str] = set()
_expected_bootstrapped = False


def _bootstrap_expected_sizes() -> None:
    global _expected_bootstrapped
    with _expected_lock:
        if _expected_bootstrapped:
            return
        _expected_bootstrapped = True
    raw = load_settings().get("expected_sizes")
    if not isinstance(raw, dict):
        return
    clean: dict[str, int] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0:
            clean[k] = v
    with _expected_lock:
        _persisted_expected.update(clean)
        for k, v in clean.items():
            _expected.setdefault(k, v)


def _persist_expected_size(key: str, total: int) -> None:
    with _expected_lock:
        if _persisted_expected.get(key) == total:
            return
        _persisted_expected[key] = total
        snapshot_sizes = dict(_persisted_expected)
    with contextlib.suppress(OSError):
        save_settings({"expected_sizes": snapshot_sizes})


def _fetch_expected(spec: ModelSpec) -> None:
    key = _spec_key(spec)
    total = 0
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(spec.repo_id, revision=spec.revision, files_metadata=True)
        for sib in info.siblings or []:
            if _matches(sib.rfilename, spec.patterns):
                total += sib.size or 0
    except Exception:
        total = 0
    changed = False
    with _expected_lock:
        if total > 0:
            changed = _expected.get(key) != total
            _expected[key] = total
            _expected_failed.pop(key, None)
        else:
            _expected_failed[key] = time.monotonic()
            # Keep last-known persisted size if Hub is currently unreachable
            if key not in _expected and key in _persisted_expected:
                _expected[key] = _persisted_expected[key]
                changed = True
        _inflight.discard(key)
    if total > 0:
        _persist_expected_size(key, total)
    if changed:
        invalidate_snapshot_cache()


def expected_bytes(spec: ModelSpec) -> int | None:
    """Total download size for this repo's requested files, or None until known."""
    _bootstrap_expected_sizes()
    key = _spec_key(spec)
    now = time.monotonic()
    with _expected_lock:
        if key in _expected:
            return _expected[key]
        if key in _inflight:
            return None
        failed_at = _expected_failed.get(key)
        if failed_at is not None and (now - failed_at) < _NEGATIVE_CACHE_TTL_S:
            return None
        _inflight.add(key)
    threading.Thread(target=_fetch_expected, args=(spec,), daemon=True).start()
    return None


# --- Live transfer rate estimator --------------------------------------------

_RATE_WINDOW_S = 10.0
_MIN_REPORT_RATE_MB_S = 0.02
_samples: dict[str, list[tuple[float, int]]] = {}
_samples_lock = threading.Lock()


def _rate_mb_s(repo_key: str, now_bytes: int) -> float | None:
    now = time.monotonic()
    with _samples_lock:
        hist = _samples.setdefault(repo_key, [])
        if hist and (now_bytes < hist[-1][1] or (now - hist[-1][0]) > _RATE_WINDOW_S):
            hist.clear()
        if not hist or now - hist[-1][0] >= 1.0:
            hist.append((now, now_bytes))
        while len(hist) > 2 and now - hist[0][0] > _RATE_WINDOW_S:
            hist.pop(0)
        oldest = hist[0]
    elapsed = now - oldest[0]
    if elapsed < 1.0:
        return None
    rate = (now_bytes - oldest[1]) / elapsed / 1_000_000
    return rate if rate >= _MIN_REPORT_RATE_MB_S else None


def repo_files(spec: ModelSpec) -> list[tuple[str, int]]:
    """The (filename, size) pairs this spec wants, newest metadata from the Hub."""
    from huggingface_hub import HfApi

    info = HfApi().model_info(spec.repo_id, revision=spec.revision, files_metadata=True)
    out: list[tuple[str, int]] = []
    for sib in info.siblings or []:
        if _matches(sib.rfilename, spec.patterns):
            out.append((sib.rfilename, sib.size or 0))
    return out


# --- Snapshot TTL Cache ------------------------------------------------------

_SNAPSHOT_TTL_ACTIVE_S = 1.5
_SNAPSHOT_TTL_IDLE_S = 20.0
_snapshot_lock = threading.Lock()
_snapshot_cache: dict[str, tuple[float, bool, dict[str, Any]]] = {}


def invalidate_snapshot_cache() -> None:
    """Drop cached snapshots so the next call re-scans the filesystem."""
    with _snapshot_lock:
        _snapshot_cache.clear()


# --- Background Download Manager ---------------------------------------------

_dl_lock = threading.Lock()
_dl: dict[str, Any] = {
    "active": False,
    "profile": None,
    "current": None,
    "error": None,
    "stop": None,
    "pausing": False,
    "include_face": True,
}


def _dl_public_state_unlocked() -> dict[str, Any]:
    """Return a JSON-safe snapshot of ``_dl`` (never includes the Event object)."""
    return {
        "active": bool(_dl["active"]),
        "pausing": bool(_dl["pausing"]),
        "profile": _dl["profile"],
        "current": _dl["current"],
        "error": _dl["error"],
        "include_face": bool(_dl["include_face"]),
    }


def _download_file_with_retry(
    hf_hub_download: Any,
    spec: ModelSpec,
    name: str,
    stop: threading.Event,
    *,
    retries: int = 3,
    base_delay: float = 2.0,
) -> None:
    """Download a single model file with exponential backoff and automatic resume on flaky networks."""
    kwargs: dict[str, Any] = {}
    if spec.revision:
        kwargs["revision"] = spec.revision
    max_attempts = max(1, int(retries))
    for attempt in range(1, max_attempts + 1):
        if stop.is_set():
            return
        with _dl_lock:
            suffix = f" (retry {attempt}/{max_attempts})" if attempt > 1 else ""
            _dl["current"] = f"{spec.repo_id}/{name}{suffix}"
        try:
            if spec.store == "diffsynth":
                hf_hub_download(spec.repo_id, name, local_dir=str(spec_dir(spec)), **kwargs)
            else:
                hf_hub_download(spec.repo_id, name, **kwargs)
            return
        except Exception as exc:
            msg = str(exc).lower()
            # Never retry permanent 401/403/404 repository/auth errors
            if any(k in msg for k in ("401", "403", "404", "gated", "unauthorized", "entrynotfound")):
                raise
            if attempt >= max_attempts or stop.is_set():
                raise
            # Interruptible backoff sleep so Pause responds immediately
            if stop.wait(timeout=base_delay * (2 ** (attempt - 1))):
                return


def _download_worker(profile: str, include_face: bool, stop: threading.Event) -> None:
    from huggingface_hub import hf_hub_download

    error = None
    try:
        specs = LIGHTWEIGHT_MODELS if profile == "lightweight" else PROFILE_MODELS.get(profile, ())
        for spec in specs:
            if stop.is_set():
                return
            if spec.stage == "face" and not include_face:
                continue
            files = repo_files(spec)
            for name, _size in files:
                if stop.is_set():
                    return
                _download_file_with_retry(hf_hub_download, spec, name, stop, retries=3, base_delay=2.0)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        with _dl_lock:
            _dl.update(active=False, pausing=False, current=None, error=error, stop=None)
        invalidate_snapshot_cache()


def start_download(profile: str, include_face: bool = True) -> dict[str, Any]:
    """Begin prefetching a profile's (or 'lightweight') weights in the background."""
    with _dl_lock:
        if _dl["active"]:
            return {**_dl_public_state_unlocked(), "started": False}
        stop = threading.Event()
        _dl.update(
            active=True,
            pausing=False,
            profile=profile,
            current=None,
            error=None,
            stop=stop,
            include_face=include_face,
        )
        state = {**_dl_public_state_unlocked(), "started": True}
    invalidate_snapshot_cache()
    threading.Thread(target=_download_worker, args=(profile, include_face, stop), daemon=True).start()
    return state


def pause_download() -> dict[str, Any]:
    """Stop after the file in flight finishes; already-downloaded files are kept."""
    with _dl_lock:
        stop = _dl.get("stop")
        if stop is not None:
            stop.set()
            _dl["pausing"] = True
        state = _dl_public_state_unlocked()
    invalidate_snapshot_cache()
    return state


def recheck() -> None:
    """Drop cached Hub sizes, failure cooldowns, and filesystem snapshots."""
    with _expected_lock:
        _expected.clear()
        _expected_failed.clear()
        _inflight.clear()
    with _samples_lock:
        _samples.clear()
    invalidate_snapshot_cache()


def delete_model(repo_id: str, store: str) -> dict[str, Any]:
    """Safely delete cached weights for one registered model repo."""
    with _dl_lock:
        if _dl["active"]:
            return {"ok": False, "error": "Cannot delete models while a download is running."}

    known = _all_known_specs()
    if store == "stale_hf":
        # Allow cleaning up a duplicate HF cache directory for a diffsynth model
        spec = known.get(("diffsynth", repo_id))
        if spec is None:
            return {"ok": False, "error": f"Unknown model repo: {repo_id}"}
        target = cache_root() / ("models--" + repo_id.replace("/", "--"))
    else:
        spec = known.get((store, repo_id))
        if spec is None:
            return {"ok": False, "error": f"Unknown model repo: {repo_id}"}
        target = spec_dir(spec)

    if not target.exists():
        return {"ok": True, "freed_bytes": 0, "message": "Already empty."}

    freed = _tree_bytes(target)
    try:
        shutil.rmtree(target)
    except OSError as exc:
        return {"ok": False, "error": f"Failed to delete {target}: {exc}"}
    recheck()
    return {"ok": True, "freed_bytes": freed, "message": f"Deleted {repo_id}."}


def stale_hf_duplicates() -> list[dict[str, Any]]:
    """Find DiffSynth models that also have leftover bytes in the HuggingFace hub cache."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    hub = cache_root()
    for (store, repo_id), spec in _all_known_specs().items():
        if store != "diffsynth" or repo_id in seen:
            continue
        seen.add(repo_id)
        hf_dir = hub / ("models--" + repo_id.replace("/", "--"))
        if hf_dir.is_dir():
            blobs = hf_dir / "blobs"
            sz = _tree_bytes(blobs) if blobs.is_dir() else _tree_bytes(hf_dir)
            if sz >= 50_000_000:  # >= 50 MB
                out.append(
                    {
                        "repo_id": repo_id,
                        "label": spec.label,
                        "store": "stale_hf",
                        "bytes": sz,
                        "folder": str(hf_dir),
                    }
                )
    return out


def download_state() -> dict[str, Any]:
    with _dl_lock:
        return _dl_public_state_unlocked()


def _spec_complete(spec: ModelSpec, have_complete: int, want: int | None) -> bool:
    if _spec_cached_complete_fast(spec):
        return True
    if want is not None and want > 0:
        return have_complete >= want * 0.995
    return False


def _spec_entry(
    spec: ModelSpec,
    scan_cache: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> dict[str, Any]:
    have_all, have_complete = _spec_bytes_pair(spec, scan_cache)
    want = expected_bytes(spec)
    rate = _rate_mb_s(_spec_key(spec), have_all)
    complete = _spec_complete(spec, have_complete, want)
    pct: float | None
    if complete:
        pct = 100.0
    elif want:
        pct = min(100.0, round(100 * have_all / want, 1))
    else:
        pct = None
    return {
        "repo_id": spec.repo_id,
        "label": spec.label,
        "stage": spec.stage,
        "store": spec.store,
        "bytes": have_all,
        "complete_bytes": have_complete,
        "total": want,
        "percent": pct,
        "rate_mb_s": round(rate, 2) if rate else None,
        "folder": str(spec_dir(spec)),
        "complete": complete,
    }


def _profile_ready_summary(
    pid: str,
    scan_cache: dict[tuple[str, str], tuple[int, int]],
) -> bool:
    specs = PROFILE_MODELS.get(pid, ())
    has_global = False
    for spec in specs:
        if spec.stage != "global":
            continue
        has_global = True
        _have_all, have_complete = _spec_bytes_pair(spec, scan_cache)
        want = expected_bytes(spec)
        if not _spec_complete(spec, have_complete, want):
            return False
    return has_global


def quick_download_snapshot(profile: str | None = None) -> dict[str, Any]:
    """Fast single-profile check for ``_download_watcher`` without scanning all profiles or stale cache."""
    profile = profile if profile in PROFILE_MODELS else preferred_profile()
    scan_cache: dict[tuple[str, str], tuple[int, int]] = {}
    models: list[dict[str, Any]] = []
    done_total = 0
    disk_total = 0
    want_total = 0
    known_all = True
    all_complete = True

    for spec in PROFILE_MODELS.get(profile, ()):
        entry = _spec_entry(spec, scan_cache)
        if not entry["complete"]:
            all_complete = False
        if spec.stage == "global":
            have = entry["bytes"]
            want = entry["total"]
            disk_total += have
            if want:
                done_total += min(have, want)
                want_total += want
            else:
                done_total += have
                known_all = False
        models.append(entry)

    return {
        "profile": profile,
        "models": models,
        "all_complete": all_complete,
        "global_ready": all(m["complete"] for m in models if m["stage"] == "global"),
        "bytes": done_total,
        "disk_bytes": disk_total,
        "total": want_total if known_all else None,
        "percent": (min(100.0, round(100 * done_total / want_total, 1)) if known_all and want_total else None),
        "downloading": any(m["rate_mb_s"] for m in models),
        "job": download_state(),
    }


def snapshot(profile: str | None = None) -> dict[str, Any]:
    """Current per-model download state for one profile + lightweight ONNX pack (TTL-cached)."""
    profile = profile if profile in PROFILE_MODELS else preferred_profile()
    dl_active = download_state()["active"]
    now = time.monotonic()

    with _snapshot_lock:
        cached = _snapshot_cache.get(profile)
        if cached is not None:
            cached_at, cached_busy, cached_data = cached
            ttl = _SNAPSHOT_TTL_ACTIVE_S if (dl_active or cached_busy) else _SNAPSHOT_TTL_IDLE_S
            if (now - cached_at) < ttl:
                return copy.deepcopy(cached_data)

    scan_cache: dict[tuple[str, str], tuple[int, int]] = {}
    models: list[dict[str, Any]] = []
    done_total = 0
    disk_total = 0
    want_total = 0
    known_all = True
    for spec in PROFILE_MODELS.get(profile, ()):
        entry = _spec_entry(spec, scan_cache)
        if spec.stage == "global":
            have = entry["bytes"]
            want = entry["total"]
            disk_total += have
            if want:
                done_total += min(have, want)
                want_total += want
            else:
                done_total += have
                known_all = False
        models.append(entry)

    lightweight = [_spec_entry(spec, scan_cache) for spec in LIGHTWEIGHT_MODELS]
    default_prof = preferred_profile()
    profiles_out = []
    for pid in PROFILE_MODELS:
        meta = PROFILE_META.get(pid, {})
        profiles_out.append(
            {
                "id": pid,
                "label": meta.get("label", pid),
                "short": meta.get("short", pid),
                "badge": meta.get("badge", ""),
                "desc": meta.get("desc", ""),
                "min_vram_gb": meta.get("min_vram_gb", 8),
                "license": meta.get("license", ""),
                "supports_non_cuda": bool(meta.get("supports_non_cuda", True)),
                "bf16_preferred": bool(meta.get("bf16_preferred", False)),
                "notes": meta.get("notes", ""),
                "default": pid == default_prof,
                "ready": _profile_ready_summary(pid, scan_cache),
            }
        )

    job_state = download_state()
    downloading = any(m["rate_mb_s"] for m in models) or any(m["rate_mb_s"] for m in lightweight)
    result = {
        "profile": profile,
        "default_profile": default_prof,
        "profiles": profiles_out,
        "cache_root": str(cache_root()),
        "diffsynth_root": str(diffsynth_root()),
        "models": models,
        "lightweight": lightweight,
        "lightweight_ready": all(m["complete"] for m in lightweight),
        "stale_cache": stale_hf_duplicates(),
        "bytes": done_total,
        "disk_bytes": disk_total,
        "total": want_total if known_all else None,
        "percent": (min(100.0, round(100 * done_total / want_total, 1)) if known_all and want_total else None),
        "downloading": downloading,
        "job": job_state,
    }

    with _snapshot_lock:
        _snapshot_cache[profile] = (time.monotonic(), bool(job_state["active"] or downloading), copy.deepcopy(result))

    return result
