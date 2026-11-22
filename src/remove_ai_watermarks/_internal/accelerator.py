"""Universal GPU/NPU/CPU hardware detection, device/dtype resolution, and ONNX EP selection.

Supports NVIDIA CUDA (RTX & GTX), AMD ROCm (HIP) & DirectML, Intel Arc XPU & OpenVINO,
Apple Silicon MPS & CoreML, AI NPUs (Intel Core Ultra / AMD Ryzen AI / Qualcomm QNN),
and clean CPU fallback.
"""

# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingTypeArgument=false, reportMissingTypeStubs=false, reportMissingImports=false, reportArgumentType=false, reportAssignmentType=false, reportReturnType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
from __future__ import annotations

import contextlib
import importlib
import logging
import os
import platform
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from remove_ai_watermarks._internal.watermark_profiles import (
    AUTO_PROFILE,
    CHROMA_ZIMAGE_PROFILE,
    QWEN21_ZIMAGE_PROFILE,
    QWEN_ZIMAGE_PROFILE,
    SDXL_ZIMAGE_PROFILE,
    normalize_profile,
)

logger = logging.getLogger(__name__)

ONNX_PROVIDER_ENV = "RAIW_ONNX_PROVIDER"

ONNX_PROVIDER_PRIORITY: tuple[str, ...] = (
    "CUDAExecutionProvider",
    "ROCMExecutionProvider",
    "MIGraphXExecutionProvider",
    "DmlExecutionProvider",
    "OpenVINOExecutionProvider",
    "QNNExecutionProvider",
    "CoreMLExecutionProvider",
    "CPUExecutionProvider",
)

DIFFSYNTH_SUPPORTED_KINDS: frozenset[str] = frozenset({"cuda", "rocm", "xpu"})


@dataclass(frozen=True)
class AcceleratorInfo:
    """Snapshot of detected GPU/NPU/CPU hardware and runtime capabilities."""

    accelerator_kind: str
    vendor: str
    device: str
    device_name: str
    vram_gb: float | None
    bf16_supported: bool
    fp16_supported: bool
    torch_version: str | None
    onnx_providers: list[str] = field(default_factory=list)
    active_onnx_provider: str = "CPUExecutionProvider"
    npu_detected: bool = False
    diffusion_devices: list[str] = field(default_factory=list)
    supported_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return asdict(self)


def _import_torch(torch_module: Any = None) -> Any | None:
    if torch_module is not None:
        return torch_module
    try:
        return importlib.import_module("torch")
    except Exception:
        return None


def _import_torch_directml() -> Any | None:
    try:
        return importlib.import_module("torch_directml")
    except Exception:
        return None


def _is_rocm(torch_mod: Any) -> bool:
    version = getattr(torch_mod, "version", None)
    hip = getattr(version, "hip", None)
    return bool(hip)


def _probe_tensor(torch_mod: Any, device: Any) -> bool:
    try:
        probe = torch_mod.tensor([1.0], device=device)
        _ = probe + probe
    except Exception:
        return False
    return True


def _cuda_available(torch_mod: Any) -> bool:
    cuda = getattr(torch_mod, "cuda", None)
    if cuda is None or not callable(getattr(cuda, "is_available", None)):
        return False
    try:
        if not cuda.is_available():
            return False
    except Exception:
        return False
    return _probe_tensor(torch_mod, "cuda")


def _xpu_available(torch_mod: Any) -> bool:
    xpu = getattr(torch_mod, "xpu", None)
    if xpu is None or not callable(getattr(xpu, "is_available", None)):
        return False
    try:
        if not xpu.is_available():
            return False
    except Exception:
        return False
    return _probe_tensor(torch_mod, "xpu")


def _mps_available(torch_mod: Any) -> bool:
    backends = getattr(torch_mod, "backends", None)
    mps = getattr(backends, "mps", None)
    if mps is None or not callable(getattr(mps, "is_available", None)):
        return False
    try:
        return bool(mps.is_available())
    except Exception:
        return False


def _dml_available() -> tuple[bool, Any]:
    dml = _import_torch_directml()
    if dml is None:
        return False, None
    try:
        if not dml.is_available():
            return False, None
        return True, dml.device()
    except Exception:
        return False, None


def is_diffsynth_supported(device_kind: str) -> bool:
    """Return True when DiffSynth's VRAM manager supports ``device_kind``."""
    return device_kind.casefold() in DIFFSYNTH_SUPPORTED_KINDS


def infer_device_kind(device: Any, *, torch_module: Any = None) -> str:
    """Infer canonical accelerator kind from a torch device object or string."""
    text = str(device).strip().casefold()
    if text.startswith("cuda"):
        torch_mod = _import_torch(torch_module)
        if torch_mod is not None and _is_rocm(torch_mod):
            return "rocm"
        return "cuda"
    if text.startswith("rocm"):
        return "rocm"
    if text.startswith("xpu"):
        return "xpu"
    if text.startswith("mps"):
        return "mps"
    if text.startswith(("dml", "directml", "privateuseone")):
        return "dml"
    return "cpu"


def resolve_torch_device(
    requested: str | None = None,
    *,
    torch_module: Any = None,
) -> tuple[Any, str]:
    """Resolve a requested or automatic PyTorch device to ``(device, device_kind)``.

    Priority for ``None`` / ``"auto"``:
    1. CUDA / AMD ROCm (with quick tensor probe)
    2. Intel Arc XPU (with quick tensor probe)
    3. Apple Silicon MPS
    4. Windows DirectML (``torch-directml``)
    5. CPU
    """
    raw = (requested or "auto").strip()
    norm = raw.casefold()
    if norm == "cpu":
        return "cpu", "cpu"

    torch_mod = _import_torch(torch_module)
    if torch_mod is None:
        if norm in ("", "auto"):
            return "cpu", "cpu"
        raise ValueError(f"Requested device '{raw}' is not available because PyTorch is not installed.")

    if norm in ("", "auto"):
        if _cuda_available(torch_mod):
            return "cuda", ("rocm" if _is_rocm(torch_mod) else "cuda")
        if _xpu_available(torch_mod):
            return "xpu", "xpu"
        if _mps_available(torch_mod):
            return "mps", "mps"
        dml_ok, dml_dev = _dml_available()
        if dml_ok:
            return dml_dev, "dml"
        return "cpu", "cpu"

    if norm == "cuda" or norm.startswith("cuda:"):
        if not _cuda_available(torch_mod):
            raise ValueError(
                f"Requested device '{raw}' is not available: no working CUDA/ROCm backend detected."
            )
        return norm, ("rocm" if _is_rocm(torch_mod) else "cuda")

    if norm == "rocm" or norm.startswith("rocm:"):
        if not (_cuda_available(torch_mod) and _is_rocm(torch_mod)):
            raise ValueError(
                f"Requested device '{raw}' is not available: no working AMD ROCm (HIP) PyTorch backend detected."
            )
        suffix = norm[4:]
        return f"cuda{suffix}", "rocm"

    if norm == "xpu" or norm.startswith("xpu:"):
        if not _xpu_available(torch_mod):
            raise ValueError(
                f"Requested device '{raw}' is not available: no working Intel Arc XPU backend detected."
            )
        return norm, "xpu"

    if norm == "mps":
        if not _mps_available(torch_mod):
            raise ValueError("Requested device 'mps' is not available: Apple Silicon MPS backend not detected.")
        return "mps", "mps"

    if norm in ("dml", "directml"):
        dml_ok, dml_dev = _dml_available()
        if not dml_ok:
            raise ValueError(
                f"Requested device '{raw}' is not available: install 'torch-directml' on Windows with a DirectML GPU."
            )
        return dml_dev, "dml"

    raise ValueError(
        f"Unsupported device '{raw}'. Use one of: auto, cuda, rocm, xpu, mps, dml, cpu."
    )


def is_bf16_supported(device_kind: str, *, torch_module: Any = None) -> bool:
    """Return whether native bfloat16 compute is supported on ``device_kind``."""
    kind = device_kind.casefold()
    if kind in ("cpu", "dml", "mps"):
        return False
    torch_mod = _import_torch(torch_module)
    if torch_mod is None:
        return False

    if kind in ("cuda", "rocm"):
        cuda = getattr(torch_mod, "cuda", None)
        if cuda is None:
            return False
        # NVIDIA pre-Ampere GPUs (GTX 10xx Pascal SM 6.x, GTX 16xx / RTX 20xx Turing SM 7.x)
        # lack native bf16 tensor cores and must fall back to fp16.
        if kind == "cuda":
            get_cap = getattr(cuda, "get_device_capability", None)
            if callable(get_cap):
                with contextlib.suppress(Exception):
                    cap = get_cap()
                    if isinstance(cap, tuple) and len(cap) == 2 and isinstance(cap[0], int) and cap[0] < 8:
                        return False
        bf16_fn = getattr(cuda, "is_bf16_supported", None)
        if callable(bf16_fn):
            try:
                return bool(bf16_fn(including_emulation=False))
            except TypeError:
                with contextlib.suppress(Exception):
                    return bool(bf16_fn())
            except Exception:
                return False
        return False

    if kind == "xpu":
        xpu = getattr(torch_mod, "xpu", None)
        if xpu is None:
            return False
        bf16_fn = getattr(xpu, "is_bf16_supported", None)
        if callable(bf16_fn):
            with contextlib.suppress(Exception):
                return bool(bf16_fn())
        try:
            probe = torch_mod.zeros(1, device="xpu", dtype=torch_mod.bfloat16)
            _ = probe + probe
            return True
        except Exception:
            return False

    return False


def resolve_dtype(device_kind: str, profile: str, *, torch_module: Any = None) -> Any:
    """Select the optimal safe PyTorch dtype for ``(device_kind, profile)``.

    - ``cpu``: always ``torch.float32`` (never fp16/bf16 on CPU).
    - ``sdxl-zimage``: ``torch.float16`` on all accelerators (uses fp16-safe VAE).
    - ``qwen-zimage`` / ``qwen21-zimage`` / ``chroma-zimage``: ``torch.bfloat16`` when
      natively supported (RTX 30/40/50, ROCm bf16, Intel Arc XPU bf16), otherwise
      ``torch.float16`` (NVIDIA GTX 10/16 & RTX 20, DirectML, Apple MPS).
    """
    torch_mod = _import_torch(torch_module)
    if torch_mod is None:
        return None

    kind = device_kind.casefold()
    if kind == "cpu":
        return torch_mod.float32

    normalized = normalize_profile(profile)
    if normalized == SDXL_ZIMAGE_PROFILE:
        return torch_mod.float16

    if is_bf16_supported(kind, torch_module=torch_mod):
        return torch_mod.bfloat16
    return torch_mod.float16


def device_vram_gib(device_kind: str, *, torch_module: Any = None) -> float:
    """Return total device VRAM in GiB, or ``0.0`` when unavailable."""
    kind = device_kind.casefold()
    torch_mod = _import_torch(torch_module)
    if torch_mod is None:
        return 0.0

    if kind in ("cuda", "rocm"):
        cuda = getattr(torch_mod, "cuda", None)
        if cuda is not None:
            with contextlib.suppress(Exception):
                props = cuda.get_device_properties("cuda")
                total = float(props.total_memory)
                if total > 0:
                    return total / (1024**3)
            with contextlib.suppress(Exception):
                _free, total = cuda.mem_get_info("cuda")
                if total > 0:
                    return float(total) / (1024**3)
        return 0.0

    if kind == "xpu":
        xpu = getattr(torch_mod, "xpu", None)
        if xpu is not None:
            with contextlib.suppress(Exception):
                props = xpu.get_device_properties("xpu")
                total = float(props.total_memory)
                if total > 0:
                    return total / (1024**3)
        return 0.0

    if kind == "mps":
        mps = getattr(torch_mod, "mps", None)
        if mps is not None:
            rec_fn = getattr(mps, "recommended_max_memory", None)
            if callable(rec_fn):
                with contextlib.suppress(Exception):
                    total = float(rec_fn())
                    if total > 0:
                        return total / (1024**3)
        return 0.0

    return 0.0


def empty_device_cache(device_kind: str, *, torch_module: Any = None) -> None:
    """Release cached allocator memory on the active accelerator if supported."""
    kind = device_kind.casefold()
    torch_mod = _import_torch(torch_module)
    if torch_mod is None:
        return

    if kind in ("cuda", "rocm"):
        cuda = getattr(torch_mod, "cuda", None)
        if cuda is not None and callable(getattr(cuda, "empty_cache", None)):
            with contextlib.suppress(Exception):
                cuda.empty_cache()
    elif kind == "xpu":
        xpu = getattr(torch_mod, "xpu", None)
        if xpu is not None and callable(getattr(xpu, "empty_cache", None)):
            with contextlib.suppress(Exception):
                xpu.empty_cache()
    elif kind == "mps":
        mps = getattr(torch_mod, "mps", None)
        if mps is not None and callable(getattr(mps, "empty_cache", None)):
            with contextlib.suppress(Exception):
                mps.empty_cache()


def make_generator(
    device: Any,
    device_kind: str,
    seed: int | None,
    *,
    torch_module: Any = None,
) -> Any:
    """Create a seeded ``torch.Generator``, safely falling back to CPU on MPS/DirectML."""
    if seed is None:
        return None
    torch_mod = _import_torch(torch_module)
    if torch_mod is None:
        return None

    kind = device_kind.casefold()
    if kind in ("cpu", "mps", "dml"):
        return torch_mod.Generator(device="cpu").manual_seed(seed)

    try:
        return torch_mod.Generator(device=device).manual_seed(seed)
    except Exception:
        return torch_mod.Generator(device="cpu").manual_seed(seed)


def _available_onnx_providers(ort_module: Any = None) -> list[str]:
    ort = ort_module
    if ort is None:
        try:
            ort = importlib.import_module("onnxruntime")
        except Exception:
            return []
    getter = getattr(ort, "get_available_providers", None)
    if not callable(getter):
        return ["CPUExecutionProvider"]
    try:
        providers = list(getter())
        return [str(p) for p in providers] if providers else ["CPUExecutionProvider"]
    except Exception:
        return ["CPUExecutionProvider"]


def select_onnx_providers(prefer_gpu: bool = True, *, ort_module: Any = None) -> list[Any]:
    """Select ordered ONNX Runtime execution providers with safe CPU fallback.

    Honors ``RAIW_ONNX_PROVIDER`` environment override (comma-separated provider names).
    """
    available = _available_onnx_providers(ort_module)
    available_set = set(available)

    override = os.environ.get(ONNX_PROVIDER_ENV, "").strip()
    if override:
        requested = [item.strip() for item in override.split(",") if item.strip()]
        selected = [p for p in requested if not available_set or p in available_set]
        if selected:
            if "CPUExecutionProvider" not in selected and (
                not available_set or "CPUExecutionProvider" in available_set
            ):
                selected.append("CPUExecutionProvider")
            return selected
        logger.warning(
            "%s=%r did not match any available ONNX provider (%s); falling back to auto selection",
            ONNX_PROVIDER_ENV,
            override,
            ", ".join(available) or "none",
        )

    if not prefer_gpu:
        return ["CPUExecutionProvider"]

    ordered = [provider for provider in ONNX_PROVIDER_PRIORITY if provider in available_set]
    if "CPUExecutionProvider" not in ordered:
        ordered.append("CPUExecutionProvider")
    return ordered


def create_onnx_session(
    model_or_bytes: Any,
    *,
    sess_options: Any = None,
    prefer_gpu: bool = True,
    ort_module: Any = None,
) -> Any:
    """Create an ``onnxruntime.InferenceSession`` trying hardware EPs with safe CPU fallback."""
    ort = ort_module if ort_module is not None else importlib.import_module("onnxruntime")
    providers = select_onnx_providers(prefer_gpu=prefer_gpu, ort_module=ort)
    kwargs: dict[str, Any] = {}
    if sess_options is not None:
        kwargs["sess_options"] = sess_options

    try:
        return ort.InferenceSession(model_or_bytes, providers=providers, **kwargs)
    except Exception as exc:
        if providers == ["CPUExecutionProvider"]:
            raise
        logger.warning(
            "ONNX session creation failed with providers %s (%s); falling back to CPUExecutionProvider",
            providers,
            exc,
        )
        return ort.InferenceSession(model_or_bytes, providers=["CPUExecutionProvider"], **kwargs)


def _detect_npu(onnx_providers: list[str]) -> bool:
    """Detect AI NPUs (Intel Core Ultra / AMD Ryzen AI / Qualcomm QNN) without slow commands."""
    if "QNNExecutionProvider" in onnx_providers:
        return True

    # Check OpenVINO runtime if installed (fast in-process check).
    with contextlib.suppress(Exception):
        ov = importlib.import_module("openvino")
        core = ov.Core()
        devices = [str(d).upper() for d in getattr(core, "available_devices", ())]
        if any("NPU" in d for d in devices):
            return True

    # Linux sysfs / devfs check for Intel VPU / AMD XDNA NPU accelerators.
    if sys.platform.startswith("linux"):
        with contextlib.suppress(OSError):
            accel_dir = Path("/sys/class/accel")
            if accel_dir.is_dir() and any(accel_dir.iterdir()):
                return True

    # Fast Windows registry CPU brand string check (no WMI / subprocess).
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                cpu_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                lower = str(cpu_name).casefold()
                if any(token in lower for token in ("core(tm) ultra", "ryzen ai", "snapdragon")):
                    return True

    return False


def _detect_device_name_and_vendor(
    device_kind: str,
    *,
    torch_mod: Any,
) -> tuple[str, str]:
    if device_kind == "cuda":
        name = "NVIDIA CUDA GPU"
        if torch_mod is not None:
            with contextlib.suppress(Exception):
                name = str(torch_mod.cuda.get_device_name(0))
        return name, "nvidia"

    if device_kind == "rocm":
        name = "AMD Radeon ROCm GPU"
        if torch_mod is not None:
            with contextlib.suppress(Exception):
                name = str(torch_mod.cuda.get_device_name(0))
        return name, "amd"

    if device_kind == "xpu":
        name = "Intel Arc XPU"
        if torch_mod is not None:
            with contextlib.suppress(Exception):
                name = str(torch_mod.xpu.get_device_name(0))
        return name, "intel"

    if device_kind == "mps":
        return "Apple Silicon (MPS)", "apple"

    if device_kind == "dml":
        name = "DirectML GPU"
        dml = _import_torch_directml()
        if dml is not None:
            with contextlib.suppress(Exception):
                name = str(dml.device_name(dml.default_device()))
        lower = name.casefold()
        if "nvidia" in lower or "geforce" in lower or "rtx" in lower or "gtx" in lower:
            vendor = "nvidia"
        elif "amd" in lower or "radeon" in lower:
            vendor = "amd"
        elif "intel" in lower or "arc" in lower:
            vendor = "intel"
        else:
            vendor = "amd"
        return name, vendor

    cpu_name = platform.processor() or platform.machine() or "CPU"
    return cpu_name, "cpu"


def _build_supported_profiles(
    accelerator_kind: str,
    vram_gb: float | None,
    bf16_supported: bool,
) -> dict[str, dict[str, Any]]:
    diffsynth_ok = is_diffsynth_supported(accelerator_kind)
    vram_val = vram_gb or 0.0
    prefer_sdxl = (not diffsynth_ok) or (not bf16_supported) or (0.0 < vram_val < 16.0)

    return {
        AUTO_PROFILE: {
            "supported": True,
            "recommended": True,
            "note": (
                "Automatically selects the best profile for the detected vendor and hardware."
                if diffsynth_ok
                else "Automatically routes to sdxl-zimage on this hardware backend."
            ),
        },
        SDXL_ZIMAGE_PROFILE: {
            "supported": True,
            "recommended": prefer_sdxl,
            "note": (
                "FP16-safe SDXL global pass; recommended for GTX/RTX 20, <=12 GB VRAM, AMD DirectML, "
                "Intel Arc, Apple Silicon MPS, and CPU."
            ),
        },
        CHROMA_ZIMAGE_PROFILE: {
            "supported": True,
            "recommended": False,
            "note": (
                "Apache-2.0 Chroma1-HD Diffusers pass "
                f"({'bf16' if bf16_supported else 'fp32' if accelerator_kind == 'cpu' else 'fp16'})."
            ),
        },
        QWEN_ZIMAGE_PROFILE: {
            "supported": diffsynth_ok,
            "recommended": diffsynth_ok and not prefer_sdxl,
            "note": (
                "Highest-fidelity Qwen-Image-2512 + Z-Image two-stage pipeline."
                if diffsynth_ok
                else (
                    f"Requires CUDA, ROCm, or Intel XPU (DiffSynth backend). "
                    f"Use '{SDXL_ZIMAGE_PROFILE}' on {accelerator_kind}."
                )
            ),
        },
        QWEN21_ZIMAGE_PROFILE: {
            "supported": diffsynth_ok,
            "recommended": False,
            "note": (
                "Non-commercial Qwen-Image-2.1 fidelity pipeline (personal/research use only)."
                if diffsynth_ok
                else (
                    f"Requires CUDA, ROCm, or Intel XPU (DiffSynth backend). "
                    f"Use '{SDXL_ZIMAGE_PROFILE}' on {accelerator_kind}."
                )
            ),
        },
    }


def detect_hardware_summary(
    *,
    torch_module: Any = None,
    ort_module: Any = None,
) -> dict[str, Any]:
    """Detect all available GPU/NPU/CPU accelerators and return a structured summary dict."""
    torch_mod = _import_torch(torch_module)
    torch_version = str(getattr(torch_mod, "__version__", "")) or None if torch_mod is not None else None

    device_obj, kind = resolve_torch_device("auto", torch_module=torch_mod)
    device_str = "dml" if kind == "dml" else str(device_obj)
    device_name, vendor = _detect_device_name_and_vendor(kind, torch_mod=torch_mod)

    raw_vram = device_vram_gib(kind, torch_module=torch_mod)
    vram_gb = round(raw_vram, 2) if raw_vram > 0.0 else None

    bf16_supported = is_bf16_supported(kind, torch_module=torch_mod)
    fp16_supported = kind != "cpu"

    onnx_providers = _available_onnx_providers(ort_module)
    selected_onnx = select_onnx_providers(prefer_gpu=True, ort_module=ort_module)
    active_onnx_provider = str(selected_onnx[0]) if selected_onnx else "CPUExecutionProvider"
    npu_detected = _detect_npu(onnx_providers)

    diffusion_devices: list[str] = []
    if torch_mod is not None:
        if _cuda_available(torch_mod):
            diffusion_devices.append("rocm" if _is_rocm(torch_mod) else "cuda")
        if _xpu_available(torch_mod):
            diffusion_devices.append("xpu")
        if _mps_available(torch_mod):
            diffusion_devices.append("mps")
        dml_ok, _ = _dml_available()
        if dml_ok:
            diffusion_devices.append("dml")
    diffusion_devices.append("cpu")

    notes: list[str] = []
    if kind == "cuda" and not bf16_supported:
        notes.append("Pre-Ampere NVIDIA GPU detected (GTX 10/16 or RTX 20); using FP16 automatically instead of BF16.")
    elif kind == "rocm":
        notes.append("AMD ROCm (HIP) GPU detected; CUDA-compatible diffusion pipelines enabled.")
    elif kind == "xpu":
        notes.append("Intel Arc XPU detected; native PyTorch XPU acceleration enabled.")
    elif kind == "mps":
        notes.append("Apple Silicon MPS detected; sdxl-zimage and chroma-zimage enabled with CPU RNG fallback.")
    elif kind == "dml":
        notes.append("Windows DirectML GPU detected; sdxl-zimage and chroma-zimage enabled in FP16.")
    elif kind == "cpu":
        notes.append(
            "No GPU accelerator detected; running in CPU FP32 mode (visible-mark removal and ONNX remain fast)."
        )
    if npu_detected:
        notes.append("AI NPU detected; ONNX models can leverage OpenVINO/QNN/DirectML acceleration.")

    supported_profiles = _build_supported_profiles(kind, vram_gb, bf16_supported)

    info = AcceleratorInfo(
        accelerator_kind=kind,
        vendor=vendor,
        device=device_str,
        device_name=device_name,
        vram_gb=vram_gb,
        bf16_supported=bf16_supported,
        fp16_supported=fp16_supported,
        torch_version=torch_version,
        onnx_providers=onnx_providers,
        active_onnx_provider=active_onnx_provider,
        npu_detected=npu_detected,
        diffusion_devices=diffusion_devices,
        supported_profiles=supported_profiles,
        notes=notes,
    )
    return info.to_dict()
