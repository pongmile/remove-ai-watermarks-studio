"""Comprehensive unit tests for universal GPU/NPU/CPU hardware acceleration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from remove_ai_watermarks._internal import accelerator as accel
from remove_ai_watermarks._internal.watermark_profiles import (
    AUTO_PROFILE,
    CHROMA_ZIMAGE_PROFILE,
    QWEN21_ZIMAGE_PROFILE,
    QWEN_ZIMAGE_PROFILE,
    SDXL_ZIMAGE_PROFILE,
)


def _make_fake_torch(
    *,
    cuda_available: bool = False,
    cuda_probe_ok: bool = True,
    cuda_name: str = "NVIDIA GeForce RTX 5070 Ti",
    cuda_vram_gib: float = 16.0,
    cuda_capability: tuple[int, int] = (12, 0),
    cuda_bf16: bool = True,
    hip_version: str | None = None,
    xpu_available: bool = False,
    xpu_probe_ok: bool = True,
    xpu_name: str = "Intel(R) Arc(TM) A770 Graphics",
    xpu_vram_gib: float = 16.0,
    xpu_bf16: bool = True,
    mps_available: bool = False,
    mps_max_mem_gib: float = 24.0,
    version: str = "2.11.0+cu128",
) -> SimpleNamespace:
    def _tensor(data: object, device: object = "cpu", dtype: object = None) -> MagicMock:
        dev_str = str(device)
        if dev_str.startswith("cuda") and not cuda_probe_ok:
            raise RuntimeError("CUDA kernel error")
        if dev_str.startswith("xpu") and not xpu_probe_ok:
            raise RuntimeError("XPU kernel error")
        m = MagicMock()
        m.__add__.return_value = m
        return m

    def _zeros(*_args: object, device: object = "cpu", dtype: object = None) -> MagicMock:
        if str(device).startswith("xpu") and dtype == "bfloat16" and not xpu_bf16:
            raise RuntimeError("XPU bf16 unsupported")
        m = MagicMock()
        m.__add__.return_value = m
        return m

    cuda_ns = SimpleNamespace(
        is_available=lambda: cuda_available,
        get_device_name=lambda _idx=0: cuda_name,
        get_device_properties=lambda _dev="cuda": SimpleNamespace(total_memory=int(cuda_vram_gib * (1024**3))),
        mem_get_info=lambda _dev="cuda": (int(cuda_vram_gib * (1024**3)), int(cuda_vram_gib * (1024**3))),
        get_device_capability=lambda _idx=0: cuda_capability,
        is_bf16_supported=lambda **_kwargs: cuda_bf16,
        empty_cache=MagicMock(),
    )
    xpu_ns = SimpleNamespace(
        is_available=lambda: xpu_available,
        get_device_name=lambda _idx=0: xpu_name,
        get_device_properties=lambda _dev="xpu": SimpleNamespace(total_memory=int(xpu_vram_gib * (1024**3))),
        is_bf16_supported=lambda: xpu_bf16,
        empty_cache=MagicMock(),
    )
    mps_ns = SimpleNamespace(
        recommended_max_memory=lambda: int(mps_max_mem_gib * (1024**3)),
        empty_cache=MagicMock(),
    )

    class _FakeGenerator:
        def __init__(self, device: object = "cpu") -> None:
            self.device = device
            self.seed: int | None = None

        def manual_seed(self, seed: int) -> _FakeGenerator:
            self.seed = seed
            return self

    return SimpleNamespace(
        __version__=version,
        version=SimpleNamespace(cuda="12.8" if not hip_version else None, hip=hip_version),
        cuda=cuda_ns,
        xpu=xpu_ns,
        mps=mps_ns,
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps_available)),
        tensor=_tensor,
        zeros=_zeros,
        Generator=_FakeGenerator,
        float32="float32",
        float16="float16",
        bfloat16="bfloat16",
    )


def _make_fake_ort(providers: list[str], *, fail_non_cpu: bool = False) -> SimpleNamespace:
    calls: list[dict[str, object]] = []

    class _FakeSession:
        def __init__(self, model: object, providers: list[str] | None = None, **kwargs: object) -> None:
            calls.append({"model": model, "providers": list(providers or []), **kwargs})
            if fail_non_cpu and providers != ["CPUExecutionProvider"]:
                raise RuntimeError("Hardware EP init failed")
            self._providers = list(providers or ["CPUExecutionProvider"])

        def get_providers(self) -> list[str]:
            return self._providers

    return SimpleNamespace(
        get_available_providers=lambda: list(providers),
        InferenceSession=_FakeSession,
        calls=calls,
    )


class TestHardwareDetection:
    """Verify detect_hardware_summary and resolve_dtype across all GPU/NPU/CPU families."""

    def test_nvidia_rtx_5070_ti_bf16(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(
            cuda_available=True,
            cuda_name="NVIDIA GeForce RTX 5070 Ti",
            cuda_vram_gib=16.0,
            cuda_capability=(12, 0),
            cuda_bf16=True,
        )
        fake_ort = _make_fake_ort(["CUDAExecutionProvider", "CPUExecutionProvider"])
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)
        monkeypatch.setattr(accel, "_detect_npu", lambda _p: False)

        summary = accel.detect_hardware_summary(torch_module=fake_torch, ort_module=fake_ort)
        assert summary["accelerator_kind"] == "cuda"
        assert summary["vendor"] == "nvidia"
        assert summary["device"] == "cuda"
        assert summary["device_name"] == "NVIDIA GeForce RTX 5070 Ti"
        assert summary["vram_gb"] == 16.0
        assert summary["bf16_supported"] is True
        assert summary["fp16_supported"] is True
        assert summary["active_onnx_provider"] == "CUDAExecutionProvider"
        assert summary["supported_profiles"][QWEN_ZIMAGE_PROFILE]["supported"] is True
        assert summary["supported_profiles"][QWEN_ZIMAGE_PROFILE]["recommended"] is True

        assert accel.resolve_dtype("cuda", QWEN_ZIMAGE_PROFILE, torch_module=fake_torch) == "bfloat16"
        assert accel.resolve_dtype("cuda", CHROMA_ZIMAGE_PROFILE, torch_module=fake_torch) == "bfloat16"
        assert accel.resolve_dtype("cuda", SDXL_ZIMAGE_PROFILE, torch_module=fake_torch) == "float16"

    def test_nvidia_gtx_1080_falls_back_to_fp16(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(
            cuda_available=True,
            cuda_name="NVIDIA GeForce GTX 1080",
            cuda_vram_gib=8.0,
            cuda_capability=(6, 1),
            cuda_bf16=False,
        )
        fake_ort = _make_fake_ort(["CUDAExecutionProvider", "CPUExecutionProvider"])
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)
        monkeypatch.setattr(accel, "_detect_npu", lambda _p: False)

        summary = accel.detect_hardware_summary(torch_module=fake_torch, ort_module=fake_ort)
        assert summary["accelerator_kind"] == "cuda"
        assert summary["vendor"] == "nvidia"
        assert summary["bf16_supported"] is False
        assert summary["fp16_supported"] is True
        assert summary["supported_profiles"][SDXL_ZIMAGE_PROFILE]["recommended"] is True

        assert accel.resolve_dtype("cuda", QWEN_ZIMAGE_PROFILE, torch_module=fake_torch) == "float16"
        assert accel.resolve_dtype("cuda", QWEN21_ZIMAGE_PROFILE, torch_module=fake_torch) == "float16"
        assert accel.resolve_dtype("cuda", CHROMA_ZIMAGE_PROFILE, torch_module=fake_torch) == "float16"
        assert accel.resolve_dtype("cuda", SDXL_ZIMAGE_PROFILE, torch_module=fake_torch) == "float16"

    def test_amd_rocm_hip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(
            cuda_available=True,
            cuda_name="AMD Radeon RX 7900 XTX",
            cuda_vram_gib=24.0,
            cuda_bf16=True,
            hip_version="6.2.41133",
            version="2.6.0+rocm6.2",
        )
        fake_ort = _make_fake_ort(["ROCMExecutionProvider", "CPUExecutionProvider"])
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)
        monkeypatch.setattr(accel, "_detect_npu", lambda _p: False)

        dev, kind = accel.resolve_torch_device("auto", torch_module=fake_torch)
        assert (dev, kind) == ("cuda", "rocm")
        dev_explicit, kind_explicit = accel.resolve_torch_device("rocm", torch_module=fake_torch)
        assert (dev_explicit, kind_explicit) == ("cuda", "rocm")

        summary = accel.detect_hardware_summary(torch_module=fake_torch, ort_module=fake_ort)
        assert summary["accelerator_kind"] == "rocm"
        assert summary["vendor"] == "amd"
        assert summary["device"] == "cuda"
        assert summary["bf16_supported"] is True
        assert summary["active_onnx_provider"] == "ROCMExecutionProvider"
        assert "rocm" in summary["diffusion_devices"]
        assert accel.resolve_dtype("rocm", QWEN_ZIMAGE_PROFILE, torch_module=fake_torch) == "bfloat16"

    def test_intel_arc_xpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(
            cuda_available=False,
            xpu_available=True,
            xpu_name="Intel(R) Arc(TM) B580 Graphics",
            xpu_vram_gib=12.0,
            xpu_bf16=True,
            version="2.7.0+xpu",
        )
        fake_ort = _make_fake_ort(["OpenVINOExecutionProvider", "CPUExecutionProvider"])
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)
        monkeypatch.setattr(accel, "_detect_npu", lambda _p: False)

        dev, kind = accel.resolve_torch_device("auto", torch_module=fake_torch)
        assert (dev, kind) == ("xpu", "xpu")

        summary = accel.detect_hardware_summary(torch_module=fake_torch, ort_module=fake_ort)
        assert summary["accelerator_kind"] == "xpu"
        assert summary["vendor"] == "intel"
        assert summary["vram_gb"] == 12.0
        assert summary["bf16_supported"] is True
        assert summary["active_onnx_provider"] == "OpenVINOExecutionProvider"
        assert summary["supported_profiles"][QWEN_ZIMAGE_PROFILE]["supported"] is True
        assert accel.resolve_dtype("xpu", QWEN_ZIMAGE_PROFILE, torch_module=fake_torch) == "bfloat16"
        assert accel.resolve_dtype("xpu", SDXL_ZIMAGE_PROFILE, torch_module=fake_torch) == "float16"

    def test_apple_silicon_mps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(
            cuda_available=False,
            xpu_available=False,
            mps_available=True,
            mps_max_mem_gib=32.0,
            version="2.6.0",
        )
        fake_ort = _make_fake_ort(["CoreMLExecutionProvider", "CPUExecutionProvider"])
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)
        monkeypatch.setattr(accel, "_detect_npu", lambda _p: False)

        dev, kind = accel.resolve_torch_device("auto", torch_module=fake_torch)
        assert (dev, kind) == ("mps", "mps")

        summary = accel.detect_hardware_summary(torch_module=fake_torch, ort_module=fake_ort)
        assert summary["accelerator_kind"] == "mps"
        assert summary["vendor"] == "apple"
        assert summary["bf16_supported"] is False
        assert summary["fp16_supported"] is True
        assert summary["active_onnx_provider"] == "CoreMLExecutionProvider"
        assert summary["supported_profiles"][SDXL_ZIMAGE_PROFILE]["supported"] is True
        assert summary["supported_profiles"][SDXL_ZIMAGE_PROFILE]["recommended"] is True
        assert summary["supported_profiles"][QWEN_ZIMAGE_PROFILE]["supported"] is False

        assert accel.resolve_dtype("mps", CHROMA_ZIMAGE_PROFILE, torch_module=fake_torch) == "float16"
        gen = accel.make_generator("mps", "mps", 42, torch_module=fake_torch)
        assert gen.device == "cpu"
        assert gen.seed == 42

    def test_windows_directml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(cuda_available=False, xpu_available=False, mps_available=False)
        fake_dml_device = SimpleNamespace(__str__=lambda self: "privateuseone:0")
        fake_dml = SimpleNamespace(
            is_available=lambda: True,
            device=lambda: fake_dml_device,
            default_device=lambda: 0,
            device_name=lambda _idx=0: "AMD Radeon RX 7800 XT",
        )
        fake_ort = _make_fake_ort(["DmlExecutionProvider", "CPUExecutionProvider"])
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: fake_dml)
        monkeypatch.setattr(accel, "_detect_npu", lambda _p: False)

        dev, kind = accel.resolve_torch_device("auto", torch_module=fake_torch)
        assert dev is fake_dml_device
        assert kind == "dml"

        summary = accel.detect_hardware_summary(torch_module=fake_torch, ort_module=fake_ort)
        assert summary["accelerator_kind"] == "dml"
        assert summary["vendor"] == "amd"
        assert summary["device"] == "dml"
        assert summary["bf16_supported"] is False
        assert summary["fp16_supported"] is True
        assert summary["active_onnx_provider"] == "DmlExecutionProvider"
        assert summary["supported_profiles"][SDXL_ZIMAGE_PROFILE]["supported"] is True
        assert summary["supported_profiles"][QWEN_ZIMAGE_PROFILE]["supported"] is False

        assert accel.resolve_dtype("dml", CHROMA_ZIMAGE_PROFILE, torch_module=fake_torch) == "float16"
        gen = accel.make_generator(fake_dml_device, "dml", 7, torch_module=fake_torch)
        assert gen.device == "cpu"
        assert gen.seed == 7

    def test_npu_detection_qnn_and_openvino(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(cuda_available=False, xpu_available=False, mps_available=False)
        fake_ort_qnn = _make_fake_ort(["QNNExecutionProvider", "CPUExecutionProvider"])
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)

        summary = accel.detect_hardware_summary(torch_module=fake_torch, ort_module=fake_ort_qnn)
        assert summary["npu_detected"] is True
        assert summary["active_onnx_provider"] == "QNNExecutionProvider"

        # OpenVINO NPU detection via mocked openvino.Core()
        fake_ort_ov = _make_fake_ort(["OpenVINOExecutionProvider", "CPUExecutionProvider"])
        fake_ov = SimpleNamespace(Core=lambda: SimpleNamespace(available_devices=["CPU", "GPU", "NPU"]))
        real_import = accel.importlib.import_module
        monkeypatch.setattr(
            accel.importlib,
            "import_module",
            lambda name: fake_ov if name == "openvino" else real_import(name),
        )
        summary_ov = accel.detect_hardware_summary(torch_module=fake_torch, ort_module=fake_ort_ov)
        assert summary_ov["npu_detected"] is True
        assert summary_ov["active_onnx_provider"] == "OpenVINOExecutionProvider"

    def test_cpu_fallback_uses_float32(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(cuda_available=False, xpu_available=False, mps_available=False)
        fake_ort = _make_fake_ort(["CPUExecutionProvider"])
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)
        monkeypatch.setattr(accel, "_detect_npu", lambda _p: False)

        dev, kind = accel.resolve_torch_device("auto", torch_module=fake_torch)
        assert (dev, kind) == ("cpu", "cpu")

        summary = accel.detect_hardware_summary(torch_module=fake_torch, ort_module=fake_ort)
        assert summary["accelerator_kind"] == "cpu"
        assert summary["vendor"] == "cpu"
        assert summary["vram_gb"] is None
        assert summary["bf16_supported"] is False
        assert summary["fp16_supported"] is False
        assert summary["diffusion_devices"] == ["cpu"]

        for profile in (SDXL_ZIMAGE_PROFILE, CHROMA_ZIMAGE_PROFILE, QWEN_ZIMAGE_PROFILE, QWEN21_ZIMAGE_PROFILE):
            assert accel.resolve_dtype("cpu", profile, torch_module=fake_torch) == "float32"


class TestExplicitDeviceResolutionAndHelpers:
    def test_unavailable_explicit_devices_raise_clear_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(cuda_available=False, xpu_available=False, mps_available=False)
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)

        for requested in ("cuda", "rocm", "xpu", "mps", "dml", "bogus"):
            with pytest.raises(ValueError, match=r"not available|Unsupported device"):
                accel.resolve_torch_device(requested, torch_module=fake_torch)

    def test_broken_cuda_probe_falls_back_to_cpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_torch = _make_fake_torch(cuda_available=True, cuda_probe_ok=False)
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)
        assert accel.resolve_torch_device("auto", torch_module=fake_torch) == ("cpu", "cpu")

    def test_empty_device_cache_routes_by_kind(self) -> None:
        fake_torch = _make_fake_torch()
        accel.empty_device_cache("cuda", torch_module=fake_torch)
        assert fake_torch.cuda.empty_cache.call_count == 1
        accel.empty_device_cache("xpu", torch_module=fake_torch)
        assert fake_torch.xpu.empty_cache.call_count == 1
        accel.empty_device_cache("mps", torch_module=fake_torch)
        assert fake_torch.mps.empty_cache.call_count == 1
        accel.empty_device_cache("cpu", torch_module=fake_torch)


class TestOnnxProviderSelection:
    def test_priority_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(accel.ONNX_PROVIDER_ENV, raising=False)
        fake_ort = _make_fake_ort(
            ["CPUExecutionProvider", "OpenVINOExecutionProvider", "DmlExecutionProvider", "CUDAExecutionProvider"]
        )
        assert accel.select_onnx_providers(prefer_gpu=True, ort_module=fake_ort) == [
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "OpenVINOExecutionProvider",
            "CPUExecutionProvider",
        ]
        assert accel.select_onnx_providers(prefer_gpu=False, ort_module=fake_ort) == ["CPUExecutionProvider"]

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(accel.ONNX_PROVIDER_ENV, "OpenVINOExecutionProvider")
        fake_ort = _make_fake_ort(["CUDAExecutionProvider", "OpenVINOExecutionProvider", "CPUExecutionProvider"])
        assert accel.select_onnx_providers(prefer_gpu=True, ort_module=fake_ort) == [
            "OpenVINOExecutionProvider",
            "CPUExecutionProvider",
        ]

    def test_create_onnx_session_falls_back_to_cpu_on_provider_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(accel.ONNX_PROVIDER_ENV, raising=False)
        fake_ort = _make_fake_ort(["CUDAExecutionProvider", "CPUExecutionProvider"], fail_non_cpu=True)
        session = accel.create_onnx_session("model.onnx", prefer_gpu=True, ort_module=fake_ort)
        assert session.get_providers() == ["CPUExecutionProvider"]
        assert len(fake_ort.calls) == 2
        assert fake_ort.calls[0]["providers"] == ["CUDAExecutionProvider", "CPUExecutionProvider"]
        assert fake_ort.calls[1]["providers"] == ["CPUExecutionProvider"]


class TestIntegrationWithEraserAndRemover:
    def test_region_eraser_batching_providers(self) -> None:
        from remove_ai_watermarks.region_eraser import _session_prefers_batching

        for ep in (
            "CUDAExecutionProvider",
            "ROCMExecutionProvider",
            "DmlExecutionProvider",
            "OpenVINOExecutionProvider",
        ):
            assert _session_prefers_batching(SimpleNamespace(get_providers=lambda ep=ep: [ep])) is True
        assert _session_prefers_batching(SimpleNamespace(get_providers=lambda: ["CPUExecutionProvider"])) is False

    def test_watermark_remover_non_diffsynth_device_policy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from remove_ai_watermarks._internal import watermark_remover as wr

        fake_torch = _make_fake_torch(cuda_available=False, mps_available=True)
        monkeypatch.setattr(wr, "torch", fake_torch)
        monkeypatch.setattr(wr, "_HAS_TORCH", True)
        monkeypatch.setattr(wr, "is_watermark_removal_available", lambda: True)
        monkeypatch.setattr(accel, "_import_torch_directml", lambda: None)

        # sdxl-zimage and chroma-zimage construct cleanly on MPS
        sdxl = wr.WatermarkRemover(device="mps", pipeline=SDXL_ZIMAGE_PROFILE)
        assert sdxl.device == "mps"
        assert sdxl.device_kind == "mps"
        assert sdxl.torch_dtype == "float16"

        chroma = wr.WatermarkRemover(device="mps", pipeline=CHROMA_ZIMAGE_PROFILE)
        assert chroma.torch_dtype == "float16"

        # auto on MPS automatically routes to sdxl-zimage
        auto_rem = wr.WatermarkRemover(device="mps", pipeline=AUTO_PROFILE)
        assert auto_rem.model_profile == SDXL_ZIMAGE_PROFILE

        # explicit qwen-zimage on MPS raises clear helpful error recommending sdxl-zimage
        with pytest.raises(ValueError, match="sdxl-zimage"):
            wr.WatermarkRemover(device="mps", pipeline=QWEN_ZIMAGE_PROFILE)
