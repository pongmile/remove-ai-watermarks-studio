# Remove AI Watermarks Studio

> **A modern local Web Studio & Universal GPU/NPU fork of [wiltodelta/remove-ai-watermarks](https://github.com/wiltodelta/remove-ai-watermarks) by [Victor Kuznetsov](https://wiltodelta.com/) (Apache-2.0).**

Remove visible AI marks, invisible watermarks, and AI provenance metadata (C2PA, EXIF, XMP, IPTC, TC260, ComfyUI) from **images, video, audio, and text you generated yourself** — **100% locally and offline** on Windows, macOS, or Linux, with zero cloud uploads and universal GPU, NPU, and CPU acceleration.

| Before | After |
| --- | --- |
| ![Image with a visible Gemini watermark](demo_banana_before.png) | ![Image after visible watermark removal](demo_banana_after.png) |

> **Lawful Use & Scope:** This is a research and personal-workflow tool for AI provenance signals, intended **only for lawful use on content you own or generated yourself**. It is provided *as is*, without warranty or liability, and does not target stock agency previews or watermarks protecting third-party paid content. Some jurisdictions restrict removing AI labels or supplying tools that do. See [docs/legal-and-safety.md](docs/legal-and-safety.md).

---

## Why This Fork?

Everything from upstream `wiltodelta/remove-ai-watermarks` (CLI, Python API, MCP server, Agent Skill, detectors, and diffusion pipelines) stays 100% intact, plus:

- **Offline Local Web Studio (`webapp/`):** Built with modern web platform standards (native `<dialog>`, Popover API, CSS `@layer` / `light-dark()` / `@container` / `:has()`, View Transitions) — zero external CDNs, zero telemetry.
- **Universal GPU / NPU / CPU Acceleration:** Works out of the box on **NVIDIA RTX & GTX**, **AMD Radeon** (Linux ROCm & Windows DirectML), **Intel Arc & Core Ultra** (PyTorch XPU & OpenVINO), **Apple Silicon** (MPS & CoreML), **AI NPUs** (Intel AI Boost, AMD Ryzen AI, Qualcomm Hexagon), and **CPU-only** machines.
- **1-Click Cross-Platform Install & Safe GitHub Updates:** Auto-detects your hardware, pins safe GPU PyTorch wheels (including Blackwell `cu128` safety), and updates from GitHub or upstream `wiltodelta/remove-ai-watermarks` without ever clobbering your GPU stack.
- **Bilingual UI (English / ไทย):** Instant language toggle + Auto / Light / Dark themes + Pro Before/After Compare, Manual Box/Brush Erase, Inspect & Source Classify v8, and 18-mark Video Clean.
- **4×–6.5× Studio Speedups:** Fast-path lossless PNG metadata strip (<50 ms), single-decode parallel Inspect, smart auto-tiling for ≤18 GB VRAM GPUs, and hardlink-deduplicated model storage management.

---

## Quick Start (1 Command)

### Windows (PowerShell)

```powershell
git clone https://github.com/pongmile/remove-ai-watermarks-studio.git
cd remove-ai-watermarks-studio
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Then double-click **`Start Studio.cmd`** (or your **Remove AI Watermarks Studio** Desktop shortcut created by `install.ps1` / `make_shortcut.ps1`), or run:

```powershell
.\run_webapp.ps1 -Open
```

### macOS & Linux

```bash
git clone https://github.com/pongmile/remove-ai-watermarks-studio.git
cd remove-ai-watermarks-studio
chmod +x install.sh run_webapp.sh update.sh
./install.sh
./run_webapp.sh --open
```

Open **http://127.0.0.1:8000** in your browser.

> **Lightweight install (no large PyTorch diffusion stack):** Pass `-SkipDeepClean` (Windows) or `--skip-deep-clean` (macOS/Linux) if you only need **Quick Clean**, **Manual Erase**, **Metadata Strip**, **Inspect**, and **Visible Video Clean**.
>
> **Explicit hardware override:** Both installers support `-Backend` / `--backend` with `auto`, `nvidia`, `nvidia-blackwell`, `amd-rocm`, `amd-dml`, `intel-xpu`, `intel-npu`, `apple-mps`, or `cpu`.

---

## Universal Hardware Support Matrix

Quick Clean (LaMa / MI-GAN / OpenCV), Manual Erase, Metadata Strip, Inspect, and Visible Video Clean run fast on **every** device below. Deep Clean (invisible watermark diffusion regeneration) adapts automatically to your accelerator:

| Hardware | OS | PyTorch Backend | ONNX Backend | Quick Clean & Inspect | Deep Clean (Invisible) | Video Clean |
| --- | --- | --- | --- | --- | --- | --- |
| **NVIDIA RTX 50-series (Blackwell)** | Win / Linux | `torch==2.11.0+cu128` *(avoids cu130 Z-Image segfault)* | `CUDA` / `CPU` | Fast (≤1s) | Full BF16 (all profiles, auto-tiled) | Visible + Deep GPU |
| **NVIDIA RTX 40 / 30 / 20** | Win / Linux | CUDA (`cu128`) | `CUDA` / `CPU` | Fast (≤1s) | Full (BF16 on 30/40; FP16 on 20) | Visible + Deep GPU |
| **NVIDIA GTX 10 / 16** | Win / Linux | CUDA (`cu128`, FP16) | `CUDA` / `CPU` | Fast (≤1s) | `sdxl-zimage` recommended (FP16 + offload) | Visible + VAE |
| **AMD Radeon (RX 6000 / 7000 / 9000)** | Linux / WSL2 | ROCm (`rocm6.2+`) | `ROCm` / `CPU` | Fast (≤1s) | Full (BF16/FP16) | Visible + Deep GPU |
| **AMD Radeon** | Windows | DirectML (`torch-directml`) | `DirectML` | GPU-accelerated | `sdxl-zimage` (FP16) | Visible + VAE |
| **Intel Arc (A/B-series) & Core Ultra GPU** | Win / Linux | Intel XPU (`whl/xpu`) | `OpenVINO` | GPU/NPU-accelerated | `sdxl-zimage` (FP16/BF16) | Visible + VAE |
| **Apple Silicon (M1 / M2 / M3 / M4)** | macOS | MPS (Metal) | `CoreML` / `CPU` | Fast (≤1s) | `sdxl-zimage` (FP16); Qwen w/ 32 GB+ RAM | Visible + MPS VAE |
| **AI NPUs** *(Intel Core Ultra AI Boost, AMD Ryzen AI, Qualcomm Hexagon)* | Windows / Linux | CPU / iGPU | `OpenVINO` / `DirectML` / `QNN` | NPU-accelerated ONNX | Use GPU or `sdxl-zimage` | Visible fast |
| **CPU-only** | Win / macOS / Linux | CPU (`float32`) | `CPU` | Fast (1–3s) | Slow (not recommended; use Quick Clean) | Visible fast |

> **Tip:** Override the ONNX Execution Provider anytime via `RAIW_ONNX_PROVIDER` (e.g. `OpenVINOExecutionProvider`, `DmlExecutionProvider`, `CUDAExecutionProvider`, `QNNExecutionProvider`, `CPUExecutionProvider`), or switch the Deep Clean compute device directly in the Studio UI (**Deep Clean → Advanced → Compute Device**).

---

## Model Guide

All models download on demand into `./models` (configurable in `webapp/settings.json` or inside the **Models & Updates** drawer) and are never bundled in this repository.

### 1. Lightweight ONNX Core Pack (~295 MB total)
Powers **Quick Clean**, **Manual Erase**, **Inspect**, and **Visible Video Clean** on any CPU/GPU/NPU:
- **big-LaMa ONNX** (~200 MB, Apache-2.0) — High-quality learned inpainting for visible watermarks & manual erase.
- **MI-GAN ONNX** (~28 MB, MIT) — Ultra-lightweight (~0.2s/call) inpainting for memory-tight systems.
- **Source Classify v8** (~67 MB, Apache-2.0) — 10-provider AI source & model-version classifier.

### 2. Deep Clean Diffusion Profiles (Invisible Watermarks)

| Profile | Approx. Download | License | Best For |
| --- | --- | --- | --- |
| **`sdxl-zimage`** | ~10 GB | CreativeML Open RAIL++-M + Apache-2.0 | **Best all-around & universal GPU choice** — fast, works cleanly on GTX, AMD DirectML, Intel Arc, Apple Silicon, and 8–16 GB VRAM cards. |
| **`qwen21-zimage`** *(7B)* | ~41 GB | **Qwen Research License (Non-Commercial Only)** | Highest visual fidelity with bounded geometric alignment. For non-commercial research, evaluation, and personal use only. |
| **`qwen-zimage`** *(20B)* | ~57 GB | Apache-2.0 | Commercial-safe high-fidelity default on high-VRAM CUDA/ROCm GPUs. |
| **`chroma-zimage`** | ~25 GB | Apache-2.0 | Calibrated Apache-2.0 alternative (used for Microsoft in `auto`). |
| **`auto`** | Routes per provider | Commercial-safe | Picks `sdxl-zimage` (Google), `chroma-zimage` (Microsoft), or `qwen-zimage` (other). |

---

## Easy GitHub Updates

Your installed GPU PyTorch wheel (`+cu128`, `+xpu`, `+rocm`, `torch-directml`, etc.) is **automatically preserved** across every update method:

1. **In-App Updater:** Open the **Models & Updates** drawer in Studio → click **Check Updates** → **Update from GitHub**.
2. **1-Click Scripts:**
   - **Windows:** Double-click **`Update Studio.cmd`** (or run `.\update.ps1`).
   - **macOS / Linux:** Run `./update.sh`.
3. **Sync Directly from Upstream (`wiltodelta/remove-ai-watermarks`):**
   ```powershell
   .\update.ps1 -Upstream      # Windows
   ```
   ```bash
   ./update.sh --upstream      # macOS / Linux
   ```
4. **Publish Your Own Fork on GitHub:**
   ```bash
   git remote set-url origin https://github.com/pongmile/remove-ai-watermarks-studio.git
   git remote add upstream https://github.com/wiltodelta/remove-ai-watermarks.git
   git push -u origin main
   ```

---

## CLI & Python API Quick Reference

The full upstream CLI, Python API, MCP server, and Agent Skill are included and documented in [`docs/`](docs/index.md):

```bash
# Inspect provenance & visible marks
remove-ai-watermarks identify image.png

# Remove visible marks + AI metadata (Quick Clean)
remove-ai-watermarks visible image.png -o clean.png --backend lama

# Strip AI metadata losslessly (image or video)
remove-ai-watermarks metadata image.png --remove -o clean.png
remove-ai-watermarks video metadata input.mp4 --remove -o clean.mp4

# Clean a video (18 registered visible marks + metadata)
remove-ai-watermarks video all input.mp4 -o clean.mp4

# Invisible watermark regeneration (Deep Clean)
remove-ai-watermarks invisible image.png -o clean.png --profile sdxl-zimage --force

# Run the MCP server
remove-ai-watermarks mcp
```

```python
import remove_ai_watermarks as raiw

report = raiw.remove_all("watermarked.png", "clean.png")
video_report = raiw.remove_video_all("input.mp4", "clean.mp4")
source = raiw.classify_source("image.png")
```

- [Web Studio Guide](webapp/README.md) · [Documentation Index](docs/index.md) · [CLI Guide](docs/cli.md) · [Python API](docs/python-api.md) · [Supported Signals](docs/supported-signals.md) · [Known Limitations](docs/known-limitations.md) · [MCP Server](docs/mcp-server.md) · [Agent Skill](docs/agent-skill.md)

---

## Credits, Upstream Attribution & Licenses

This repository is licensed under the **[Apache License 2.0](LICENSE)** (see also **[NOTICE](NOTICE)**).

### Upstream Project
- **[Victor Kuznetsov](https://wiltodelta.com/) — [`wiltodelta/remove-ai-watermarks`](https://github.com/wiltodelta/remove-ai-watermarks)** *(Apache-2.0, Copyright 2025–2026 wiltodelta)* — Original library, provenance/visible/audio/video/text detectors, removal pipelines, benchmarks, CLI, Agent Skill, and MCP server. Hosted service at [raiw.cc](https://raiw.cc).

### Models (Downloaded On Demand)
- **Alibaba Qwen:** `Qwen-Image-2512` *(Apache-2.0)* · `Qwen-Image-2.1` *(Qwen Research License — non-commercial use only)*
- **Stability AI:** `SDXL 1.0` *(CreativeML Open RAIL++-M)*
- **ByteDance:** `SDXL-Lightning` *(CreativeML Open RAIL++-M)*
- **Tongyi-MAI:** `Z-Image-Turbo` *(Apache-2.0)*
- **Lodestones:** `Chroma1-HD` *(Apache-2.0)*
- **MadeByOllin:** `Texture-Fix VAE` & `SDXL fp16 VAE` *(MIT / Apache-2.0)*
- **Carve:** `LaMa-ONNX` *(Apache-2.0)*
- **Andranik Sargsyan:** `MI-GAN` *(MIT)*
- **Meta Platforms:** `Segment Anything (SAM)` *(Apache-2.0)*
- **OpenCV Zoo:** `YuNet` Face Detector *(MIT)*
- **Victor Kuznetsov (`wiltodelta`):** [`wiltodelta/raiw-source-classify`](https://huggingface.co/wiltodelta/raiw-source-classify) *(Apache-2.0)*

### Frameworks & Web Platform Guidance
- **PyTorch**, **HuggingFace Diffusers & Transformers**, **DiffSynth-Studio**, **ONNX Runtime**, **FastAPI & Uvicorn**, and **Google Chrome `modern-web-guidance`**.
