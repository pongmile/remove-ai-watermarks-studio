# Remove AI Watermarks Studio — Local Web App

A fast, **100% offline** local Web Studio wrapping [`remove-ai-watermarks`](https://github.com/wiltodelta/remove-ai-watermarks) with universal GPU/NPU/CPU acceleration and 1-click GitHub updates.
**Nothing is uploaded to the internet, and zero external CDN scripts, fonts, or stylesheets are loaded.**

---

## Launch Studio

- **Windows:** Double-click **`Start Studio.cmd`** (or your **Remove AI Watermarks Studio** Desktop shortcut), or run:
  ```powershell
  .\run_webapp.ps1 -Open
  ```
- **macOS / Linux:**
  ```bash
  ./run_webapp.sh --open
  ```

Then open **http://127.0.0.1:8000** (override port/host with `RAIW_PORT` / `RAIW_HOST`, or `-Port` / `--port` and `-Host` / `--host`).

---

## Features

1. **Image Clean**
   - **Quick Clean:** Auto-removes 15+ visible AI watermarks (Gemini sparkle, Doubao, Jimeng, Qwen, Kling, OpenArt, Samsung, Microsoft, LiblibAI, generic `AI生成`, etc.) via **big-LaMa**, **MI-GAN**, or **OpenCV**, plus fast-path lossless PNG metadata stripping (<50 ms).
   - **Deep Clean:** Visible + invisible (SynthID / InvisMark / Content Seal) diffusion regeneration with universal device selection (`Auto`, `CUDA / ROCm`, `Intel Arc XPU`, `DirectML`, `Apple MPS`, `CPU`) and smart auto-tiling for ≤18 GB VRAM GPUs (`sdxl-zimage`, `qwen21-zimage`, `qwen-zimage`, `chroma-zimage`, `auto`).
   - **Metadata Only:** Lossless chunk stripping of C2PA, EXIF, XMP, IPTC, TC260, and ComfyUI tags.
   - Global drag-and-drop, `Ctrl+V` clipboard paste, parallel batch queue, Stop/Cancel, `.zip` batch download, Copy to Clipboard, and Pro Before/After Compare modal (Split / Side-by-Side / Hold Space / Zoom & Pan).
2. **Manual Erase**
   - Interactive Box (`R`) and Brush (`B`) canvas with live brush cursor, zoom/pan (`Space` + drag), `Auto-Detect Marks`, EXIF-orientation safety, IME-safe keyboard shortcuts, and in-place Result Preview.
3. **Inspect & AI Detect**
   - Single-decode parallel provenance + visible mark SVG bounding-box overlay + **Source Classify v8** + 1-click **Clean Now**.
4. **Video Clean**
   - All **18 registered visible video marks** (Sora 2, Veo, Seedance, Kling, Hailuo, Doubao, Dola, Vidu, Wan, Jimeng, Dreamina, Qwen, Yuanbao, Baidu, RunningHub, Microsoft, Generic AI Label), lossless metadata stripping, opt-in GPU regeneration, and in-app video preview modal.
5. **Models, Hardware & GitHub Updates Drawer**
   - Top-layer slide-over drawer showing your detected GPU / NPU / ONNX accelerator, Fast Core Pack (~295 MB ONNX) and Deep Clean model management, inline 2-step delete confirmation, **Check Updates** & **Update from GitHub** (`origin` / `upstream`), and instant **EN / ไทย** + **Auto / Light / Dark** toggles.

---

## Architecture & Files

| File | Purpose |
| --- | --- |
| `webapp/server.py` | FastAPI backend with localhost CSRF/Host guard, universal `/health` hardware summary, `/update/status`, `/update/check`, `/update/apply`, disk-backed `JobManager`, async replayable SSE, fast-path PNG strip, auto-tiling, `/cancel/{id}`, `/results/zip`, `/decode-preview`. |
| `webapp/model_status.py` | Fast `os.scandir()` model inventory with hardlink deduplication, TTL snapshot cache, hardware-annotated profile metadata, and portable `./models` default. |
| `webapp/index.html` | Offline semantic HTML shell using native `<dialog>` modals, `popover` drawer & top-layer toasts, and inline SVGs. |
| `webapp/static/app.css` | Offline responsive stylesheet organized with `@layer`, `light-dark()`, `@container` queries, `:has()`, `interpolate-size`, and `rem` typography. |
| `webapp/static/app.js` | Offline vanilla JS client (EN/ไทย i18n, View Transitions, IME-safe shortcuts, parallel queue, Compare modal, Manual Erase canvas, Inspect SVG overlay, Video player, Models & GitHub Updates drawer). |
| `Start Studio.cmd` / `run_webapp.ps1` / `run_webapp.sh` | Portable launchers that invoke `.venv` Python directly (never `uv run`) so GPU PyTorch wheels are preserved. |
| `Update Studio.cmd` / `update.ps1` / `update.sh` | Safe GitHub & upstream (`wiltodelta/remove-ai-watermarks`) updaters that protect your installed GPU PyTorch wheel. |
