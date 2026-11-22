"""Local web app backend for remove-ai-watermarks (v0.66+).

FastAPI server wrapping the installed ``remove-ai-watermarks`` library:
  * Image Clean:
      - Quick clean   : 15+ visible AI marks (Gemini sparkle, Doubao/Jimeng/Qwen/
                        Kling/OpenArt/Samsung/Microsoft/LiblibAI/AI生成...) filled
                        with big-LaMa, MI-GAN, or OpenCV + fast lossless AI metadata strip.
      - Deep clean    : visible + invisible (SynthID / InvisMark / Content Seal)
                        via CUDA diffusion (SDXL-ZImage, Qwen-2.1 7B Fidelity,
                        Qwen-2512, Chroma1-HD, or Auto router) + smart auto-tiling
                        + metadata strip.
      - Metadata only : instant lossless strip of C2PA/EXIF/XMP/IPTC/TC260.
  * Manual Region Erase:
      - Interactive rectangle boxes or freehand brush strokes/mask erased via big-LaMa,
        MI-GAN, or OpenCV, EXIF-orientation-safe, preserving alpha + display tags and
        stripping metadata.
  * Inspect & AI Detect:
      - Single-decode parallel provenance report (C2PA, EXIF, XMP, TC260, visible marks,
        SynthID provenance) + Source Classify v8 (10-provider + model version + synthetic
        detection from pixels alone). Works on images and videos.
  * Video Clean:
      - 18 registered visible video marks (Sora 2, Veo, Seedance, Kling, Hailuo,
        Doubao, Dola, Vidu, Wan...) + verified lossless metadata strip + opt-in invisible
        video regeneration (Auto / SynthID / Seedance / Wan 2.1).
  * Model & Storage Manager:
      - Live download / pause / re-check / folder setting / safe weight cleanup
        for both lightweight ONNX models (~295 MB) and diffusion profiles.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import functools
import gc
import json
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

import remove_ai_watermarks as raiw
from remove_ai_watermarks.api import (
    InvisibleOptions,
    MetadataStripIncomplete,
    remove_all,
    remove_visible_detailed,
)
from webapp import model_status

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from typing import BinaryIO

log = logging.getLogger(__name__)

# Apply saved model directory before any DiffSynth module loads weights.
model_status.apply_saved_model_dir()

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
INDEX_HTML = HERE / "index.html"
STATIC_DIR = HERE / "static"

STUDIO_NAME = "Remove AI Watermarks Studio"
UPSTREAM_REPO = "wiltodelta/remove-ai-watermarks"

# --- Security constants ------------------------------------------------------

_ALLOWED_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", "testserver"})
_SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})
_MAX_IMAGE_BYTES = 250 * 1024 * 1024  # 250 MB
_MAX_VIDEO_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB
_MAX_BOXES = 256
_MAX_STROKES = 2048
_MAX_STROKE_POINTS = 200_000
_UPLOAD_CHUNK_BYTES = 1024 * 1024  # 1 MB
_HARDWARE_ACCELERATOR_KINDS: frozenset[str] = frozenset({"cuda", "rocm", "xpu", "mps", "dml"})

# --- Universal hardware accelerator helpers ----------------------------------


def _detect_hardware_summary() -> dict[str, Any]:
    """Return universal GPU/NPU/CPU summary via ``accelerator.py`` with a safe fallback."""
    try:
        from remove_ai_watermarks._internal import accelerator

        summary = accelerator.detect_hardware_summary()
        if isinstance(summary, dict):
            return summary
    except Exception:
        log.debug("accelerator.detect_hardware_summary unavailable; using fallback probe", exc_info=True)

    accel_kind = "cpu"
    vendor = "cpu"
    device = "cpu"
    device_name = "CPU"
    vram_gb: float | None = None
    bf16_supported = False
    fp16_supported = False
    torch_ver: str | None = None
    diffusion_devices: list[str] = ["cpu"]

    with contextlib.suppress(Exception):
        import torch

        torch_ver = torch.__version__
        if torch.cuda.is_available():
            is_rocm = bool(getattr(torch.version, "hip", None))
            accel_kind = "rocm" if is_rocm else "cuda"
            vendor = "amd" if is_rocm else "nvidia"
            device = "cuda"
            device_name = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            vram_gb = round(props.total_memory / (1024**3), 1)
            fp16_supported = True
            bf16_supported = bool(getattr(torch.cuda, "is_bf16_supported", lambda: False)())
            diffusion_devices.insert(0, accel_kind)
        elif hasattr(torch, "xpu") and torch.xpu.is_available():
            accel_kind = "xpu"
            vendor = "intel"
            device = "xpu"
            device_name = torch.xpu.get_device_name(0)
            props = torch.xpu.get_device_properties(0)
            vram_gb = round(props.total_memory / (1024**3), 1)
            fp16_supported = True
            bf16_supported = bool(getattr(torch.xpu, "is_bf16_supported", lambda: True)())
            diffusion_devices.insert(0, "xpu")
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            accel_kind = "mps"
            vendor = "apple"
            device = "mps"
            device_name = "Apple Silicon (MPS)"
            fp16_supported = True
            diffusion_devices.insert(0, "mps")

    onnx_providers: list[str] = []
    with contextlib.suppress(Exception):
        import onnxruntime as ort

        onnx_providers = list(ort.get_available_providers())
    active_onnx = onnx_providers[0] if onnx_providers else "CPUExecutionProvider"
    npu_detected = any(p in onnx_providers for p in ("OpenVINOExecutionProvider", "QNNExecutionProvider"))

    has_gpu = accel_kind in _HARDWARE_ACCELERATOR_KINDS
    supported_profiles = {
        pid: {
            "supported": True,
            "recommended": pid == model_status.DEFAULT_PROFILE,
            "note": meta.get("notes", ""),
        }
        for pid, meta in model_status.PROFILE_META.items()
    }
    return {
        "accelerator_kind": accel_kind,
        "vendor": vendor,
        "device": device,
        "device_name": device_name,
        "vram_gb": vram_gb,
        "bf16_supported": bf16_supported,
        "fp16_supported": fp16_supported,
        "torch_version": torch_ver,
        "onnx_providers": onnx_providers,
        "active_onnx_provider": active_onnx,
        "npu_detected": npu_detected,
        "diffusion_devices": diffusion_devices,
        "supported_profiles": supported_profiles,
        "notes": [] if has_gpu else ["No GPU accelerator detected; Quick Clean uses CPU/ONNX."],
    }


def _empty_accelerator_cache(device_kind: str | None = None) -> None:
    """Release cached GPU/accelerator memory across CUDA, ROCm, Intel XPU, and Apple MPS."""
    try:
        from remove_ai_watermarks._internal import accelerator

        kind = device_kind or str(_static_health().get("accelerator_kind") or "cpu")
        accelerator.empty_device_cache(kind)
        return
    except Exception:
        log.debug("accelerator.empty_device_cache unavailable; using torch fallback", exc_info=True)

    with contextlib.suppress(Exception):
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            torch.xpu.empty_cache()
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            torch.mps.empty_cache()


# --- GPU engine: built once, lazily, and serialized --------------------------

_engine_lock = threading.Lock()
_engines: dict[tuple[str, bool, str | None], Any] = {}
_loaded_lock = threading.Lock()
_loaded_profiles: set[str] = set()
_active_sink: Any = None


def _engine_progress(msg: str) -> None:
    sink = _active_sink
    if sink is not None:
        sink(msg)


def _clear_engines() -> None:
    if not _engines:
        return
    _engines.clear()
    with _loaded_lock:
        _loaded_profiles.clear()
    gc.collect()
    _empty_accelerator_cache()


def _get_engine(profile: str, *, cpu_offload: bool = False, device: str | None = None) -> Any:
    """Return the InvisibleEngine for (profile, cpu_offload, device), building it on first use."""
    key = (profile, cpu_offload, device)
    cached = _engines.get(key)
    if cached is not None:
        return cached
    from remove_ai_watermarks.invisible_engine import InvisibleEngine

    _clear_engines()
    engine = InvisibleEngine(
        device=device,
        pipeline=profile,
        progress_callback=_engine_progress,
        cpu_offload=cpu_offload,
    )
    _engines[key] = engine
    with _loaded_lock:
        _loaded_profiles.add(profile)
    return engine


# --- Bounded thread pools & ONNX session synchronization ---------------------

_pools_lock = threading.Lock()
_meta_pool: ThreadPoolExecutor | None = None
_quick_pool: ThreadPoolExecutor | None = None
_deep_pool: ThreadPoolExecutor | None = None
_video_pool: ThreadPoolExecutor | None = None
_inspect_pool: ThreadPoolExecutor | None = None


def _ensure_pools() -> None:
    """Create bounded thread pools if not yet created (or after a previous lifespan shutdown)."""
    global _meta_pool, _quick_pool, _deep_pool, _video_pool, _inspect_pool
    with _pools_lock:
        if _meta_pool is None:
            _meta_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="raiw-meta")
        if _quick_pool is None:
            _quick_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="raiw-quick")
        if _deep_pool is None:
            _deep_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="raiw-deep")
        if _video_pool is None:
            _video_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="raiw-video")
        if _inspect_pool is None:
            _inspect_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="raiw-inspect")


def _get_pool(kind: str) -> ThreadPoolExecutor:
    global _meta_pool, _quick_pool, _deep_pool, _video_pool, _inspect_pool
    with _pools_lock:
        if kind == "meta":
            if _meta_pool is None:
                _meta_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="raiw-meta")
            return _meta_pool
        if kind == "quick":
            if _quick_pool is None:
                _quick_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="raiw-quick")
            return _quick_pool
        if kind == "deep":
            if _deep_pool is None:
                _deep_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="raiw-deep")
            return _deep_pool
        if kind == "video":
            if _video_pool is None:
                _video_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="raiw-video")
            return _video_pool
        if _inspect_pool is None:
            _inspect_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="raiw-inspect")
        return _inspect_pool


def _shutdown_pools() -> None:
    global _meta_pool, _quick_pool, _deep_pool, _video_pool, _inspect_pool
    with _pools_lock:
        pools = (_meta_pool, _quick_pool, _deep_pool, _video_pool, _inspect_pool)
        _meta_pool = _quick_pool = _deep_pool = _video_pool = _inspect_pool = None
    for pool in pools:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)


_ensure_pools()

_onnx_init_locks: dict[str, threading.Lock] = {
    "migan": threading.Lock(),
    "lama": threading.Lock(),
}
_lama_sem = threading.Semaphore(1)


def _ensure_onnx_session(backend: str) -> None:
    """Serialize first-time ONNX session creation per backend to prevent races/double loads."""
    lock = _onnx_init_locks.get(backend)
    if lock is None:
        return
    with lock:
        from remove_ai_watermarks import region_eraser

        if backend == "migan":
            region_eraser._get_migan_session()
        elif backend == "lama":
            region_eraser._get_lama_session()


def _warmup_cached_onnx() -> None:
    """Quietly warm up already-cached ONNX sessions at startup (never triggers downloads)."""
    with contextlib.suppress(Exception):
        from remove_ai_watermarks import region_eraser

        if region_eraser.migan_available() and model_status.lightweight_spec_cached("migan"):
            _ensure_onnx_session("migan")
        if region_eraser.lama_available() and model_status.lightweight_spec_cached("lama"):
            _ensure_onnx_session("lama")


# --- Disk-backed JobManager with replayable async SSE & cancellation ---------

_MAX_COMPLETED_JOBS = 64
_JOB_TTL_SECONDS = 30 * 60


@dataclass
class JobRecord:
    """State of one background cleaning/erase job, stored on disk rather than RAM."""

    job_id: str
    job_dir: Path
    out_name: str
    ext: str
    kind: str  # "image" | "video" | "erase"
    result_path: Path | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    terminal: bool = False
    cancelled: threading.Event = field(default_factory=threading.Event)
    summary: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = field(default_factory=list)


class JobManager:
    """Thread-safe disk-backed job store with replayable SSE events and TTL pruning."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}
        self._root_dir: Path | None = None

    def _ensure_root_unlocked(self) -> Path:
        if self._root_dir is None or not self._root_dir.is_dir():
            self._root_dir = Path(tempfile.mkdtemp(prefix="raiw_webapp_jobs_"))
        return self._root_dir

    def create_job(self, out_name: str, ext: str, kind: str) -> JobRecord:
        job_id = uuid.uuid4().hex
        with self._lock:
            root = self._ensure_root_unlocked()
            job_dir = root / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            rec = JobRecord(job_id=job_id, job_dir=job_dir, out_name=out_name, ext=ext, kind=kind)
            self._jobs[job_id] = rec
            return rec

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _notify_unlocked(self, rec: JobRecord) -> None:
        for loop, ev in list(rec.waiters):
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(ev.set)

    def emit(self, job_id: str, payload: dict[str, Any], *, terminal: bool = False) -> bool:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None or rec.terminal:
                return False
            rec.events.append(payload)
            if terminal:
                rec.terminal = True
                rec.finished_at = time.monotonic()
            self._notify_unlocked(rec)
            return True

    def complete(self, job_id: str, result_path: Path, summary: dict[str, Any]) -> bool:
        drop_result = False
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None or rec.terminal or rec.cancelled.is_set():
                drop_result = True
            else:
                rec.result_path = result_path
                rec.summary = summary
                rec.events.append({"type": "done", "message": "Done", "percent": 100, "summary": summary})
                rec.terminal = True
                rec.finished_at = time.monotonic()
                self._notify_unlocked(rec)
                return True
        if drop_result:
            with contextlib.suppress(OSError):
                result_path.unlink(missing_ok=True)
        return False

    def fail(self, job_id: str, message: str) -> bool:
        return self.emit(job_id, {"type": "error", "message": message}, terminal=True)

    def cancel(self, job_id: str) -> tuple[bool, str]:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return False, "not_found"
            rec.cancelled.set()
            if rec.terminal:
                return False, "already_finished"
            rec.events.append({"type": "cancelled", "message": "Cancelled by user"})
            rec.terminal = True
            rec.finished_at = time.monotonic()
            self._notify_unlocked(rec)
            return True, "cancelled"

    def register_waiter(self, job_id: str, loop: asyncio.AbstractEventLoop, ev: asyncio.Event) -> bool:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return False
            rec.waiters.append((loop, ev))
            return True

    def unregister_waiter(self, job_id: str, loop: asyncio.AbstractEventLoop, ev: asyncio.Event) -> None:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return
            with contextlib.suppress(ValueError):
                rec.waiters.remove((loop, ev))

    def read_events_from(self, job_id: str, idx: int) -> tuple[list[dict[str, Any]], bool]:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return [], True
            return list(rec.events[idx:]), rec.terminal

    def get_ready_result(self, job_id: str) -> tuple[Path, str, str] | None:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None or rec.result_path is None:
                return None
            result_path = rec.result_path
            ext = rec.ext
            out_name = rec.out_name
        if not result_path.is_file():
            return None
        return result_path, ext, out_name

    def prune(self) -> None:
        now = time.monotonic()
        dirs_to_remove: list[Path] = []
        with self._lock:
            expired = [
                jid
                for jid, rec in self._jobs.items()
                if rec.finished_at is not None and (now - rec.finished_at) > _JOB_TTL_SECONDS
            ]
            for jid in expired:
                rec = self._jobs.pop(jid, None)
                if rec is not None:
                    dirs_to_remove.append(rec.job_dir)

            remaining = sorted(
                ((jid, rec.finished_at) for jid, rec in self._jobs.items() if rec.finished_at is not None),
                key=lambda x: x[1],
            )
            while len(remaining) > _MAX_COMPLETED_JOBS:
                old_id, _ = remaining.pop(0)
                rec = self._jobs.pop(old_id, None)
                if rec is not None:
                    dirs_to_remove.append(rec.job_dir)

        for d in dirs_to_remove:
            shutil.rmtree(d, ignore_errors=True)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for rec in self._jobs.values() if not rec.terminal)

    def cancel_all_active(self) -> int:
        cancelled = 0
        with self._lock:
            for rec in self._jobs.values():
                if not rec.terminal:
                    rec.cancelled.set()
                    rec.events.append({"type": "cancelled", "message": "Cancelled due to Studio shutdown"})
                    rec.terminal = True
                    rec.finished_at = time.monotonic()
                    self._notify_unlocked(rec)
                    cancelled += 1
        return cancelled

    def cleanup_all(self) -> None:
        with self._lock:
            self._jobs.clear()
            root = self._root_dir
            self._root_dir = None
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)


_job_mgr = JobManager()
atexit.register(_job_mgr.cleanup_all)


# --- App creation & Lifespan -------------------------------------------------


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _ensure_pools()
    threading.Thread(target=_warmup_cached_onnx, name="raiw-onnx-warmup", daemon=True).start()
    _start_lifecycle_watchdog()
    try:
        yield
    finally:
        _stop_lifecycle_watchdog()
        _shutdown_pools()
        _job_mgr.cleanup_all()


app = FastAPI(title=STUDIO_NAME, version=raiw.__version__, lifespan=_lifespan)


class _NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Any) -> Response:
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


if STATIC_DIR.is_dir():
    app.mount("/static", _NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")


def _extract_hostname(host_header: str) -> str:
    raw = (host_header or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end != -1 else ""
    return raw.split(":", 1)[0]


@app.middleware("http")
async def _local_security_middleware(request: Request, call_next: Callable[..., Any]) -> Response:
    host = _extract_hostname(request.headers.get("host", ""))
    if host not in _ALLOWED_HOSTS:
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)

    origin = request.headers.get("origin")
    if origin:
        parsed = urllib.parse.urlparse(origin)
        orig_host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or orig_host not in _ALLOWED_HOSTS:
            return JSONResponse({"detail": "Forbidden origin"}, status_code=403)

    if request.method.upper() not in _SAFE_METHODS and request.headers.get("x-raiw-request") != "1":
        return JSONResponse({"detail": "Missing or invalid X-RAIW-Request header"}, status_code=403)

    return await call_next(request)


# --- Media types, validation & upload helpers --------------------------------

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpe": "image/jpeg",
    ".jfif": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".avif": "image/avif",
}

_VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".flv": "video/x-flv",
}

_ALL_MIME = {**_IMAGE_MIME, **_VIDEO_MIME}
_VALID_MODES = frozenset({"quick", "deep", "metadata"})
_VALID_BACKENDS = ("auto", "lama", "migan", "cv2")
_VALID_DEVICES = ("auto", "cuda", "rocm", "xpu", "mps", "dml", "cpu")
_VALID_UPDATE_SOURCES = frozenset({"auto", "origin", "upstream"})
_VALID_SENSITIVITIES = ("auto", "strict")
_VALID_VENDORS = ("google", "openai", "microsoft", "meta")
_VALID_VIDEO_INVISIBLE_PROFILES = (
    "auto",
    "synthid",
    "seedance-experimental",
    "wan21-synthid-experimental",
    "wan21-seedance-experimental",
)
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_STEP_RE = re.compile(r"(\d+)\s*/\s*(\d+)")

_STAGE_TEXT = {
    "visible": "Removing visible watermark…",
    "invisible": "Removing hidden watermark…",
    "metadata": "Stripping AI metadata…",
}
_STAGE_PCT = {"visible": 8, "invisible": 14, "metadata": 92}


class _UploadTooLargeError(Exception):
    pass


class _BoundedReader:
    """File-like wrapper for ``shutil.copyfileobj`` that enforces a size limit and captures magic bytes."""

    def __init__(self, src: BinaryIO, max_bytes: int) -> None:
        self._src = src
        self._max = max_bytes
        self.total = 0
        self.head = bytearray()

    def read(self, size: int = -1) -> bytes:
        chunk = self._src.read(size)
        if not chunk:
            return b""
        self.total += len(chunk)
        if self.total > self._max:
            raise _UploadTooLargeError
        if len(self.head) < 64:
            need = 64 - len(self.head)
            self.head.extend(chunk[:need])
        return chunk


def _stream_upload(file: UploadFile, dst: Path, *, max_bytes: int) -> tuple[int, bytes]:
    """Stream ``file`` straight to ``dst`` via ``shutil.copyfileobj``, enforcing non-empty and max_bytes."""
    reader = _BoundedReader(file.file, max_bytes)
    try:
        with dst.open("wb") as fh:
            shutil.copyfileobj(cast("Any", reader), fh, length=_UPLOAD_CHUNK_BYTES)
    except _UploadTooLargeError as exc:
        with contextlib.suppress(OSError):
            dst.unlink(missing_ok=True)
        mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File exceeds maximum size limit ({mb} MB).") from exc

    if reader.total == 0:
        with contextlib.suppress(OSError):
            dst.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    return reader.total, bytes(reader.head)


def _safe_basename(raw: str | None, fallback: str) -> str:
    """Normalize an uploaded filename to a safe basename (no path traversal, control chars, or leading dots)."""
    text = (raw or "").replace("\\", "/")
    name = Path(text).name
    name = re.sub(r"[\x00-\x1f\x7f]+", "", name).lstrip(". ").strip()
    return name or fallback


def _sniff_media_ext(head: bytes) -> str | None:
    """Infer file extension from magic bytes when upload extension is missing or unknown."""
    if len(head) < 4:
        return None
    if head.startswith(_PNG_SIG):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:4] == b"RIFF" and len(head) >= 12:
        if head[8:12] == b"WEBP":
            return ".webp"
        if head[8:12] == b"AVI ":
            return ".avi"
    if head.startswith(b"BM"):
        return ".bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return ".tiff"
    if head.startswith(b"FLV"):
        return ".flv"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm" if b"webm" in head.lower() else ".mkv"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return ".avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx"):
            return ".heic"
        if brand in (b"mif1", b"msf1", b"heif"):
            return ".heif"
        if brand == b"qt  ":
            return ".mov"
        if brand == b"M4V ":
            return ".m4v"
        return ".mp4"
    return None


def _resolve_image_ext(filename: str, head: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_MIME:
        return ext
    sniffed = _sniff_media_ext(head)
    if sniffed in _IMAGE_MIME:
        return sniffed
    return ".png"


def _resolve_video_ext(filename: str, head: bytes) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext in _VIDEO_MIME:
        return ext
    sniffed = _sniff_media_ext(head)
    if sniffed in _VIDEO_MIME:
        return sniffed
    return None


def _content_disposition(filename: str, inline: bool = False) -> str:
    """RFC 5987 safe Content-Disposition header (handles Thai/Unicode filenames)."""
    disp = "inline" if inline else "attachment"
    ascii_fallback = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip() or "cleaned_file"
    ascii_fallback = ascii_fallback.replace('"', "")
    encoded = urllib.parse.quote(filename, safe="")
    return f'{disp}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


def _parse_bool(raw: str | bool | None, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    val = str(raw).strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


def _parse_finite_float(val: float, name: str, lo: float, hi: float) -> float:
    if isinstance(val, bool) or not math.isfinite(val):
        raise HTTPException(status_code=400, detail=f"Invalid numeric value for {name}.")
    return max(lo, min(hi, float(val)))


def _unlink_quietly(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


# --- EXIF orientation helpers (C1) -------------------------------------------

_EXIF_ORIENTATION_TAG = 0x0112
# Containers whose decoder in image_io.read_bgr_and_alpha already rotates pixels upright.
_AUTO_ORIENTED_FORMATS: frozenset[str] = frozenset({"TIFF", "HEIF"})


def _read_format_and_exif_orientation(path: Path) -> tuple[str | None, int]:
    """Return ``(pil_format, exif_orientation)`` without decoding pixels."""
    with contextlib.suppress(Exception):
        from PIL import Image

        from remove_ai_watermarks import image_io

        image_io._register_heif()
        with Image.open(path) as im:
            fmt = im.format
            orient = im.getexif().get(_EXIF_ORIENTATION_TAG, 1)
            return fmt, int(orient) if isinstance(orient, int) and 1 <= orient <= 8 else 1
    return None, 1


def _apply_exif_orientation(arr: Any, orient: int) -> Any:
    """Transpose an ndarray upright to match ``PIL.ImageOps.exif_transpose``."""
    import cv2

    if orient == 2:
        return cv2.flip(arr, 1)
    if orient == 3:
        return cv2.rotate(arr, cv2.ROTATE_180)
    if orient == 4:
        return cv2.flip(arr, 0)
    if orient == 5:
        return cv2.transpose(arr)
    if orient == 6:
        return cv2.rotate(arr, cv2.ROTATE_90_CLOCKWISE)
    if orient == 7:
        return cv2.flip(cv2.transpose(arr), -1)
    if orient == 8:
        return cv2.rotate(arr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return arr


def _probe_image_dimensions(path: Path) -> tuple[int, int] | None:
    """Read image ``(width, height)`` from container header without full decode (<1ms)."""
    with contextlib.suppress(Exception):
        from PIL import Image

        from remove_ai_watermarks import image_io

        image_io._register_heif()
        with Image.open(path) as im:
            w, h = im.size
            return int(w), int(h)
    return None


# --- Fast-path 8-bit PNG metadata stripping ----------------------------------

# Critical & pure colour/display PNG chunks that never carry AI provenance or EXIF/XMP/C2PA.
_PNG_SAFE_DISPLAY_CHUNKS: frozenset[bytes] = frozenset(
    {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",
        b"cHRM",
        b"gAMA",
        b"iCCP",
        b"sBIT",
        b"sRGB",
        b"bKGD",
        b"hIST",
        b"pHYs",
        b"sPLT",
        b"cICP",
        b"mDCv",
        b"cLLi",
    }
)


def _is_png_file(path: Path) -> bool:
    if path.suffix.lower() == ".png":
        return True
    with contextlib.suppress(OSError), path.open("rb") as fh:
        return fh.read(8) == _PNG_SIG
    return False


def _png_only_display_chunks(path: Path) -> bool:
    """Verify in <1ms (zero zlib/pixel decode) that a PNG holds ONLY safe display chunks.

    Walks chunk headers via ``seek()`` over payloads. Returns ``True`` strictly when the
    file starts with the PNG signature, terminates cleanly at ``IEND`` with zero trailing
    bytes, and every chunk type belongs to ``_PNG_SAFE_DISPLAY_CHUNKS`` (so no ``caBX``,
    ``tEXt``, ``zTXt``, ``iTXt``, ``eXIf``, or unknown chunks exist). Any anomaly returns
    ``False`` so the caller falls back to full ``get_ai_metadata`` verification.
    """
    try:
        file_size = path.stat().st_size
        if file_size < 33:
            return False
        with path.open("rb") as fh:
            if fh.read(8) != _PNG_SIG:
                return False
            pos = 8
            saw_ihdr = False
            while pos + 12 <= file_size:
                hdr = fh.read(8)
                if len(hdr) != 8:
                    return False
                (length,) = struct.unpack(">I", hdr[:4])
                ctype = hdr[4:8]
                next_pos = pos + 12 + length
                if next_pos > file_size:
                    return False
                if ctype not in _PNG_SAFE_DISPLAY_CHUNKS:
                    return False
                if ctype == b"IHDR":
                    saw_ihdr = True
                if ctype == b"IEND":
                    return saw_ihdr and length == 0 and next_pos == file_size
                fh.seek(length + 4, os.SEEK_CUR)
                pos = next_pos
    except OSError:
        return False
    return False


def _fast_strip_output(dst: Path) -> None:
    """Fast metadata strip for freshly written image outputs.

    For PNGs, first verifies chunk headers in <1ms via ``_png_only_display_chunks``
    (skipping Pillow's full zlib pixel decode inside ``get_ai_metadata``). When AI
    metadata or text/EXIF chunks ARE present (e.g. a no-op copy), strips PNG chunks
    losslessly (~20ms) before falling back to ``strip_written_output``.
    """
    if _is_png_file(dst) and _png_only_display_chunks(dst):
        return

    from remove_ai_watermarks import metadata as meta_mod

    if not meta_mod.get_ai_metadata(dst):
        return

    if _is_png_file(dst):
        strip_png = getattr(meta_mod, "_strip_png_metadata_lossless", None)
        if callable(strip_png):
            tmp_dst = dst.with_name(f"{dst.stem}.strip_tmp{dst.suffix}")
            try:
                if (
                    strip_png(dst, tmp_dst, True)
                    and tmp_dst.is_file()
                    and (_png_only_display_chunks(tmp_dst) or not meta_mod.get_ai_metadata(tmp_dst))
                ):
                    os.replace(tmp_dst, dst)
                    return
            finally:
                _unlink_quietly(tmp_dst)

    leftover = meta_mod.strip_written_output(dst)
    if leftover:
        raise MetadataStripIncomplete(set(leftover))


def _fast_strip_metadata_only(src: Path, dst: Path) -> None:
    """Metadata-only strip using lossless PNG chunk stripping when possible (~20ms)."""
    from remove_ai_watermarks import metadata as meta_mod

    if _is_png_file(src):
        strip_png = getattr(meta_mod, "_strip_png_metadata_lossless", None)
        if callable(strip_png) and strip_png(src, dst, True) and dst.is_file():
            if _png_only_display_chunks(dst):
                return
            leftover = meta_mod.get_ai_metadata(dst)
            if not leftover:
                return
            _unlink_quietly(dst)

    _written, leftover = meta_mod.strip_and_verify(src, dst)
    if leftover:
        raise MetadataStripIncomplete(set(leftover))


# --- Cached static hardware/dependency probes --------------------------------


@functools.lru_cache(maxsize=1)
def _static_health() -> dict[str, Any]:
    from remove_ai_watermarks import optional_deps, region_eraser, source_classify
    from remove_ai_watermarks.invisible_engine import is_available

    hw = _detect_hardware_summary()
    accel_kind = str(hw.get("accelerator_kind") or "cpu")
    gpu = accel_kind in _HARDWARE_ACCELERATOR_KINDS
    device_name = str(hw.get("device_name") or hw.get("device") or "cpu")
    device = device_name if gpu else "cpu"

    return {
        "studio_name": STUDIO_NAME,
        "upstream_repo": UPSTREAM_REPO,
        "version": raiw.__version__,
        "deep_available": is_available(),
        "gpu": gpu,
        "device": device,
        "vram_gb": hw.get("vram_gb"),
        "torch_version": hw.get("torch_version"),
        "lama_available": region_eraser.lama_available(),
        "migan_available": region_eraser.migan_available(),
        "source_classify_available": source_classify.is_available(),
        "video_available": optional_deps.module_available("cv2", "numpy", "av"),
        "heif_available": optional_deps.module_available("pillow_heif"),
        "hardware": hw,
        "accelerator_kind": accel_kind,
        "vendor": str(hw.get("vendor") or "cpu"),
        "device_name": device_name,
        "bf16_supported": bool(hw.get("bf16_supported", False)),
        "onnx_providers": list(hw.get("onnx_providers") or []),
        "active_onnx_provider": str(hw.get("active_onnx_provider") or "CPUExecutionProvider"),
        "npu_detected": bool(hw.get("npu_detected", False)),
        "diffusion_devices": list(hw.get("diffusion_devices") or ["cpu"]),
        "supported_profiles": dict(hw.get("supported_profiles") or {}),
    }


# --- Progress helpers & background job runners -------------------------------


def _translate_engine_msg(msg: str, first_load: bool) -> tuple[int | None, str]:
    low = msg.lower()
    step = _STEP_RE.search(msg)
    if step:
        cur, tot = int(step.group(1)), int(step.group(2))
        if "tile" in low:
            pct = 18 + int(58 * cur / max(1, tot))
            return pct, f"Removing hidden watermark — tile {cur}/{tot}"
        if "face" in low:
            pct = 78 + int(10 * cur / max(1, tot))
            return pct, f"Repairing face {cur}/{tot}…"
        pct = 18 + int(70 * cur / max(1, tot))
        return pct, f"Removing hidden watermark — step {cur}/{tot}"
    if "alignment" in low:
        return 89, "Evaluating guarded alignment & LPIPS fidelity…"
    if "face" in low or "z-image" in low or "sam" in low:
        return 76, msg.strip().rstrip(".")
    if "running " in low and "pass" in low:
        return 25, msg.strip().rstrip(".")
    if any(k in low for k in ("weight", "controlnet", "vae", "loading ", "moving model", "streaming ")):
        if first_load:
            return 14, msg.strip().rstrip(".") or "Loading model weights…"
        return 16, msg.strip().rstrip(".") or "Loading model…"
    if "adaptive polish" in low or "sharpen" in low or "humanizer" in low:
        return 90, msg.strip().rstrip(".")
    return None, msg.strip().rstrip(".") or "Working…"


def _emit(job_id: str, message: str, percent: int | None, **extra: Any) -> None:
    payload: dict[str, Any] = {"type": "status", "message": message, "percent": percent}
    payload.update(extra)
    _job_mgr.emit(job_id, payload)


def _download_watcher(job_id: str, profile: str, stop: threading.Event) -> None:
    while not stop.wait(1.5):
        try:
            snap = model_status.quick_download_snapshot(profile)
        except Exception:
            log.debug("quick download snapshot failed", exc_info=True)
            continue
        active = [m for m in snap["models"] if m["rate_mb_s"]]
        if not active:
            continue
        cur = active[0]
        got = cur["bytes"] / 1e9
        tot = (cur["total"] or 0) / 1e9
        size = f"{got:.1f} / {tot:.1f} GB" if tot else f"{got:.1f} GB"
        msg = f"Downloading {cur['repo_id']} — {size} at {cur['rate_mb_s']:.0f} MB/s"
        if not _job_mgr.emit(job_id, {"type": "status", "message": msg, "percent": None, "download": snap}):
            return


def _run_image_job(
    job_id: str,
    src: Path,
    dst: Path,
    mode: str,
    profile: str,
    backend: str,
    sensitivity: str,
    force: bool,
    vendor: str | None,
    cpu_offload: bool,
    adaptive_polish: bool | None,
    humanize: float,
    unsharp: float,
    tile_mode: str = "auto",
    device: str | None = None,
) -> None:
    rec = _job_mgr.get(job_id)
    if rec is None:
        _unlink_quietly(src)
        return
    t0 = time.monotonic()
    try:
        if rec.cancelled.is_set():
            return

        summary: dict[str, Any] = {
            "mode": mode,
            "out_name": rec.out_name,
            "visible_marks": [],
            "visible_status": None,
            "invisible_outcome": None,
            "backend": backend,
            "pipeline": profile if mode == "deep" else None,
            "device": device or "auto",
            "metadata_stripped": True,
            "auto_tiled": False,
        }

        if mode == "metadata":
            from remove_ai_watermarks.metadata import get_ai_metadata

            _emit(job_id, "Inspecting & stripping AI metadata (lossless)…", 35)
            detected = get_ai_metadata(src)
            if rec.cancelled.is_set():
                return
            _fast_strip_metadata_only(src, dst)
            summary["metadata_found"] = sorted(detected.keys())
            _emit(job_id, "Metadata stripped cleanly", 95)

        elif mode == "deep":
            from remove_ai_watermarks.invisible_engine import is_available

            if not is_available():
                raise RuntimeError(
                    "Deep clean needs the diffusion dependencies (`qwen-zimage`) and a supported "
                    "GPU (NVIDIA CUDA, AMD ROCm/DirectML, Intel Arc XPU, Apple MPS) or CPU runtime."
                )

            # Determine tiling (auto-tile large images on <=18.5 GB GPUs)
            use_tile = False
            auto_tiled = False
            tile_norm = tile_mode.strip().lower()
            if tile_norm in ("true", "1", "yes", "on"):
                use_tile = True
            elif tile_norm in ("false", "0", "no", "off"):
                use_tile = False
            else:
                vram_gb = _static_health().get("vram_gb")
                dims = _probe_image_dimensions(src)
                if (
                    isinstance(vram_gb, (int, float))
                    and vram_gb <= 18.5
                    and dims is not None
                    and max(dims) > 1536
                    and profile in ("sdxl-zimage", "qwen-zimage", "auto")
                ):
                    use_tile = True
                    auto_tiled = True
                    summary["auto_tiled"] = True
                    _emit(job_id, f"Auto-tiling {dims[0]}\u00d7{dims[1]} for {vram_gb:g} GB VRAM…", 5)

            first_load = (profile, cpu_offload, device) not in _engines
            if first_load:
                _emit(job_id, f"Preparing {profile} model stack…", 6)

            last_pct = [5]

            def sink(m: str) -> None:
                pct, text = _translate_engine_msg(m, first_load)
                if pct is not None:
                    last_pct[0] = max(last_pct[0], pct)
                _job_mgr.emit(job_id, {"type": "status", "message": text, "percent": last_pct[0]})

            def on_stage(stage: str, detail: str) -> None:
                text = _STAGE_TEXT.get(stage)
                if text is None:
                    return
                if stage == "visible" and detail:
                    text = f"Visible mark removed: {detail}"
                elif stage == "invisible" and detail.startswith("strength="):
                    text = f"Running {profile} ({detail})…"
                elif stage == "invisible" and detail == "removed":
                    text = "Hidden watermark removed"
                    last_pct[0] = max(last_pct[0], 91)
                elif stage == "invisible" and detail == "no-signal":
                    text = "No hidden-watermark metadata detected (skipped; enable Force to scrub anyway)"
                elif stage == "invisible" and detail == "unavailable":
                    text = "Hidden-watermark engine unavailable — visible + metadata only"
                last_pct[0] = max(last_pct[0], _STAGE_PCT[stage])
                _job_mgr.emit(job_id, {"type": "status", "message": text, "percent": last_pct[0]})

            global _active_sink
            with _engine_lock:
                if rec.cancelled.is_set():
                    return
                stop_watch = threading.Event()
                watcher: threading.Thread | None = None
                try:
                    needs_watch = not model_status.quick_download_snapshot(profile).get("all_complete", False)
                except Exception:
                    needs_watch = True
                if needs_watch:
                    watcher = threading.Thread(
                        target=_download_watcher,
                        args=(job_id, profile, stop_watch),
                        daemon=True,
                    )
                    watcher.start()

                _active_sink = sink
                try:
                    opts = InvisibleOptions(
                        pipeline=profile,
                        vendor=vendor,
                        cpu_offload=cpu_offload,
                        adaptive_polish=adaptive_polish,
                        humanize=humanize,
                        unsharp=unsharp,
                        tile=use_tile,
                    )
                    res = remove_all(
                        src,
                        dst,
                        backend=cast("Any", backend),
                        sensitivity=cast("Any", sensitivity),
                        invisible=opts,
                        force=force,
                        engine=_get_engine(profile, cpu_offload=cpu_offload, device=device),
                        progress=on_stage,
                    )
                finally:
                    _active_sink = None
                    stop_watch.set()
                    if watcher is not None:
                        watcher.join(timeout=1.5)

            summary["visible_marks"] = [m.label for m in res.visible_marks]
            summary["visible_status"] = res.visible_status
            summary["invisible_outcome"] = res.invisible
            summary["auto_tiled"] = auto_tiled
            if res.visible_marks:
                summary["backend"] = res.visible_marks[0].backend

        else:  # quick
            from remove_ai_watermarks import watermark_registry

            resolved_be = watermark_registry.resolve_backend(cast("Any", backend))
            if rec.cancelled.is_set():
                return
            _emit(job_id, f"Detecting & removing visible marks ({resolved_be})…", 28)
            _ensure_onnx_session(resolved_be)
            if rec.cancelled.is_set():
                return

            if resolved_be == "lama":
                with _lama_sem:
                    if rec.cancelled.is_set():
                        return
                    rep = remove_visible_detailed(
                        src,
                        dst,
                        sensitivity=cast("Any", sensitivity),
                        backend=cast("Any", resolved_be),
                        strip_metadata=False,
                    )
            else:
                rep = remove_visible_detailed(
                    src,
                    dst,
                    sensitivity=cast("Any", sensitivity),
                    backend=cast("Any", resolved_be),
                    strip_metadata=False,
                )

            if rec.cancelled.is_set():
                return
            _emit(job_id, "Verifying & stripping AI metadata…", 85)
            _fast_strip_output(dst)
            summary["visible_marks"] = rep.labels
            summary["visible_status"] = rep.status
            summary["backend"] = rep.marks[0].backend if rep.marks else resolved_be

        if rec.cancelled.is_set():
            _unlink_quietly(dst)
            return

        summary["elapsed_s"] = round(time.monotonic() - t0, 2)
        summary["size_bytes"] = dst.stat().st_size if dst.is_file() else 0
        _job_mgr.complete(job_id, dst, summary)
    except MetadataStripIncomplete as e:
        _unlink_quietly(dst)
        _job_mgr.fail(
            job_id,
            f"AI metadata survived the strip ({', '.join(sorted(e.surviving))}); no file produced.",
        )
    except Exception as e:
        log.exception("Image job %s failed", job_id)
        _unlink_quietly(dst)
        _job_mgr.fail(job_id, str(e) or e.__class__.__name__)
    finally:
        _unlink_quietly(src)
        _job_mgr.prune()


def _run_video_job(
    job_id: str,
    src: Path,
    dst: Path,
    mode: str,
    mark: str,
    backend: str,
    invisible_profile: str,
    temporal_consistency: bool,
) -> None:
    rec = _job_mgr.get(job_id)
    if rec is None:
        _unlink_quietly(src)
        return
    t0 = time.monotonic()
    try:
        if rec.cancelled.is_set():
            return
        from remove_ai_watermarks import video as vid_mod

        summary: dict[str, Any] = {
            "kind": "video",
            "mode": mode,
            "out_name": rec.out_name,
        }

        if mode == "metadata":
            _emit(job_id, "Stripping AI metadata from video container (lossless)…", 35)
            res = vid_mod.remove_video_metadata(src, dst)
            if res.remaining:
                raise MetadataStripIncomplete(set(res.remaining))
            summary["detected_metadata"] = sorted(res.detected.keys())
            summary["visible_marks"] = []
            summary["invisible_removed"] = False
        else:
            include_inv = mode == "deep"
            if include_inv:
                _emit(job_id, f"Scanning visible marks & regenerating video ({invisible_profile})…", 18)
            else:
                _emit(job_id, f"Scanning video frames for visible marks ({backend})…", 20)

            def _exec() -> Any:
                return vid_mod.remove_video_all(
                    src,
                    dst,
                    mark=mark or "auto",
                    backend=backend,
                    temporal_consistency=temporal_consistency,
                    include_invisible=include_inv,
                    invisible_profile=cast("Any", invisible_profile if include_inv else "synthid"),
                )

            if include_inv:
                with _engine_lock:
                    if rec.cancelled.is_set():
                        return
                    _clear_engines()
                    try:
                        res_all = _exec()
                    finally:
                        gc.collect()
                        _empty_accelerator_cache()
            else:
                if backend in ("migan", "lama"):
                    _ensure_onnx_session(backend)
                res_all = _exec()

            summary["visible_mark"] = res_all.visible_mark
            summary["visible_marks"] = (
                list(res_all.visible_marks)
                if res_all.visible_marks
                else ([res_all.visible_mark] if res_all.visible_mark else [])
            )
            summary["total_frames"] = res_all.total_frames
            summary["visible_removed_frames"] = res_all.visible_removed_frames
            summary["detected_metadata"] = sorted(res_all.detected_metadata.keys())
            summary["invisible_removed"] = bool(res_all.invisible_removed)
            summary["invisible_profile"] = res_all.invisible_profile

        if rec.cancelled.is_set():
            _unlink_quietly(dst)
            return

        summary["elapsed_s"] = round(time.monotonic() - t0, 2)
        summary["size_bytes"] = dst.stat().st_size if dst.is_file() else 0
        _job_mgr.complete(job_id, dst, summary)
    except MetadataStripIncomplete as e:
        _unlink_quietly(dst)
        _job_mgr.fail(
            job_id,
            f"AI metadata survived video strip ({', '.join(sorted(e.surviving))}); no file produced.",
        )
    except Exception as e:
        log.exception("Video job %s failed", job_id)
        _unlink_quietly(dst)
        _job_mgr.fail(job_id, str(e) or e.__class__.__name__)
    finally:
        _unlink_quietly(src)
        _job_mgr.prune()


# --- Routes ------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(
        content=INDEX_HTML.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/health")
def health() -> dict[str, Any]:
    base = _static_health()
    settings = model_status.load_settings()
    return {
        **base,
        "default_profile": model_status.preferred_profile(),
        "default_backend": settings.get("default_backend", "auto"),
    }


@app.get("/model")
def model(profile: str | None = None) -> dict[str, Any]:
    chosen = profile if profile in model_status.PROFILE_MODELS else None
    snap = model_status.snapshot(chosen)
    with _loaded_lock:
        snap["loaded"] = sorted(_loaded_profiles)
    return snap


@app.post("/model/download")
def model_download(profile: str = Form(""), include_face: str = Form("true")) -> dict[str, Any]:
    if profile == "lightweight":
        chosen = "lightweight"
    elif profile in model_status.PROFILE_MODELS:
        chosen = profile
    else:
        chosen = model_status.preferred_profile()
    return model_status.start_download(chosen, _parse_bool(include_face, True))


@app.post("/model/pause")
def model_pause() -> dict[str, Any]:
    return model_status.pause_download()


@app.post("/model/folder")
def model_folder(path: str = Form(""), profile: str = Form("")) -> dict[str, Any]:
    result = model_status.set_model_dir(path)
    chosen = profile if profile in model_status.PROFILE_MODELS else None
    snap = model_status.snapshot(chosen)
    with _loaded_lock:
        snap["loaded"] = sorted(_loaded_profiles)
    return {**result, "state": snap}


@app.post("/model/recheck")
def model_recheck(profile: str = Form("")) -> dict[str, Any]:
    model_status.recheck()
    chosen = profile if profile in model_status.PROFILE_MODELS else None
    snap = model_status.snapshot(chosen)
    with _loaded_lock:
        snap["loaded"] = sorted(_loaded_profiles)
    return snap


@app.post("/model/delete")
def model_delete(
    repo_id: str = Form(...),
    store: str = Form(...),
    profile: str = Form(""),
) -> dict[str, Any]:
    if not _engine_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Cannot delete models while a GPU job is running.")
    try:
        _clear_engines()
        res = model_status.delete_model(repo_id, store)
    finally:
        _engine_lock.release()
    chosen = profile if profile in model_status.PROFILE_MODELS else None
    snap = model_status.snapshot(chosen)
    with _loaded_lock:
        snap["loaded"] = sorted(_loaded_profiles)
    return {**res, "state": snap}


@app.post("/settings")
def update_settings(
    default_profile: str = Form(""),
    default_backend: str = Form(""),
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if default_profile in model_status.PROFILE_MODELS:
        updates["default_profile"] = default_profile
    if default_backend in _VALID_BACKENDS:
        updates["default_backend"] = default_backend
    saved = model_status.save_settings(updates) if updates else model_status.load_settings()
    return {"ok": True, "settings": saved}


# --- Easy GitHub Updater API -------------------------------------------------

_update_lock = threading.Lock()
_update_state: dict[str, Any] = {
    "checked_at": None,
    "error": None,
    "snapshot": None,
}


_GIT_TRANSIENT_PATTERNS = (
    "could not resolve host",
    "failed to connect",
    "connection reset",
    "connection timed out",
    "operation timed out",
    "timed out",
    "ssl",
    "tls",
    "gnutls",
    "openssl",
    "unexpected disconnect",
    "early eof",
    "transfer closed",
    "recv failure",
    "rpc failed",
    "the remote end hung up",
    "unable to access",
    "502",
    "503",
    "504",
    "429",
    "temporary failure",
    "network is unreachable",
    "name or service not known",
    "low speed",
)

_GIT_NON_RETRYABLE_PATTERNS = (
    "authentication failed",
    "repository not found",
    "permission denied",
    "could not read username",
    "not a git repository",
)


def _is_transient_git_error(proc: subprocess.CompletedProcess[str] | None) -> bool:
    if proc is None:
        return True  # timeout
    err = ((proc.stderr or "") + "\n" + (proc.stdout or "")).lower()
    if any(p in err for p in _GIT_NON_RETRYABLE_PATTERNS):
        return False
    return any(p in err for p in _GIT_TRANSIENT_PATTERNS)


def _is_offline_git_error(msg: str | None) -> bool:
    low = (msg or "").lower()
    return any(
        k in low
        for k in (
            "could not resolve host",
            "failed to connect",
            "timed out",
            "unable to access",
            "network is unreachable",
            "name or service not known",
            "connection reset",
            "low speed",
        )
    )


def _run_git(*args: str, timeout: float = 5.0) -> subprocess.CompletedProcess[str] | None:
    git_exe = shutil.which("git")
    if not git_exe:
        return None
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GCM_INTERACTIVE", "never")
    try:
        return subprocess.run(  # noqa: S603
            [git_exe, "--no-optional-locks", *args],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _run_git_with_retry(
    *args: str,
    timeout: float = 30.0,
    retries: int = 3,
    base_delay: float = 1.5,
) -> tuple[subprocess.CompletedProcess[str] | None, int]:
    """Run a network git command with exponential backoff on transient failures."""
    max_attempts = max(1, int(retries))
    last_proc: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, max_attempts + 1):
        last_proc = _run_git(*args, timeout=timeout)
        if _git_ok(last_proc):
            return last_proc, attempt
        if attempt >= max_attempts or not _is_transient_git_error(last_proc):
            return last_proc, attempt
        time.sleep(base_delay * (2 ** (attempt - 1)))
    return last_proc, max_attempts


def _git_ok(proc: subprocess.CompletedProcess[str] | None) -> bool:
    return proc is not None and proc.returncode == 0


def _git_stdout(proc: subprocess.CompletedProcess[str] | None) -> str:
    return (proc.stdout or "").strip() if _git_ok(proc) and proc is not None else ""


def _git_stderr(proc: subprocess.CompletedProcess[str] | None) -> str:
    if proc is None:
        return "Git command timed out or git is unavailable."
    return (proc.stderr or proc.stdout or "").strip()


def _git_ref_exists(ref: str) -> bool:
    return _git_ok(_run_git("rev-parse", "--verify", "--quiet", ref, timeout=5.0))


def _git_rev_count(rev_range: str) -> int | None:
    out = _git_stdout(_run_git("rev-list", "--count", rev_range, timeout=5.0))
    if out.isdigit():
        return int(out)
    return None


def _resolve_upstream_ref(branch: str | None) -> str | None:
    candidates = ["upstream/main", "upstream/master"]
    if branch and f"upstream/{branch}" not in candidates:
        candidates.insert(0, f"upstream/{branch}")
    for ref in candidates:
        if _git_ref_exists(ref):
            return ref
    return None


def _collect_update_status(
    *,
    checked_at: str | None = None,
    error: str | None = None,
    attempts: int | None = None,
) -> dict[str, Any]:
    """Gather local git & remote tracking status without making network calls."""
    if not shutil.which("git") or not _git_ok(_run_git("rev-parse", "--is-inside-work-tree", timeout=5.0)):
        return {
            "git_available": False,
            "current_version": raiw.__version__,
            "branch": None,
            "commit": None,
            "commit_date": None,
            "dirty": False,
            "remotes": {"origin": None, "upstream": None},
            "checked_at": checked_at,
            "behind_origin": None,
            "behind_upstream": None,
            "latest_upstream_tag": None,
            "recent_commits": [],
            "offline": False,
            "attempts": attempts,
            "error": error or "Git is not installed or this directory is not a git repository.",
        }

    branch = _git_stdout(_run_git("rev-parse", "--abbrev-ref", "HEAD", timeout=5.0)) or None
    if branch == "HEAD":
        branch = "detached"
    commit = _git_stdout(_run_git("rev-parse", "--short", "HEAD", timeout=5.0)) or None
    commit_date = _git_stdout(_run_git("log", "-1", "--format=%cI", timeout=5.0)) or None
    dirty_out = _git_stdout(_run_git("status", "--porcelain", "--untracked-files=no", timeout=5.0))
    dirty = bool(dirty_out)

    origin_url = _git_stdout(_run_git("remote", "get-url", "origin", timeout=5.0)) or None
    upstream_url = _git_stdout(_run_git("remote", "get-url", "upstream", timeout=5.0)) or None

    behind_origin: int | None = None
    origin_ref = f"origin/{branch}" if origin_url and branch and branch != "detached" else None
    if origin_ref and _git_ref_exists(origin_ref):
        behind_origin = _git_rev_count(f"HEAD..{origin_ref}")

    behind_upstream: int | None = None
    upstream_ref = _resolve_upstream_ref(branch if branch != "detached" else None) if upstream_url else None
    if upstream_ref:
        behind_upstream = _git_rev_count(f"HEAD..{upstream_ref}")

    tags_out = _git_stdout(_run_git("tag", "--sort=-v:refname", timeout=5.0))
    latest_tag = next((line.strip() for line in tags_out.splitlines() if line.strip()), None)

    log_target = "HEAD"
    if origin_ref and isinstance(behind_origin, int) and behind_origin > 0:
        log_target = f"HEAD..{origin_ref}"
    elif upstream_ref and isinstance(behind_upstream, int) and behind_upstream > 0:
        log_target = f"HEAD..{upstream_ref}"

    commits_out = _git_stdout(_run_git("log", "--oneline", "-n", "8", log_target, timeout=5.0))
    recent_commits = [line.strip() for line in commits_out.splitlines() if line.strip()][:8]

    return {
        "git_available": True,
        "current_version": raiw.__version__,
        "branch": branch,
        "commit": commit,
        "commit_date": commit_date,
        "dirty": dirty,
        "remotes": {"origin": origin_url, "upstream": upstream_url},
        "checked_at": checked_at,
        "behind_origin": behind_origin,
        "behind_upstream": behind_upstream,
        "latest_upstream_tag": latest_tag,
        "recent_commits": recent_commits,
        "offline": _is_offline_git_error(error),
        "attempts": attempts,
        "error": error,
    }


def _torch_index_for_version(ver: str) -> str:
    m = re.search(r"\+(cu\d+|rocm[\d.]+|xpu|cpu)", ver or "")
    return f"https://download.pytorch.org/whl/{m.group(1)}" if m else ""


def _read_installed_torch_versions() -> tuple[str, str]:
    import importlib.metadata as _im

    torch_ver = ""
    vision_ver = ""
    with contextlib.suppress(_im.PackageNotFoundError):
        torch_ver = _im.version("torch")
    with contextlib.suppress(_im.PackageNotFoundError):
        vision_ver = _im.version("torchvision")
    return torch_ver, vision_ver


def _run_pip_install(args: list[str], *, timeout: float = 120.0, retries: int = 2) -> tuple[bool, str]:
    uv_exe = shutil.which("uv")
    cmd = (
        [uv_exe, "pip", "install", "--python", sys.executable, *args]
        if uv_exe
        else [sys.executable, "-m", "pip", "install", *args]
    )
    last_err = ""
    for attempt in range(1, max(1, retries) + 1):
        try:
            proc = subprocess.run(  # noqa: S603
                cmd,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            if proc.returncode == 0:
                return True, ""
            last_err = (proc.stderr or proc.stdout or f"Exit code {proc.returncode}").strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_err = str(exc)
        if attempt < retries:
            time.sleep(2.0 * attempt)
    return False, last_err


def _reinstall_editable_no_deps(*, sync_pyproject: bool = False) -> tuple[bool, str, bool]:
    """Refresh editable package metadata while protecting installed GPU PyTorch wheels."""
    saved_torch, saved_vision = _read_installed_torch_versions()
    torch_protected = bool(saved_torch)
    warnings: list[str] = []

    if sync_pyproject:
        torch_index = _torch_index_for_version(saved_torch)
        dep_args: list[str] = []
        if torch_index:
            dep_args.extend(["--extra-index-url", torch_index])
        dep_args.append(".[studio,visible,video,heif,detect,lama,migan,source-classify]")
        ok_deps, err_deps = _run_pip_install(dep_args, timeout=180.0, retries=2)
        if not ok_deps:
            warnings.append(f"dependency sync: {err_deps}")

        if saved_torch and torch_index:
            after_torch, _ = _read_installed_torch_versions()
            if after_torch and after_torch != saved_torch:
                base_torch = saved_torch.split("+")[0]
                restore_specs = [f"torch=={base_torch}"]
                if saved_vision:
                    restore_specs.append(f"torchvision=={saved_vision.split('+')[0]}")
                ok_r, err_r = _run_pip_install(
                    ["--index-url", torch_index, "--force-reinstall", "--no-deps", *restore_specs],
                    timeout=180.0,
                    retries=2,
                )
                if not ok_r:
                    warnings.append(f"torch restore: {err_r}")

    ok_ed, err_ed = _run_pip_install(["--no-deps", "-e", "."], timeout=90.0, retries=2)
    if not ok_ed:
        warnings.append(err_ed)
        return False, "; ".join(warnings), torch_protected
    return (not warnings), "; ".join(warnings), torch_protected


@app.get("/update/status")
def update_status() -> dict[str, Any]:
    """Return local git repository status and cached remote update check info."""
    with _update_lock:
        checked_at = _update_state["checked_at"]
        last_error = _update_state["error"]
    return _collect_update_status(checked_at=checked_at, error=last_error)


@app.post("/update/check")
def update_check() -> dict[str, Any]:
    """Fetch tags and refs from configured git remotes (origin & upstream) with retry on flaky networks."""
    with _update_lock:
        base = _collect_update_status()
        if not base["git_available"]:
            _update_state["snapshot"] = base
            return base

        errors: list[str] = []
        max_attempts_used = 1
        remotes = base["remotes"]
        for remote_name in ("origin", "upstream"):
            if remotes.get(remote_name):
                proc, attempts = _run_git_with_retry(
                    "-c",
                    "http.lowSpeedLimit=1000",
                    "-c",
                    "http.lowSpeedTime=20",
                    "fetch",
                    "--tags",
                    remote_name,
                    timeout=30.0,
                    retries=3,
                    base_delay=1.5,
                )
                max_attempts_used = max(max_attempts_used, attempts)
                if not _git_ok(proc):
                    errors.append(f"{remote_name}: {_git_stderr(proc)}")

        checked_at = datetime.now(UTC).isoformat()
        err_msg = "; ".join(errors) if errors else None
        snap = _collect_update_status(checked_at=checked_at, error=err_msg, attempts=max_attempts_used)
        _update_state["checked_at"] = checked_at
        _update_state["error"] = err_msg
        _update_state["snapshot"] = snap
        return snap


@app.post("/update/apply")
def update_apply(source: str = Form("auto")) -> dict[str, Any]:
    """Safely pull from origin or merge from upstream with network retries and GPU wheel protection."""
    src_norm = (source or "auto").strip().lower()
    if src_norm not in _VALID_UPDATE_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid update source: {source!r}. Use auto, origin, or upstream.",
        )

    if model_status.download_state().get("active"):
        raise HTTPException(status_code=409, detail="Cannot apply updates while a model download is running.")

    if not _engine_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Cannot apply updates while a GPU job is running.")

    try:
        with _update_lock:
            status = _collect_update_status()
            if not status["git_available"]:
                return {
                    "ok": False,
                    "updated": False,
                    "old_commit": None,
                    "new_commit": None,
                    "restart_required": False,
                    "attempts": 0,
                    "offline": False,
                    "message": status["error"] or "Git is unavailable.",
                }

            if status["dirty"]:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Working tree has uncommitted changes to tracked files. "
                        "Commit or stash them before applying an update."
                    ),
                )

            old_commit = status["commit"]
            branch = status["branch"]
            remotes = status["remotes"]
            has_origin = bool(remotes.get("origin"))
            has_upstream = bool(remotes.get("upstream"))

            if src_norm == "origin":
                target_source = "origin"
            elif src_norm == "upstream":
                target_source = "upstream"
            else:
                behind_origin = status.get("behind_origin")
                if has_origin and ((isinstance(behind_origin, int) and behind_origin > 0) or not has_upstream):
                    target_source = "origin"
                elif has_upstream:
                    target_source = "upstream"
                else:
                    return {
                        "ok": False,
                        "updated": False,
                        "old_commit": old_commit,
                        "new_commit": old_commit,
                        "restart_required": False,
                        "attempts": 0,
                        "offline": False,
                        "message": "No origin or upstream git remote is configured.",
                    }

            attempts_used = 1
            if target_source == "origin":
                if not has_origin:
                    return {
                        "ok": False,
                        "updated": False,
                        "old_commit": old_commit,
                        "new_commit": old_commit,
                        "restart_required": False,
                        "attempts": 0,
                        "offline": False,
                        "message": "Remote 'origin' is not configured.",
                    }
                if not branch or branch == "detached":
                    return {
                        "ok": False,
                        "updated": False,
                        "old_commit": old_commit,
                        "new_commit": old_commit,
                        "restart_required": False,
                        "attempts": 0,
                        "offline": False,
                        "message": "HEAD is detached; checkout a branch before pulling from origin.",
                    }
                fetch_proc, attempts_used = _run_git_with_retry(
                    "-c",
                    "http.lowSpeedLimit=1000",
                    "-c",
                    "http.lowSpeedTime=20",
                    "fetch",
                    "--tags",
                    "origin",
                    timeout=30.0,
                    retries=3,
                    base_delay=1.5,
                )
                if not _git_ok(fetch_proc):
                    err_txt = _git_stderr(fetch_proc)
                    return {
                        "ok": False,
                        "updated": False,
                        "old_commit": old_commit,
                        "new_commit": old_commit,
                        "restart_required": False,
                        "attempts": attempts_used,
                        "offline": _is_offline_git_error(err_txt),
                        "message": f"Failed to fetch origin after {attempts_used} attempt(s): {err_txt}",
                    }
                origin_ref = f"origin/{branch}"
                if not _git_ref_exists(origin_ref):
                    return {
                        "ok": False,
                        "updated": False,
                        "old_commit": old_commit,
                        "new_commit": old_commit,
                        "restart_required": False,
                        "attempts": attempts_used,
                        "offline": False,
                        "message": f"Remote branch '{origin_ref}' not found.",
                    }
                # Local ff-only merge using already-fetched ref (no second network round-trip)
                pull_proc = _run_git("merge", "--ff-only", origin_ref, timeout=30.0)
                if not _git_ok(pull_proc):
                    return {
                        "ok": False,
                        "updated": False,
                        "old_commit": old_commit,
                        "new_commit": old_commit,
                        "restart_required": False,
                        "attempts": attempts_used,
                        "offline": False,
                        "message": (
                            f"Fast-forward pull from {origin_ref} failed: {_git_stderr(pull_proc)}. "
                            "Resolve divergence manually via git."
                        ),
                    }
            else:
                if not has_upstream:
                    return {
                        "ok": False,
                        "updated": False,
                        "old_commit": old_commit,
                        "new_commit": old_commit,
                        "restart_required": False,
                        "attempts": 0,
                        "offline": False,
                        "message": "Remote 'upstream' is not configured.",
                    }
                fetch_proc, attempts_used = _run_git_with_retry(
                    "-c",
                    "http.lowSpeedLimit=1000",
                    "-c",
                    "http.lowSpeedTime=20",
                    "fetch",
                    "--tags",
                    "upstream",
                    timeout=30.0,
                    retries=3,
                    base_delay=1.5,
                )
                if not _git_ok(fetch_proc):
                    err_txt = _git_stderr(fetch_proc)
                    return {
                        "ok": False,
                        "updated": False,
                        "old_commit": old_commit,
                        "new_commit": old_commit,
                        "restart_required": False,
                        "attempts": attempts_used,
                        "offline": _is_offline_git_error(err_txt),
                        "message": f"Failed to fetch upstream after {attempts_used} attempt(s): {err_txt}",
                    }
                upstream_ref = _resolve_upstream_ref(branch if branch != "detached" else None) or "upstream/main"
                ff_proc = _run_git("merge", "--ff-only", upstream_ref, timeout=30.0)
                if not _git_ok(ff_proc):
                    merge_proc = _run_git("merge", "--no-edit", upstream_ref, timeout=30.0)
                    if not _git_ok(merge_proc):
                        _run_git("merge", "--abort", timeout=10.0)
                        return {
                            "ok": False,
                            "updated": False,
                            "old_commit": old_commit,
                            "new_commit": old_commit,
                            "restart_required": False,
                            "attempts": attempts_used,
                            "offline": False,
                            "message": (
                                f"Merge conflict while syncing {upstream_ref}. "
                                "The merge was cleanly aborted; please resolve conflicts manually via git."
                            ),
                        }

            new_commit = _git_stdout(_run_git("rev-parse", "--short", "HEAD", timeout=5.0)) or old_commit
            updated = new_commit != old_commit

            if updated:
                changed_files = _git_stdout(
                    _run_git("diff", "--name-only", str(old_commit), str(new_commit), timeout=10.0)
                ).splitlines()
                pyproject_changed = "pyproject.toml" in [f.strip() for f in changed_files]
                reinstall_ok, reinstall_err, torch_protected = _reinstall_editable_no_deps(
                    sync_pyproject=pyproject_changed
                )
                _static_health.cache_clear()
                model_status.invalidate_snapshot_cache()
                checked_at = datetime.now(UTC).isoformat()
                _update_state["checked_at"] = checked_at
                _update_state["error"] = None
                _update_state["snapshot"] = _collect_update_status(checked_at=checked_at, attempts=attempts_used)
                if not reinstall_ok:
                    return {
                        "ok": True,
                        "updated": True,
                        "old_commit": old_commit,
                        "new_commit": new_commit,
                        "restart_required": True,
                        "attempts": attempts_used,
                        "deps_synced": pyproject_changed,
                        "torch_protected": torch_protected,
                        "offline": False,
                        "message": (
                            f"Updated {old_commit} -> {new_commit}, but package refresh warned: "
                            f"{reinstall_err}. Restart Studio to load the new code."
                        ),
                    }
                return {
                    "ok": True,
                    "updated": True,
                    "old_commit": old_commit,
                    "new_commit": new_commit,
                    "restart_required": True,
                    "attempts": attempts_used,
                    "deps_synced": pyproject_changed,
                    "torch_protected": torch_protected,
                    "offline": False,
                    "message": f"Updated {old_commit} -> {new_commit}. Restart Studio to load the new code.",
                }

            checked_at = datetime.now(UTC).isoformat()
            _update_state["checked_at"] = checked_at
            _update_state["error"] = None
            _update_state["snapshot"] = _collect_update_status(checked_at=checked_at, attempts=attempts_used)
            return {
                "ok": True,
                "updated": False,
                "old_commit": old_commit,
                "new_commit": new_commit,
                "restart_required": False,
                "attempts": attempts_used,
                "deps_synced": False,
                "torch_protected": True,
                "offline": False,
                "message": "Already up to date.",
            }
    finally:
        _engine_lock.release()


@app.post("/decode-preview")
def decode_preview(
    file: UploadFile,
    max_side: int = Form(1600),
) -> Response:
    """Decode browser-unsupported image formats (HEIC/HEIF/TIFF/AVIF) into a fast preview PNG/JPEG."""
    import cv2
    import numpy as np

    from remove_ai_watermarks import image_io

    max_px = max(64, min(2048, int(max_side)))
    name = _safe_basename(file.filename, "upload.png")
    with tempfile.TemporaryDirectory(prefix="raiw_prev_") as td:
        tmp_in = Path(td) / "raw"
        _size, head = _stream_upload(file, tmp_in, max_bytes=_MAX_IMAGE_BYTES)
        ext = _resolve_image_ext(name, head)
        src = Path(td) / f"in{ext}"
        os.replace(tmp_in, src)

        fmt, orient = _read_format_and_exif_orientation(src)
        bgr, alpha = image_io.read_bgr_and_alpha(src)
        if bgr is None:
            raise HTTPException(status_code=400, detail="Could not decode image.")

        if fmt not in _AUTO_ORIENTED_FORMATS and orient in (2, 3, 4, 5, 6, 7, 8):
            bgr = _apply_exif_orientation(bgr, orient)
            if alpha is not None:
                alpha = _apply_exif_orientation(alpha, orient)

        orig_h, orig_w = bgr.shape[:2]
        # Convert 16-bit to 8-bit for browser preview
        if bgr.dtype != np.uint8:
            scale = 255.0 / float(np.iinfo(bgr.dtype).max)
            bgr = cv2.convertScaleAbs(bgr, alpha=scale)
            if alpha is not None and alpha.dtype != np.uint8:
                alpha = cv2.convertScaleAbs(alpha, alpha=255.0 / float(np.iinfo(alpha.dtype).max))

        if max(orig_w, orig_h) > max_px:
            ratio = max_px / float(max(orig_w, orig_h))
            nw = max(1, round(orig_w * ratio))
            nh = max(1, round(orig_h * ratio))
            bgr = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
            if alpha is not None:
                alpha = cv2.resize(alpha, (nw, nh), interpolation=cv2.INTER_AREA)

        if alpha is not None:
            ok, buf = cv2.imencode(".png", np.dstack([bgr, alpha]))
            mime = "image/png"
        else:
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
            mime = "image/jpeg"

        if not ok:
            raise HTTPException(status_code=500, detail="Failed to encode preview image.")

        return Response(
            content=buf.tobytes(),
            media_type=mime,
            headers={
                "Cache-Control": "no-store",
                "X-Image-Width": str(orig_w),
                "X-Image-Height": str(orig_h),
            },
        )


@app.post("/inspect")
def inspect_media(
    file: UploadFile,
    run_classifier: str = Form("true"),
) -> dict[str, Any]:
    """Single-decode parallel inspection of provenance, visible marks, and Source Classify v8."""
    name = _safe_basename(file.filename, "upload.png")
    ext_hint = Path(name).suffix.lower()
    max_bytes = _MAX_VIDEO_BYTES if ext_hint in _VIDEO_MIME else _MAX_IMAGE_BYTES

    with tempfile.TemporaryDirectory(prefix="raiw_inspect_") as td:
        tmp_in = Path(td) / "raw"
        size_bytes, head = _stream_upload(file, tmp_in, max_bytes=max_bytes)

        vid_ext = _resolve_video_ext(name, head)
        is_video = vid_ext is not None and ext_hint not in _IMAGE_MIME
        final_ext = vid_ext if is_video and vid_ext else _resolve_image_ext(name, head)
        src = Path(td) / f"in{final_ext}"
        os.replace(tmp_in, src)

        if is_video:
            from remove_ai_watermarks import video as vid_mod

            vrep = vid_mod.identify_video(src, check_visible=True, check_audio=False)
            return {
                "kind": "video",
                "filename": name,
                "size_bytes": size_bytes,
                "is_ai_generated": vrep.is_ai_generated,
                "confidence": vrep.confidence,
                "platform": vrep.platform,
                "visible_mark": vrep.visible_mark,
                "visible_marks": list(vrep.visible_marks),
                "visible_detected_frames": vrep.visible_detected_frames,
                "total_frames": vrep.total_frames,
                "has_ai_metadata": vrep.has_ai_metadata,
                "metadata_markers": dict(vrep.metadata_markers),
                "invisible_watermark_hints": list(vrep.invisible_watermark_hints),
                "recommended_recipe": vrep.recommended_recipe,
                "caveats": list(vrep.caveats),
            }

        from remove_ai_watermarks import identify as id_mod
        from remove_ai_watermarks import source_classify
        from remove_ai_watermarks._internal.watermark_profiles import vendor_for_strength

        # Run Source Classify v8 concurrently on helper thread while provenance + visible marks run
        sc_future: Future[dict[str, Any]] | None = None
        if _parse_bool(run_classifier, True) and source_classify.is_available():

            def _run_sc() -> dict[str, Any]:
                try:
                    return source_classify.classify_source(src).to_dict()
                except Exception as exc:
                    return {"error": str(exc)}

            sc_future = _get_pool("inspect").submit(_run_sc)

        evidence = id_mod.extract_provenance_evidence(src)
        ai_meta = dict(evidence.ai_metadata)
        rep = id_mod.identify_from_evidence(evidence, image_path=src, check_visible=False, check_invisible=True)
        vendor_hint = vendor_for_strength(src)
        prov_dict = rep.to_dict()

        # Decode image ONCE (oriented upright for browser & Erase overlay) and detect marks ONCE
        visible_boxes: list[dict[str, Any]] = []
        dimensions: list[int] | None = None
        with contextlib.suppress(Exception):
            from remove_ai_watermarks import image_io, watermark_registry

            fmt, orient = _read_format_and_exif_orientation(src)
            bgr, _ = image_io.read_bgr_and_alpha(src)
            if bgr is not None:
                if fmt not in _AUTO_ORIENTED_FORMATS and orient in (2, 3, 4, 5, 6, 7, 8):
                    bgr = _apply_exif_orientation(bgr, orient)
                h_px, w_px = bgr.shape[:2]
                dimensions = [int(w_px), int(h_px)]
                dets = watermark_registry.detect_marks(bgr)
                non_google = rep.trusted_non_google_vendor
                for det in dets:
                    if not det.detected:
                        continue
                    # Mirror identify._collect_visible_signals sparkle veto on non-Google provenance
                    if det.key == "gemini_sparkle" and non_google:
                        continue
                    visible_boxes.append(
                        {
                            "key": det.key,
                            "label": det.label,
                            "location": det.location,
                            "confidence": round(float(det.confidence), 3),
                            "region": list(det.region) if det.region else None,
                        }
                    )
                    prov_dict["watermarks"].append(f"Visible {det.label} (confidence {float(det.confidence):.2f})")
                    prov_dict["signals"].append(
                        {
                            "name": f"visible_{det.key}",
                            "detail": f"NCC confidence {float(det.confidence):.2f}",
                            "confidence": "medium",
                        }
                    )
                if visible_boxes and prov_dict.get("is_ai_generated") is None:
                    prov_dict["is_ai_generated"] = True
                    prov_dict["confidence"] = "medium"

        sc_dict: dict[str, Any] | None = sc_future.result() if sc_future is not None else None

        # Compute smart cleaning recommendation gated on deep_available
        deep_available = bool(_static_health().get("deep_available", False))
        has_visible = bool(visible_boxes) or any("visible" in str(w).lower() for w in prov_dict.get("watermarks", []))
        has_invisible_hint = bool(rep.ai_from_metadata or vendor_hint) or bool(
            sc_dict and sc_dict.get("synthetic_detected")
        )
        if has_invisible_hint and deep_available:
            rec_mode = "deep"
            rec_pipeline = "sdxl-zimage" if vendor_hint == "google" else model_status.preferred_profile()
            sc_label = sc_dict.get("label") if sc_dict and sc_dict.get("label") != "unknown" else None
            src_name = vendor_hint or sc_label or "AI"
            rec_reason = (
                f"Detected {src_name} signals — Deep clean recommended to scrub invisible marks "
                "alongside visible/metadata."
            )
        elif has_invisible_hint and not deep_available:
            rec_mode = "quick"
            rec_pipeline = None
            sc_label = sc_dict.get("label") if sc_dict and sc_dict.get("label") != "unknown" else None
            src_name = vendor_hint or sc_label or "AI"
            rec_reason = (
                f"Detected {src_name} signals — Deep clean needs diffusion dependencies (`qwen-zimage`); "
                "Quick clean will remove visible marks and AI metadata."
            )
        elif has_visible or ai_meta:
            rec_mode = "quick"
            rec_pipeline = None
            rec_reason = (
                "Visible watermark or AI metadata found — Quick clean (LaMa/MI-GAN) handles this cleanly in ~1s."
            )
        else:
            rec_mode = "quick"
            rec_pipeline = None
            rec_reason = (
                "No local watermark or metadata signals detected "
                "(stripped images may still carry invisible marks)."
            )

        return {
            "kind": "image",
            "filename": name,
            "size_bytes": size_bytes,
            "dimensions": dimensions,
            "provenance": prov_dict,
            "ai_metadata": ai_meta,
            "vendor_hint": vendor_hint,
            "visible_boxes": visible_boxes,
            "source_classify": sc_dict,
            "recommendation": {
                "mode": rec_mode,
                "pipeline": rec_pipeline,
                "vendor": vendor_hint,
                "reason": rec_reason,
                "deep_available": deep_available,
            },
        }


def _parse_erase_boxes(raw_boxes: str, w: int, h: int) -> list[tuple[int, int, int, int]]:
    try:
        parsed = json.loads(raw_boxes or "[]")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid boxes JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="boxes must be a JSON array.")
    if len(parsed) > _MAX_BOXES:
        raise HTTPException(status_code=400, detail=f"Too many boxes (max {_MAX_BOXES}).")

    rects: list[tuple[int, int, int, int]] = []
    for item in parsed:
        if not isinstance(item, (list, tuple)) or len(item) != 4:
            raise HTTPException(status_code=400, detail="Each box must be [x, y, w, h].")
        vals: list[float] = []
        for coord in item:
            if isinstance(coord, bool) or not isinstance(coord, (int, float)) or not math.isfinite(coord):
                raise HTTPException(status_code=400, detail="Box coordinates must be finite numbers.")
            vals.append(float(coord))
        x0 = max(0, min(w, round(vals[0])))
        y0 = max(0, min(h, round(vals[1])))
        x1 = max(0, min(w, round(vals[0] + vals[2])))
        y1 = max(0, min(h, round(vals[1] + vals[3])))
        if x1 > x0 and y1 > y0:
            rects.append((x0, y0, x1 - x0, y1 - y0))
    return rects


def _rasterize_strokes(mask: Any, raw_strokes: str, w: int, h: int) -> None:
    import cv2
    import numpy as np

    try:
        parsed = json.loads(raw_strokes or "[]")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid strokes JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="strokes must be a JSON array.")
    if len(parsed) > _MAX_STROKES:
        raise HTTPException(status_code=400, detail=f"Too many brush strokes (max {_MAX_STROKES}).")

    total_pts = 0
    for stroke in parsed:
        if not isinstance(stroke, dict):
            raise HTTPException(status_code=400, detail="Each stroke must be an object with r and pts.")
        r_raw = stroke.get("r")
        pts_raw = stroke.get("pts")
        if isinstance(r_raw, bool) or not isinstance(r_raw, (int, float)) or not math.isfinite(r_raw):
            raise HTTPException(status_code=400, detail="Stroke radius must be a finite number.")
        if not isinstance(pts_raw, list) or not pts_raw:
            continue
        total_pts += len(pts_raw)
        if total_pts > _MAX_STROKE_POINTS:
            raise HTTPException(status_code=400, detail=f"Too many brush points (max {_MAX_STROKE_POINTS}).")

        radius = max(1, min(2000, round(float(r_raw))))
        coords: list[tuple[int, int]] = []
        for pt in pts_raw:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise HTTPException(status_code=400, detail="Stroke points must be [x, y].")
            px, py = pt[0], pt[1]
            if (
                isinstance(px, bool)
                or isinstance(py, bool)
                or not isinstance(px, (int, float))
                or not isinstance(py, (int, float))
                or not math.isfinite(px)
                or not math.isfinite(py)
            ):
                raise HTTPException(status_code=400, detail="Stroke point coordinates must be finite numbers.")
            coords.append((max(0, min(w - 1, round(float(px)))), max(0, min(h - 1, round(float(py))))))

        if len(coords) == 1:
            cv2.circle(mask, coords[0], radius, 255, thickness=-1, lineType=cv2.LINE_AA)
        else:
            pts_arr = np.asarray(coords, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(
                mask,
                [pts_arr],
                isClosed=False,
                color=255,
                thickness=max(1, radius * 2),
                lineType=cv2.LINE_AA,
            )
            cv2.circle(mask, coords[0], radius, 255, thickness=-1, lineType=cv2.LINE_AA)
            cv2.circle(mask, coords[-1], radius, 255, thickness=-1, lineType=cv2.LINE_AA)


@app.post("/erase")
def erase_regions_endpoint(
    file: UploadFile,
    boxes: str = Form("[]"),
    strokes: str = Form("[]"),
    mask_file: UploadFile | None = None,
    backend: str = Form("auto"),
    strip_metadata: str = Form("true"),
) -> dict[str, Any]:
    """Erase user-drawn boxes, JSON brush strokes, and/or PNG mask via big-LaMa, MI-GAN, or OpenCV."""
    import cv2
    import numpy as np

    from remove_ai_watermarks import image_io, region_eraser, watermark_registry

    t0 = time.monotonic()
    name = _safe_basename(file.filename, "image.png")
    if backend not in _VALID_BACKENDS:
        backend = "auto"

    rec = _job_mgr.create_job(out_name=f"{Path(name).stem}_erased.png", ext=".png", kind="erase")
    tmp_in = rec.job_dir / "raw"
    src: Path | None = None
    try:
        _size, head = _stream_upload(file, tmp_in, max_bytes=_MAX_IMAGE_BYTES)
        ext = _resolve_image_ext(name, head)
        out_name = f"{Path(name).stem}_erased{ext}"
        rec.ext = ext
        rec.out_name = out_name
        src = rec.job_dir / f"in{ext}"
        dst = rec.job_dir / f"out{ext}"
        os.replace(tmp_in, src)

        fmt, orient = _read_format_and_exif_orientation(src)
        bgr, alpha = image_io.read_bgr_and_alpha(src)
        if bgr is None:
            raise HTTPException(status_code=400, detail="Could not decode image.")

        # Align pixels upright when browser displays EXIF-rotated image (except formats already rotated on decode)
        orientation_applied = False
        if fmt not in _AUTO_ORIENTED_FORMATS and orient in (2, 3, 4, 5, 6, 7, 8):
            bgr = _apply_exif_orientation(bgr, orient)
            if alpha is not None:
                alpha = _apply_exif_orientation(alpha, orient)
            orientation_applied = True

        h, w = bgr.shape[:2]
        rect_list = _parse_erase_boxes(boxes, w, h)
        combined_mask = np.zeros((h, w), dtype=np.uint8)
        if rect_list:
            combined_mask = np.maximum(combined_mask, region_eraser.boxes_to_mask((h, w), rect_list, dilate=3))
        if strokes and strokes.strip() not in ("", "[]"):
            _rasterize_strokes(combined_mask, strokes, w, h)
        if mask_file is not None:
            mask_path = rec.job_dir / "mask.bin"
            try:
                _msize, _mhead = _stream_upload(mask_file, mask_path, max_bytes=_MAX_IMAGE_BYTES)
                arr = np.fromfile(str(mask_path), dtype=np.uint8)
                m_img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
                if m_img is not None:
                    if m_img.ndim == 3:
                        m_gray = m_img[:, :, 3] if m_img.shape[2] == 4 else cv2.cvtColor(m_img, cv2.COLOR_BGR2GRAY)
                    else:
                        m_gray = m_img
                    if m_gray.shape[:2] != (h, w):
                        m_gray = cv2.resize(m_gray, (w, h), interpolation=cv2.INTER_NEAREST)
                    combined_mask = np.maximum(combined_mask, np.where(m_gray > 20, 255, 0).astype(np.uint8))
            finally:
                _unlink_quietly(mask_path)

        if not combined_mask.any():
            raise HTTPException(status_code=400, detail="Draw at least one box or brush stroke to erase.")

        resolved_be = watermark_registry.resolve_backend(cast("Any", backend))
        _ensure_onnx_session(resolved_be)
        if resolved_be == "lama":
            with _lama_sem:
                erased = region_eraser.erase(bgr, mask=combined_mask, backend=resolved_be)
        else:
            erased = region_eraser.erase(bgr, mask=combined_mask, backend=resolved_be)

        if not image_io.write_bgr_with_alpha(
            dst,
            erased,
            alpha,
            display_tags_from=src,
            orientation_applied=orientation_applied,
        ):
            raise HTTPException(status_code=500, detail="Failed to write erased image.")

        stripped = False
        if _parse_bool(strip_metadata, True):
            try:
                _fast_strip_output(dst)
            except MetadataStripIncomplete as exc:
                _unlink_quietly(dst)
                raise HTTPException(
                    status_code=422,
                    detail=f"AI metadata survived strip: {', '.join(sorted(exc.surviving))}",
                ) from exc
            stripped = True

        out_size = dst.stat().st_size if dst.is_file() else 0
        elapsed = round(time.monotonic() - t0, 2)
        summary = {
            "mode": "erase",
            "out_name": out_name,
            "backend": resolved_be,
            "metadata_stripped": stripped,
            "elapsed_s": elapsed,
            "size_bytes": out_size,
        }
        _job_mgr.complete(rec.job_id, dst, summary)
        return {
            "job_id": rec.job_id,
            "out_name": out_name,
            "backend": resolved_be,
            "metadata_stripped": stripped,
            "elapsed_s": elapsed,
            "size_bytes": out_size,
            "preview_url": f"/preview/{rec.job_id}",
            "download_url": f"/result/{rec.job_id}",
        }
    except HTTPException:
        _job_mgr.fail(rec.job_id, "Erase request failed")
        raise
    except Exception as exc:
        log.exception("Erase job %s failed", rec.job_id)
        _job_mgr.fail(rec.job_id, str(exc) or exc.__class__.__name__)
        raise HTTPException(status_code=500, detail=str(exc) or exc.__class__.__name__) from exc
    finally:
        _unlink_quietly(tmp_in)
        if src is not None:
            _unlink_quietly(src)
        _job_mgr.prune()


@app.post("/clean")
def clean(
    file: UploadFile,
    mode: str = Form("quick"),
    pipeline: str = Form(""),
    backend: str = Form("auto"),
    sensitivity: str = Form("auto"),
    force: str = Form("true"),
    vendor: str = Form(""),
    cpu_offload: str = Form("false"),
    adaptive_polish: str = Form("auto"),
    humanize: float = Form(0.0),
    unsharp: float = Form(0.0),
    tile: str = Form("auto"),
    device: str = Form("auto"),
) -> dict[str, Any]:
    """Start an image cleaning job in a bounded pool and return its job_id."""
    mode_norm = (mode or "").strip().lower()
    if mode_norm not in _VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode!r}. Use quick, deep, or metadata.")

    hum = _parse_finite_float(humanize, "humanize", 0.0, 0.5)
    unsh = _parse_finite_float(unsharp, "unsharp", 0.0, 1.0)

    name = _safe_basename(file.filename, "image.png")
    profile = pipeline if pipeline in model_status.PROFILE_MODELS else model_status.preferred_profile()
    be = backend if backend in _VALID_BACKENDS else "auto"
    sens = sensitivity if sensitivity in _VALID_SENSITIVITIES else "auto"
    dev_norm = (device or "auto").strip().lower()
    dev = dev_norm if dev_norm in _VALID_DEVICES else "auto"
    resolved_device = None if dev == "auto" else dev
    vend = vendor.strip().lower() if vendor.strip().lower() in _VALID_VENDORS else None
    ap: bool | None = None
    ap_low = adaptive_polish.strip().lower()
    if ap_low in ("true", "1", "on"):
        ap = True
    elif ap_low in ("false", "0", "off"):
        ap = False

    rec = _job_mgr.create_job(out_name=f"{Path(name).stem}_clean.png", ext=".png", kind="image")
    tmp_in = rec.job_dir / "raw"
    try:
        _size, head = _stream_upload(file, tmp_in, max_bytes=_MAX_IMAGE_BYTES)
        ext = _resolve_image_ext(name, head)
        rec.ext = ext
        rec.out_name = f"{Path(name).stem}_clean{ext}"
        src = rec.job_dir / f"in{ext}"
        dst = rec.job_dir / f"out{ext}"
        os.replace(tmp_in, src)
    except Exception:
        _unlink_quietly(tmp_in)
        _job_mgr.fail(rec.job_id, "Upload failed")
        _job_mgr.prune()
        raise

    pool_kind = "meta" if mode_norm == "metadata" else ("deep" if mode_norm == "deep" else "quick")
    _get_pool(pool_kind).submit(
        _run_image_job,
        rec.job_id,
        src,
        dst,
        mode_norm,
        profile,
        be,
        sens,
        _parse_bool(force, True),
        vend,
        _parse_bool(cpu_offload, False),
        ap,
        hum,
        unsh,
        tile,
        resolved_device,
    )
    return {"job_id": rec.job_id, "pipeline": profile, "backend": be, "device": dev}


@app.post("/video/clean")
def video_clean(
    file: UploadFile,
    mode: str = Form("quick"),
    mark: str = Form("auto"),
    backend: str = Form("migan"),
    invisible_profile: str = Form("auto"),
    temporal_consistency: str = Form("true"),
) -> dict[str, Any]:
    """Start a video watermark cleaning job in the bounded video pool and return its job_id."""
    mode_norm = (mode or "").strip().lower()
    if mode_norm not in _VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid video mode: {mode!r}. Use quick, deep, or metadata.")

    name = _safe_basename(file.filename, "video.mp4")
    be = backend if backend in _VALID_BACKENDS else "migan"
    inv_prof = invisible_profile if invisible_profile in _VALID_VIDEO_INVISIBLE_PROFILES else "auto"

    rec = _job_mgr.create_job(out_name=f"{Path(name).stem}_clean.mp4", ext=".mp4", kind="video")
    tmp_in = rec.job_dir / "raw"
    try:
        _size, head = _stream_upload(file, tmp_in, max_bytes=_MAX_VIDEO_BYTES)
        ext = _resolve_video_ext(name, head)
        if ext is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported video format: {Path(name).suffix.lower() or 'unknown'}",
            )
        rec.ext = ext
        rec.out_name = f"{Path(name).stem}_clean{ext}"
        src = rec.job_dir / f"in{ext}"
        dst = rec.job_dir / f"out{ext}"
        os.replace(tmp_in, src)
    except Exception:
        _unlink_quietly(tmp_in)
        _job_mgr.fail(rec.job_id, "Upload failed")
        _job_mgr.prune()
        raise

    _get_pool("video").submit(
        _run_video_job,
        rec.job_id,
        src,
        dst,
        mode_norm,
        mark.strip() or "auto",
        be,
        inv_prof,
        _parse_bool(temporal_consistency, True),
    )
    return {"job_id": rec.job_id, "mode": mode_norm, "backend": be}


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str) -> dict[str, Any]:
    """Request cancellation of a queued or running job."""
    ok, status = _job_mgr.cancel(job_id)
    if status == "not_found":
        raise HTTPException(status_code=404, detail="Unknown job.")
    return {"ok": True, "job_id": job_id, "cancelled": ok, "status": status}


@app.get("/events/{job_id}")
async def events(job_id: str, request: Request) -> StreamingResponse:
    """Async replayable Server-Sent Events stream for a job (zero race on fast finish or reconnect)."""
    if _job_mgr.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Unknown job.")

    async def gen() -> AsyncIterator[str]:
        idx = 0
        loop = asyncio.get_running_loop()
        wake = asyncio.Event()
        if not _job_mgr.register_waiter(job_id, loop, wake):
            return
        try:
            while True:
                if await request.is_disconnected():
                    break
                wake.clear()
                batch, is_terminal = _job_mgr.read_events_from(job_id, idx)
                for ev in batch:
                    idx += 1
                    yield f"data: {json.dumps(ev)}\n\n"
                if is_terminal:
                    break
                try:
                    await asyncio.wait_for(wake.wait(), timeout=15.0)
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _job_mgr.unregister_waiter(job_id, loop, wake)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/preview/{job_id}")
def preview(job_id: str) -> FileResponse:
    """Return the cleaned file inline (chunked + HTTP Range support) for Before/After or video preview."""
    ready = _job_mgr.get_ready_result(job_id)
    if ready is None:
        raise HTTPException(status_code=404, detail="Preview not ready.")
    result_path, ext, out_name = ready
    return FileResponse(
        path=result_path,
        media_type=_ALL_MIME.get(ext, "application/octet-stream"),
        headers={
            "Content-Disposition": _content_disposition(out_name, inline=True),
            "Cache-Control": "no-store",
        },
    )


@app.get("/result/{job_id}")
def result(job_id: str) -> FileResponse:
    """Return the cleaned file as a download attachment (kept alive until TTL for re-download)."""
    ready = _job_mgr.get_ready_result(job_id)
    if ready is None:
        raise HTTPException(status_code=404, detail="Result not ready.")
    result_path, ext, out_name = ready
    return FileResponse(
        path=result_path,
        media_type=_ALL_MIME.get(ext, "application/octet-stream"),
        headers={
            "Content-Disposition": _content_disposition(out_name, inline=False),
            "Cache-Control": "no-store",
        },
    )


@app.post("/results/zip")
async def results_zip(request: Request) -> FileResponse:
    """Package multiple finished jobs into an instant zero-CPU ZIP_STORED archive."""
    job_ids: list[str] = []
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
        raw_ids = payload.get("job_ids") if isinstance(payload, dict) else None
        if isinstance(raw_ids, list):
            job_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
    else:
        form = await request.form()
        raw_list = form.getlist("job_ids")
        for item in raw_list:
            text = str(item).strip()
            if not text:
                continue
            if text.startswith("["):
                with contextlib.suppress(Exception):
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        job_ids.extend(str(x).strip() for x in parsed if str(x).strip())
                        continue
            job_ids.extend(part.strip() for part in text.split(",") if part.strip())

    ready_files: list[tuple[Path, str]] = []
    seen_ids: set[str] = set()
    for jid in job_ids:
        if jid in seen_ids:
            continue
        seen_ids.add(jid)
        info = _job_mgr.get_ready_result(jid)
        if info is not None:
            ready_files.append((info[0], info[2]))

    if not ready_files:
        raise HTTPException(status_code=400, detail="No ready jobs to package.")

    fd, tmp_name = tempfile.mkstemp(prefix="raiw_batch_", suffix=".zip")
    os.close(fd)
    zip_path = Path(tmp_name)
    try:
        used_names: dict[str, int] = {}
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
            for file_path, out_name in ready_files:
                base = _safe_basename(out_name, "cleaned_file")
                low = base.lower()
                count = used_names.get(low, 0) + 1
                used_names[low] = count
                if count > 1:
                    p = Path(base)
                    arcname = f"{p.stem} ({count}){p.suffix}"
                else:
                    arcname = base
                zf.write(file_path, arcname=arcname)
    except Exception:
        _unlink_quietly(zip_path)
        raise

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        background=BackgroundTask(_unlink_quietly, zip_path),
        headers={
            "Content-Disposition": _content_disposition("cleaned_batch.zip", inline=False),
            "Cache-Control": "no-store",
        },
    )


# --- App Lifecycle: Tab Heartbeat, Auto-Shutdown, Safe Quit & Restart --------

_RESTART_EXIT_CODE = 75
_CLIENT_STALE_SEC = 18.0
_DEFAULT_SHUTDOWN_GRACE_SEC = 12.0

_lifecycle_lock = threading.Lock()
_lifecycle_clients: dict[str, float] = {}  # client_id -> last_seen monotonic
_lifecycle_ever_connected = False
_lifecycle_zero_since: float | None = None
_lifecycle_shutting_down = False
_lifecycle_stop_ev = threading.Event()
_lifecycle_watchdog_started = False
_exit_process: Callable[[int], Any] = os._exit


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _auto_shutdown_grace_sec() -> float:
    raw = os.environ.get("RAIW_AUTO_SHUTDOWN_GRACE_SEC", "")
    try:
        val = float(raw)
        if 2.0 <= val <= 300.0:
            return val
    except ValueError:
        pass
    return _DEFAULT_SHUTDOWN_GRACE_SEC


def _auto_shutdown_enabled() -> bool:
    """Auto-shutdown activates when launched via Studio launcher unless disabled in settings."""
    if not _env_flag("RAIW_AUTO_SHUTDOWN", False):
        return False
    saved = model_status.load_settings().get("auto_shutdown_on_close")
    if isinstance(saved, bool):
        return saved
    return True


def _prune_stale_clients_unlocked(now: float) -> int:
    global _lifecycle_zero_since
    stale = [cid for cid, ts in _lifecycle_clients.items() if (now - ts) > _CLIENT_STALE_SEC]
    for cid in stale:
        _lifecycle_clients.pop(cid, None)
    count = len(_lifecycle_clients)
    if count > 0:
        _lifecycle_zero_since = None
    elif _lifecycle_ever_connected and _lifecycle_zero_since is None:
        _lifecycle_zero_since = now
    return count


def _active_work_summary() -> dict[str, Any]:
    """Inspect active cleaning jobs, downloads, GPU engine work, and GitHub updates."""
    active_jobs = _job_mgr.active_count()
    engine_busy = _engine_lock.locked()
    if engine_busy and active_jobs == 0:
        active_jobs = 1
    dl_state = model_status.download_state()
    downloading = bool(dl_state.get("active"))
    updating = _update_lock.locked()
    reasons: list[str] = []
    if active_jobs > 0:
        reasons.append(f"{active_jobs} active clean/video job(s)")
    if downloading:
        prof = dl_state.get("profile") or "model"
        reasons.append(f"model download in progress ({prof})")
    if updating:
        reasons.append("GitHub update in progress")
    return {
        "busy": bool(active_jobs > 0 or downloading or updating),
        "active_jobs": active_jobs,
        "downloading": downloading,
        "updating": updating,
        "reasons": reasons,
    }


def _release_gpu_and_cleanup() -> None:
    """Cancel active downloads/jobs, release cached diffusion engines & VRAM, and remove temp files."""
    with contextlib.suppress(Exception):
        model_status.pause_download()
    with contextlib.suppress(Exception):
        _job_mgr.cancel_all_active()
    with contextlib.suppress(Exception):
        _engines.clear()
    with contextlib.suppress(Exception):
        import gc

        gc.collect()
    with contextlib.suppress(Exception):
        from remove_ai_watermarks._internal import accelerator

        accelerator.empty_cache()
    with contextlib.suppress(Exception):
        _job_mgr.cleanup_all()


def _schedule_process_exit(exit_code: int, *, delay_sec: float = 0.35) -> None:
    global _lifecycle_shutting_down
    with _lifecycle_lock:
        if _lifecycle_shutting_down:
            return
        _lifecycle_shutting_down = True

    def _do_exit() -> None:
        time.sleep(max(0.0, delay_sec))
        _release_gpu_and_cleanup()
        _exit_process(exit_code)

    threading.Thread(target=_do_exit, name="raiw-lifecycle-exit", daemon=True).start()


def _lifecycle_watchdog_loop() -> None:
    global _lifecycle_zero_since
    while not _lifecycle_stop_ev.wait(timeout=2.0):
        if not _auto_shutdown_enabled():
            continue
        now = time.monotonic()
        grace = _auto_shutdown_grace_sec()
        with _lifecycle_lock:
            if _lifecycle_shutting_down:
                return
            active_tabs = _prune_stale_clients_unlocked(now)
            zero_since = _lifecycle_zero_since
            armed = _lifecycle_ever_connected

        if not armed or active_tabs > 0 or zero_since is None:
            continue
        if (now - zero_since) < grace:
            continue

        # Never auto-shutdown while a job, download, or update is still running!
        work = _active_work_summary()
        if work["busy"]:
            with _lifecycle_lock:
                _lifecycle_zero_since = now
            continue

        log.info("All browser tabs closed and Studio is idle; shutting down cleanly to free RAM/VRAM.")
        _schedule_process_exit(0, delay_sec=0.1)
        return


def _start_lifecycle_watchdog() -> None:
    global _lifecycle_watchdog_started
    with _lifecycle_lock:
        if _lifecycle_watchdog_started:
            return
        if not _env_flag("RAIW_AUTO_SHUTDOWN", False):
            return
        _lifecycle_stop_ev.clear()
        _lifecycle_watchdog_started = True
    threading.Thread(target=_lifecycle_watchdog_loop, name="raiw-auto-shutdown", daemon=True).start()


def _stop_lifecycle_watchdog() -> None:
    global _lifecycle_watchdog_started
    _lifecycle_stop_ev.set()
    with _lifecycle_lock:
        _lifecycle_watchdog_started = False


@app.get("/lifecycle/status")
def lifecycle_status() -> dict[str, Any]:
    """Return active tab count, active-work busy state, and auto-shutdown configuration."""
    now = time.monotonic()
    with _lifecycle_lock:
        active_tabs = _prune_stale_clients_unlocked(now)
        shutting_down = _lifecycle_shutting_down
    work = _active_work_summary()
    return {
        **work,
        "active_tabs": active_tabs,
        "auto_shutdown_available": _env_flag("RAIW_AUTO_SHUTDOWN", False),
        "auto_shutdown_enabled": _auto_shutdown_enabled(),
        "grace_seconds": _auto_shutdown_grace_sec(),
        "allow_restart": _env_flag("RAIW_ALLOW_RESTART", False),
        "shutting_down": shutting_down,
    }


@app.post("/lifecycle/ping")
def lifecycle_ping(client_id: str = Form(...)) -> dict[str, Any]:
    """Register or refresh an open browser tab heartbeat."""
    global _lifecycle_ever_connected, _lifecycle_zero_since
    cid = (client_id or "").strip()[:64]
    if not cid:
        raise HTTPException(status_code=400, detail="Missing client_id.")
    now = time.monotonic()
    with _lifecycle_lock:
        _lifecycle_clients[cid] = now
        _lifecycle_ever_connected = True
        _lifecycle_zero_since = None
        active_tabs = _prune_stale_clients_unlocked(now)
    return {
        "ok": True,
        "active_tabs": active_tabs,
        "auto_shutdown_enabled": _auto_shutdown_enabled(),
    }


@app.post("/lifecycle/bye")
def lifecycle_bye(client_id: str = Form(...)) -> dict[str, Any]:
    """Mark a browser tab as closed (invoked via keepalive fetch on pagehide)."""
    global _lifecycle_zero_since
    cid = (client_id or "").strip()[:64]
    now = time.monotonic()
    with _lifecycle_lock:
        if cid:
            _lifecycle_clients.pop(cid, None)
        active_tabs = _prune_stale_clients_unlocked(now)
        if active_tabs == 0 and _lifecycle_ever_connected:
            _lifecycle_zero_since = now
    return {"ok": True, "active_tabs": active_tabs}


@app.post("/lifecycle/config")
def lifecycle_config(auto_shutdown_on_close: bool = Form(...)) -> dict[str, Any]:
    """Toggle automatic server shutdown when the last browser tab is closed."""
    model_status.save_settings({"auto_shutdown_on_close": bool(auto_shutdown_on_close)})
    return {
        "ok": True,
        "auto_shutdown_available": _env_flag("RAIW_AUTO_SHUTDOWN", False),
        "auto_shutdown_enabled": _auto_shutdown_enabled(),
    }


@app.post("/lifecycle/shutdown")
def lifecycle_shutdown(force: bool = Form(False)) -> dict[str, Any]:
    """Shut down the Studio server and free VRAM. Returns 409 if work is in progress unless force=True."""
    work = _active_work_summary()
    if work["busy"] and not force:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                **work,
                "detail": (
                    "Active work is in progress ("
                    + ", ".join(work["reasons"])
                    + "). Confirm Force Quit to stop immediately and discard unfinished work."
                ),
            },
        )
    _schedule_process_exit(0, delay_sec=0.35)
    return {
        "ok": True,
        "shutting_down": True,
        "forced": bool(force and work["busy"]),
        "message": "Studio is shutting down cleanly and freeing RAM/VRAM.",
    }


@app.post("/lifecycle/restart")
def lifecycle_restart(force: bool = Form(False)) -> dict[str, Any]:
    """Restart Studio (when launched via Start Studio.cmd / run_webapp). Returns 409 if busy unless force=True."""
    if not _env_flag("RAIW_ALLOW_RESTART", False):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "restart_supported": False,
                "detail": "Auto-restart requires launching via Start Studio.cmd, run_webapp.ps1, or run_webapp.sh.",
            },
        )
    work = _active_work_summary()
    if work["busy"] and not force:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                **work,
                "detail": (
                    "Active work is in progress ("
                    + ", ".join(work["reasons"])
                    + "). Confirm Force Restart to stop immediately and discard unfinished work."
                ),
            },
        )
    _schedule_process_exit(_RESTART_EXIT_CODE, delay_sec=0.35)
    return {
        "ok": True,
        "restarting": True,
        "forced": bool(force and work["busy"]),
        "message": "Studio is restarting… this page will reconnect automatically.",
    }
