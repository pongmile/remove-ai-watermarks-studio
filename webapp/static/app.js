'use strict';

// --- Minimal DOM & Formatting Utilities --------------------------------------
const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const isImeEvent = (e) => Boolean(e && (e.isComposing || e.keyCode === 229));
const prefersReducedMotion = () =>
  Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
const supportsPopover = () => Object.hasOwn(HTMLElement.prototype, 'popover') && typeof HTMLElement.prototype.showPopover === 'function';

const fmtSize = (b) => {
  if (b == null || Number.isNaN(b)) return '—';
  if (b >= 1e9) return (b / 1e9).toFixed(2) + ' GB';
  if (b >= 1e6) return (b / 1e6).toFixed(1) + ' MB';
  if (b >= 1e3) return (b / 1e3).toFixed(0) + ' KB';
  return b + ' B';
};
const fmtDuration = (sec) => {
  if (!Number.isFinite(sec) || sec < 0) return '';
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r < 10 ? '0' : ''}${r}`;
};

const VIDEO_EXT_RE = /\.(mp4|mov|m4v|webm|mkv|avi|flv)$/i;
const IMAGE_EXT_RE = /\.(png|jpe?g|jpe|jfif|webp|bmp|tiff?|heic|heif|avif)$/i;
const isVideoFile = (f) => (f.type && f.type.startsWith('video/')) || VIDEO_EXT_RE.test(f.name || '');
const isImageFile = (f) => (f.type && f.type.startsWith('image/')) || IMAGE_EXT_RE.test(f.name || '');

// Persistent Top-Layer UI helper (uses atomic moveBefore when available)
function reparentPreservingTopLayer(targetParent, el) {
  if (!targetParent || !el || el.parentNode === targetParent) return;
  if ('moveBefore' in Element.prototype) {
    try {
      targetParent.moveBefore(el, null);
      return;
    } catch {}
  }
  const wasPopoverOpen = supportsPopover() && el.matches(':popover-open');
  targetParent.insertBefore(el, null);
  if (wasPopoverOpen && typeof el.showPopover === 'function') {
    try { el.showPopover(); } catch {}
  }
}

// --- Inline SVG Icon Helpers -------------------------------------------------
const ICO = {
  inspect: '<svg class="ico ico-sm" aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
  erase: '<svg class="ico ico-sm" aria-hidden="true" viewBox="0 0 24 24"><path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/><path d="M22 21H7"/><path d="m5 11 9 9"/></svg>',
  copy: '<svg class="ico ico-sm" aria-hidden="true" viewBox="0 0 24 24"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>',
  dl: '<svg class="ico ico-sm" aria-hidden="true" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>',
  rerun: '<svg class="ico ico-sm" aria-hidden="true" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>',
  compare: '<svg class="ico ico-sm" aria-hidden="true" viewBox="0 0 24 24"><path d="M18 8L22 12L18 16"/><path d="M6 8L2 12L6 16"/><line x1="12" x2="12" y1="3" y2="21"/></svg>',
  play: '<svg class="ico ico-sm" aria-hidden="true" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
  trash: '<svg class="ico ico-sm" aria-hidden="true" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>',
  film: '<svg class="ico" aria-hidden="true" viewBox="0 0 24 24"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="m10 8 6 4-6 4V8z"/></svg>',
  img: '<svg class="ico" aria-hidden="true" viewBox="0 0 24 24"><rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>',
};

// --- Bilingual EN / ไทย Dictionary -------------------------------------------
const I18N = {
  en: {
    appTitle: 'Remove AI Watermarks Studio',
    models: 'Models',
    modelsDownloading: 'Downloading…',
    tabImage: 'Image',
    tabErase: 'Manual Erase',
    tabInspect: 'Inspect',
    tabVideo: 'Video',
    modeQuick: 'Quick Clean',
    modeQuickDesc: 'Auto-erases 15+ visible AI marks and strips AI metadata.',
    badgeFast: '~1s · Neural',
    modeDeep: 'Deep Clean',
    modeDeepDesc: 'Removes visible + hidden SynthID / InvisMark watermarks via GPU diffusion.',
    modeMeta: 'Metadata Only',
    modeMetaDesc: 'Strips C2PA, EXIF, XMP, TC260 & ComfyUI tags without touching pixels.',
    badgeLossless: 'Instant · Lossless',
    diffModel: 'Diffusion Model',
    alwaysScrub: 'Always scrub hidden marks',
    advancedOptions: 'Advanced Options',
    computeDevice: 'Compute Device',
    devAuto: 'Auto (Best available)',
    devCuda: 'NVIDIA CUDA',
    devRocm: 'AMD ROCm',
    devXpu: 'Intel Arc (XPU)',
    devDml: 'DirectML (AMD / Intel)',
    devMps: 'Apple MPS',
    devCpu: 'CPU',
    manageModels: 'Manage Models',
    tileLabel: 'Tile',
    tileAuto: 'Auto (>1536px)',
    tileOn: 'Always On',
    tileOff: 'Off',
    sourceHint: 'Source Hint',
    vendorAuto: 'Auto-detect',
    polishLabel: 'Polish',
    profileDefault: 'Profile default',
    forceOn: 'Force On',
    forceOff: 'Force Off',
    grainLabel: 'Grain',
    sharpenLabel: 'Sharpen',
    cpuOffload: 'CPU Offload',
    dropHeroTitle: 'Drop anywhere, click, or Ctrl+V paste',
    dropHeroSub: 'PNG, JPEG, WebP, HEIC/AVIF, TIFF, BMP — 100% local, batch supported',
    autoCleanDrop: 'Auto-clean on drop',
    fillModel: 'Quality / Fill Model',
    beAuto: 'Auto (Best)',
    detection: 'Detection',
    sensAuto: 'Smart Auto',
    sensStrict: 'Strict (low false-positive)',
    cleanBtn: 'Clean',
    stopBtn: 'Stop',
    downloadZip: 'Download All (.zip)',
    clearBtn: 'Clear',
    autoDownload: 'Auto-download',
    toolBox: 'Box',
    toolBrush: 'Brush',
    brushSize: 'Size',
    autoDetectMarks: 'Auto-Detect Marks',
    undoBtn: 'Undo',
    clearMaskBtn: 'Clear Mask',
    modelShort: 'Model',
    stripMeta: 'Strip metadata',
    eraseRunBtn: 'Erase',
    eraseDropTitle: 'Drop an image, click, or Ctrl+V paste to erase manually',
    eraseDropSub: 'Draw boxes (R), paint with brush (B), resize ([ / ]), or click Auto-Detect Marks',
    viewEditMask: 'Edit Mask',
    viewResult: 'Result Preview',
    chooseAnother: 'Choose another',
    zoomFit: 'Fit',
    downloadBtn: 'Download',
    copyBtn: 'Copy',
    keepErasing: 'Keep Erasing on Result',
    inspectDropTitle: 'Drop an image or video, click, or Ctrl+V paste to inspect',
    inspectDropSub: 'Checks C2PA, EXIF, TC260, visible watermarks (with overlay) + Source Classify v8',
    vidQuick: 'Visible + Metadata',
    vidQuickDesc: 'Auto-removes Sora 2, Veo, Seedance, Kling, Hailuo, Doubao, Vidu, Wan & more.',
    vidMetaDesc: 'Strips TC260, C2PA & vendor metadata without re-encoding video or audio.',
    vidDeep: 'Deep Video Clean',
    vidDeepDesc: 'Visible + metadata + invisible pixel regeneration (SynthID / Seedance / Wan 2.1).',
    vidDropTitle: 'Drag & drop videos here or click to browse',
    vidDropSub: 'MP4, MOV, M4V, WebM, MKV, AVI, FLV — bundled FFmpeg ready',
    vidModeNoteText: '18 registered video marks + optical-flow temporal smoothing',
    vidMarkLabel: 'Visible Mark',
    vidInvLabel: 'Invisible Profile',
    temporalSmooth: 'Temporal smoothing',
    cleanVideosBtn: 'Clean Videos',
    footerForkOf: 'Fork of',
    modelsDrawerTitle: 'Models & Updates',
    recheckBtn: 'Re-check',
    hwTitle: 'Hardware & Acceleration',
    updatesTitle: 'GitHub Updates',
    updateSource: 'Source',
    updateSrcAuto: 'Auto',
    updateSrcOrigin: 'Origin (Fork)',
    updateSrcUpstream: 'Upstream (wiltodelta)',
    checkUpdatesBtn: 'Check Updates',
    applyUpdateBtn: 'Update from GitHub',
    checkingUpdates: 'Checking GitHub remotes…',
    updatingStudio: 'Updating from GitHub…',
    upToDate: 'Up to date',
    updatesAvailable: '{n} update(s) available',
    dirtyWorktree: 'Local changes detected',
    gitUnavailable: 'Git unavailable',
    restartRequired: 'Update applied! Restart the Studio server to load the latest code.',
    dismissToast: 'Dismiss',
    tier1Title: 'Fast Core Pack · ~295 MB (ONNX)',
    downloadCorePack: 'Download Core Pack',
    corePackReady: '✓ Core Pack Ready',
    tier2Title: 'Deep Clean GPU Models',
    downloadProfile: 'Download Profile',
    pauseBtn: 'Pause',
    setDefaultBtn: 'Set Default ★',
    includeFace: 'Include face-repair weights (Z-Image + SAM)',
    storageTitle: 'Storage Folders',
    saveBtn: 'Save',
    cmpSplit: 'Split',
    cmpSbs: 'Side-by-Side',
    cmpPeek: 'Hold Space',
    touchUpErase: 'Touch up in Erase',
    kbdTitle: 'Keyboard Shortcuts',
    kbdTabs: 'Switch tabs (Image / Erase / Inspect / Video)',
    kbdPaste: 'Paste image from clipboard',
    kbdBoxBrush: 'Manual Erase: Box / Brush tool',
    kbdBrushSize: 'Manual Erase: Decrease / Increase brush size',
    kbdUndo: 'Manual Erase: Undo stroke or box',
    kbdPan: 'Manual Erase: Pan zoomed canvas',
    kbdEraseRun: 'Manual Erase: Run erase',
    kbdComparePeek: 'Compare Modal: Hold to peek Before / Navigate',
    kbdClose: 'Close modal / drawer',
    kbdHelp: 'Toggle shortcuts overlay',
    globalDropTitle: 'Drop images or videos anywhere',
    globalDropSub: 'Videos automatically open in Video Clean · Images route to the active tab',
    ready: 'Ready',
    done: 'Done ✓',
    cancelled: 'Cancelled',
    uploading: 'Uploading…',
    compare: 'Compare',
    preview: 'Preview',
    cleanNow: 'Clean Now',
    confirmDel: 'Confirm',
    cancel: 'Cancel',
    copiedImg: 'Copied cleaned image to clipboard',
    copyFailed: 'Clipboard copy not supported here',
    pastedToast: 'Image pasted from clipboard',
    zipReady: 'Downloaded cleaned_batch.zip',
    batchTipZip: 'Batch finished — click Download All (.zip) to save all files',
    recleanIn: 'Re-clean in',
    techDetails: 'Technical Details (Metadata / Signals)',
    before: 'Before',
    after: 'Cleaned',
    holdSpaceHint: 'Hold Space to peek Before',
    autoDetectFound: 'Detected {n} watermark region(s) — adjust or click Erase',
    autoDetectNone: 'No known watermark boxes detected automatically',
  },
  th: {
    appTitle: 'ลบลายน้ำ AI Studio',
    models: 'โมเดล',
    modelsDownloading: 'กำลังดาวน์โหลด…',
    tabImage: 'รูปภาพ',
    tabErase: 'ลบด้วยมือ',
    tabInspect: 'ตรวจสอบ AI',
    tabVideo: 'วิดีโอ',
    modeQuick: 'ลบด่วน',
    modeQuickDesc: 'ลบลายน้ำ AI ที่มองเห็นอัตโนมัติกว่า 15 แบบ พร้อมล้างเมทาดาทา AI',
    badgeFast: '~1 วิ · AI ลบเนียน',
    modeDeep: 'ลบเชิงลึก',
    modeDeepDesc: 'ลบทั้งลายน้ำที่เห็น + ลายน้ำซ่อน (SynthID / InvisMark) ด้วย GPU',
    modeMeta: 'ล้างเมทาดาทา',
    modeMetaDesc: 'ลบข้อมูล C2PA, EXIF, XMP, TC260 และ ComfyUI ทันทีโดยไม่แตะพิกเซล',
    badgeLossless: 'ทันที · ไม่ลดคุณภาพ',
    diffModel: 'โมเดล Diffusion',
    alwaysScrub: 'ลบเชิงลึกเสมอแม้ไม่มีเมทาดาทา',
    advancedOptions: 'ตัวเลือกขั้นสูง',
    computeDevice: 'อุปกรณ์ประมวลผล',
    devAuto: 'อัตโนมัติ (ดีที่สุด)',
    devCuda: 'NVIDIA CUDA',
    devRocm: 'AMD ROCm',
    devXpu: 'Intel Arc (XPU)',
    devDml: 'DirectML (AMD / Intel)',
    devMps: 'Apple MPS',
    devCpu: 'CPU',
    manageModels: 'จัดการโมเดล',
    tileLabel: 'แบ่งไทล์',
    tileAuto: 'อัตโนมัติ (>1536px)',
    tileOn: 'เปิดเสมอ',
    tileOff: 'ปิด',
    sourceHint: 'แหล่งที่มา',
    vendorAuto: 'ตรวจจับอัตโนมัติ',
    polishLabel: 'ปรับคมชัด',
    profileDefault: 'ค่าเริ่มต้นโปรไฟล์',
    forceOn: 'บังคับเปิด',
    forceOff: 'บังคับปิด',
    grainLabel: 'เกรนภาพ',
    sharpenLabel: 'ความคมชัด',
    cpuOffload: 'ลด VRAM ด้วย CPU',
    dropHeroTitle: 'ลากไฟล์วางตรงไหนก็ได้ คลิกเลือก หรือกด Ctrl+V วางรูป',
    dropHeroSub: 'รองรับ PNG, JPEG, WebP, HEIC/AVIF, TIFF, BMP — ทำงานในเครื่อง 100%',
    autoCleanDrop: 'ลบอัตโนมัติทันทีเมื่อวางไฟล์',
    fillModel: 'โมเดลเติมภาพ',
    beAuto: 'อัตโนมัติ (ดีที่สุด)',
    detection: 'ความไวการตรวจจับ',
    sensAuto: 'อัตโนมัติอัจฉริยะ',
    sensStrict: 'เข้มงวด (กันพลาด)',
    cleanBtn: 'เริ่มลบ',
    stopBtn: 'หยุด',
    downloadZip: 'ดาวน์โหลดทั้งหมด (.zip)',
    clearBtn: 'ล้างรายการ',
    autoDownload: 'โหลดอัตโนมัติ',
    toolBox: 'กรอบสี่เหลี่ยม',
    toolBrush: 'แปรงระบาย',
    brushSize: 'ขนาด',
    autoDetectMarks: 'ตรวจหาลายน้ำอัตโนมัติ',
    undoBtn: 'ย้อนกลับ',
    clearMaskBtn: 'ล้างมาสก์',
    modelShort: 'โมเดล',
    stripMeta: 'ล้างเมทาดาทา',
    eraseRunBtn: 'ลบจุดที่เลือก',
    eraseDropTitle: 'วางรูป คลิกเลือก หรือกด Ctrl+V เพื่อลบลายน้ำด้วยมือ',
    eraseDropSub: 'วาดกรอบ (R) ใช้แปรง (B) ปรับขนาด ([ / ]) หรือกดตรวจหาลายน้ำอัตโนมัติ',
    viewEditMask: 'แก้ไขมาสก์',
    viewResult: 'ดูผลลัพธ์',
    chooseAnother: 'เลือกรูปอื่น',
    zoomFit: 'พอดีจอ',
    downloadBtn: 'ดาวน์โหลด',
    copyBtn: 'คัดลอกรูป',
    keepErasing: 'ลบต่อบนภาพผลลัพธ์',
    inspectDropTitle: 'วางรูปหรือวิดีโอ คลิก หรือกด Ctrl+V เพื่อตรวจสอบลายน้ำและ AI',
    inspectDropSub: 'ตรวจ C2PA, EXIF, TC260, ลายน้ำที่มองเห็น (พร้อมกรอบตำแหน่ง) + Source Classify v8',
    vidQuick: 'ลบลายน้ำ + เมทาดาทา',
    vidQuickDesc: 'ลบลายน้ำวิดีโออัตโนมัติ 18 ค่าย (Sora 2, Veo, Seedance, Kling, Hailuo, Vidu ฯลฯ)',
    vidMetaDesc: 'ลบ TC260, C2PA และเมทาดาทา AI ทันทีโดยไม่เข้ารหัสวิดีโอใหม่',
    vidDeep: 'ลบวิดีโอเชิงลึก',
    vidDeepDesc: 'ลบลายน้ำ + เมทาดาทา + ลบลายน้ำซ่อนในเฟรมด้วย GPU (SynthID / Seedance / Wan 2.1)',
    vidDropTitle: 'ลากวิดีโอมาวางที่นี่ หรือคลิกเพื่อเลือกไฟล์',
    vidDropSub: 'รองรับ MP4, MOV, M4V, WebM, MKV, AVI, FLV — พร้อม FFmpeg ในตัว',
    vidModeNoteText: 'รองรับลายน้ำวิดีโอ 18 ค่าย + เกลี่ยเฟรมต่อเนื่องด้วย Optical Flow',
    vidMarkLabel: 'ชนิดลายน้ำ',
    vidInvLabel: 'โปรไฟล์ลบซ่อน',
    temporalSmooth: 'เกลี่ยเฟรมต่อเนื่อง',
    cleanVideosBtn: 'เริ่มลบวิดีโอ',
    footerForkOf: 'พัฒนาต่อจาก',
    modelsDrawerTitle: 'โมเดลและอัปเดต',
    recheckBtn: 'ตรวจใหม่',
    hwTitle: 'ฮาร์ดแวร์และการเร่งความเร็ว',
    updatesTitle: 'อัปเดตจาก GitHub',
    updateSource: 'แหล่งอัปเดต',
    updateSrcAuto: 'อัตโนมัติ',
    updateSrcOrigin: 'Origin (Fork)',
    updateSrcUpstream: 'Upstream (wiltodelta)',
    checkUpdatesBtn: 'ตรวจหาอัปเดต',
    applyUpdateBtn: 'อัปเดตจาก GitHub',
    checkingUpdates: 'กำลังตรวจสอบจาก GitHub…',
    updatingStudio: 'กำลังอัปเดตจาก GitHub…',
    upToDate: 'เป็นเวอร์ชันล่าสุดแล้ว',
    updatesAvailable: 'มีอัปเดตใหม่ {n} รายการ',
    dirtyWorktree: 'พบไฟล์ที่ยังไม่ได้ commit',
    gitUnavailable: 'ไม่พบ Git',
    restartRequired: 'อัปเดตสำเร็จ! กรุณารีสตาร์ทเซิร์ฟเวอร์ Studio เพื่อใช้งานโค้ดใหม่',
    dismissToast: 'ปิดการแจ้งเตือน',
    tier1Title: 'ชุดโมเดลหลักความเร็วสูง · ~295 MB (ONNX)',
    downloadCorePack: 'ดาวน์โหลดชุดหลัก',
    corePackReady: '✓ ชุดหลักพร้อมใช้งาน',
    tier2Title: 'โมเดลลบเชิงลึก (GPU)',
    downloadProfile: 'ดาวน์โหลดโปรไฟล์',
    pauseBtn: 'หยุดชั่วคราว',
    setDefaultBtn: 'ตั้งเป็นค่าหลัก ★',
    includeFace: 'รวมโมเดลซ่อมใบหน้า (Z-Image + SAM)',
    storageTitle: 'โฟลเดอร์จัดเก็บโมเดล',
    saveBtn: 'บันทึก',
    cmpSplit: 'เลื่อนเทียบ',
    cmpSbs: 'เทียบคู่กัน',
    cmpPeek: 'กด Space ค้างดูต้นฉบับ',
    touchUpErase: 'เก็บงานต่อในลบด้วยมือ',
    kbdTitle: 'คีย์ลัดแป้นพิมพ์',
    kbdTabs: 'สลับแท็บ (รูปภาพ / ลบด้วยมือ / ตรวจสอบ / วิดีโอ)',
    kbdPaste: 'วางรูปจากคลิปบอร์ด',
    kbdBoxBrush: 'ลบด้วยมือ: เครื่องมือกรอบ / แปรง',
    kbdBrushSize: 'ลบด้วยมือ: ลด / เพิ่มขนาดแปรง',
    kbdUndo: 'ลบด้วยมือ: ย้อนกลับ',
    kbdPan: 'ลบด้วยมือ: เลื่อนภาพตอนซูม',
    kbdEraseRun: 'ลบด้วยมือ: เริ่มลบจุดที่เลือก',
    kbdComparePeek: 'หน้าต่างเปรียบเทียบ: กด Space ค้างดูต้นฉบับ / เปลี่ยนรูป',
    kbdClose: 'ปิดหน้าต่าง / แผงโมเดล',
    kbdHelp: 'เปิด/ปิดรายการคีย์ลัด',
    globalDropTitle: 'วางรูปภาพหรือวิดีโอตรงไหนก็ได้',
    globalDropSub: 'วิดีโอจะสลับไปแท็บวิดีโออัตโนมัติ · รูปภาพจะส่งเข้าแท็บที่เปิดอยู่',
    ready: 'พร้อม',
    done: 'เสร็จแล้ว ✓',
    cancelled: 'ยกเลิกแล้ว',
    uploading: 'กำลังอัปโหลด…',
    compare: 'เทียบก่อน/หลัง',
    preview: 'ดูวิดีโอ',
    cleanNow: 'ลบทันที',
    confirmDel: 'ยืนยันลบ',
    cancel: 'ยกเลิก',
    copiedImg: 'คัดลอกรูปที่ลบแล้วลงคลิปบอร์ด',
    copyFailed: 'เบราว์เซอร์ไม่รองรับการคัดลอกรูป',
    pastedToast: 'วางรูปจากคลิปบอร์ดแล้ว',
    zipReady: 'ดาวน์โหลด cleaned_batch.zip แล้ว',
    batchTipZip: 'ลบครบชุดแล้ว — กด ดาวน์โหลดทั้งหมด (.zip) เพื่อบันทึกทุกไฟล์',
    recleanIn: 'ลบซ้ำด้วยโหมด',
    techDetails: 'รายละเอียดเชิงเทคนิค (เมทาดาทา / สัญญาณ)',
    before: 'ก่อนลบ',
    after: 'หลังลบ',
    holdSpaceHint: 'กด Space ค้างเพื่อดูภาพต้นฉบับ',
    autoDetectFound: 'ตรวจพบลายน้ำ {n} จุด — ปรับแก้หรือกดลบได้ทันที',
    autoDetectNone: 'ไม่พบกรอบลายน้ำมาตรฐานอัตโนมัติ',
  },
};

let curLang = 'en';
try {
  const savedLang = localStorage.getItem('raiw_lang');
  if (savedLang === 'en' || savedLang === 'th') curLang = savedLang;
} catch {}

function t(key, vars) {
  let str = (I18N[curLang] && I18N[curLang][key]) || I18N.en[key] || key;
  if (vars) {
    Object.entries(vars).forEach(([k, v]) => {
      str = str.replace('{' + k + '}', String(v));
    });
  }
  return str;
}

function applyLanguage(lang) {
  curLang = lang === 'th' ? 'th' : 'en';
  document.documentElement.lang = curLang;
  try { localStorage.setItem('raiw_lang', curLang); } catch {}
  $('langBtn').textContent = curLang === 'th' ? 'ไทย / EN' : 'EN / ไทย';
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    const k = el.getAttribute('data-i18n');
    if (k && I18N[curLang][k]) el.textContent = I18N[curLang][k];
  });
  updateImgOptSummary();
  updateVidOptSummary();
  updateImageActionRow();
  if (modelSnap) renderModels(modelSnap);
  if (updateSnap) renderUpdateStatus(updateSnap);
}

$('langBtn').addEventListener('click', () => applyLanguage(curLang === 'en' ? 'th' : 'en'));

// --- Native Top-Layer Popover Toast System + ariaNotify / Live Region --------
function announceToAT(message, isAssertive = false) {
  if (typeof document.ariaNotify === 'function') {
    try {
      document.ariaNotify(message, { priority: isAssertive ? 'high' : 'normal' });
      return;
    } catch {}
  }
  const region = isAssertive ? $('srAlert') : $('srAnnouncer');
  if (!region) return;
  region.textContent = '';
  requestAnimationFrame(() => { region.textContent = message; });
}

function syncToastStackVisibility() {
  const stack = $('toastStack');
  if (!stack) return;
  const hasToasts = stack.children.length > 0;
  if (supportsPopover()) {
    try {
      if (hasToasts) {
        // Re-promote to top of top-layer so toasts stay above any open <dialog>
        if (stack.matches(':popover-open')) stack.hidePopover();
        stack.showPopover();
      } else if (stack.matches(':popover-open')) {
        stack.hidePopover();
      }
    } catch {}
  } else {
    stack.classList.toggle('popover-fallback-open', hasToasts);
  }
}

function showToast(message, kind = 'info', durationMs = 3600) {
  const stack = $('toastStack');
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.setAttribute('role', kind === 'err' ? 'alert' : 'status');
  el.innerHTML =
    `<span>${esc(message)}</span>` +
    `<button type="button" class="toast-close" aria-label="${esc(t('dismissToast'))}">✕</button>`;

  reparentPreservingTopLayer(document.body, stack);
  stack.appendChild(el);
  syncToastStackVisibility();
  announceToAT(message, kind === 'err');

  let timer = null;
  let paused = false;

  const removeToast = (moveFocus) => {
    clearTimeout(timer);
    if (!el.isConnected) return;
    const nextSibling = el.nextElementSibling || el.previousElementSibling;
    const hadFocus = el.contains(document.activeElement);
    el.classList.add('leaving');
    const finishRemove = () => {
      el.remove();
      syncToastStackVisibility();
      if (moveFocus && hadFocus && nextSibling) {
        nextSibling.querySelector('.toast-close')?.focus();
      }
    };
    if (prefersReducedMotion()) finishRemove();
    else setTimeout(finishRemove, 190);
  };

  const scheduleDismiss = () => {
    clearTimeout(timer);
    if (paused) return;
    timer = setTimeout(() => removeToast(false), durationMs);
  };

  el.querySelector('.toast-close').addEventListener('click', () => removeToast(true));
  el.addEventListener('pointerenter', () => { paused = true; clearTimeout(timer); });
  el.addEventListener('pointerleave', () => { paused = false; scheduleDismiss(); });
  el.addEventListener('focusin', () => { paused = true; clearTimeout(timer); });
  el.addEventListener('focusout', () => { paused = false; scheduleDismiss(); });
  scheduleDismiss();
}

// --- Accessible Form Validation Sync (:user-invalid <-> aria-invalid) --------
(function initAccessibleValidation() {
  const syncAria = (el) => {
    if (!el || !el.matches?.('input, select, textarea')) return;
    let invalid = false;
    try {
      invalid = el.matches(':user-invalid');
    } catch {
      invalid = el.classList.contains('user-invalid-fallback');
    }
    el.setAttribute('aria-invalid', invalid ? 'true' : 'false');
  };
  document.querySelectorAll('input, select, textarea').forEach((el) => {
    if (!el.hasAttribute('aria-invalid')) el.setAttribute('aria-invalid', 'false');
  });
  document.addEventListener('blur', (e) => syncAria(e.target), true);
  document.addEventListener('change', (e) => syncAria(e.target), true);
  document.addEventListener('input', (e) => {
    if (e.target && e.target.hasAttribute && e.target.hasAttribute('aria-invalid')) syncAria(e.target);
  });
})();

// --- Secure API Helpers (always sends X-RAIW-Request: 1) ---------------------
async function apiPostForm(url, data, signal) {
  const fd = data instanceof FormData ? data : new FormData();
  if (!(data instanceof FormData) && data) {
    Object.entries(data).forEach(([k, v]) => {
      if (v !== undefined && v !== null) fd.append(k, v);
    });
  }
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'X-RAIW-Request': '1' },
    body: fd,
    signal,
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || body.error || `HTTP ${resp.status}`);
  return body;
}

async function apiPostJsonBlob(url, payload) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'X-RAIW-Request': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || body.error || `HTTP ${resp.status}`);
  }
  return resp.blob();
}

async function decodePreviewFallback(file, maxSide = 1600) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('max_side', String(maxSide));
  const resp = await fetch('/decode-preview', {
    method: 'POST',
    headers: { 'X-RAIW-Request': '1' },
    body: fd,
  });
  if (!resp.ok) throw new Error('Decode preview failed');
  const blob = await resp.blob();
  const w = Number(resp.headers.get('X-Image-Width')) || 0;
  const h = Number(resp.headers.get('X-Image-Height')) || 0;
  return { url: URL.createObjectURL(blob), width: w, height: h };
}

function triggerDownload(url, filename) {
  const a = document.createElement('a');
  a.href = url;
  if (filename) a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function copyImageToClipboard(url) {
  try {
    if (!navigator.clipboard || typeof ClipboardItem === 'undefined') {
      throw new Error('Clipboard API unavailable');
    }
    const resp = await fetch(url);
    const blob = await resp.blob();
    let pngBlob = blob;
    if (blob.type !== 'image/png') {
      const bmp = await createImageBitmap(blob);
      const c = document.createElement('canvas');
      c.width = bmp.width;
      c.height = bmp.height;
      c.getContext('2d').drawImage(bmp, 0, 0);
      bmp.close();
      pngBlob = await new Promise((res, rej) => c.toBlob((b) => (b ? res(b) : rej(new Error('toBlob failed'))), 'image/png'));
    }
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': pngBlob })]);
    showToast(t('copiedImg'), 'ok', 2200);
  } catch {
    showToast(t('copyFailed'), 'warn', 3000);
  }
}

async function downloadBatchZip(jobIds) {
  if (!jobIds.length) return;
  try {
    const blob = await apiPostJsonBlob('/results/zip', { job_ids: jobIds });
    const url = URL.createObjectURL(blob);
    triggerDownload(url, 'cleaned_batch.zip');
    setTimeout(() => URL.revokeObjectURL(url), 15000);
    showToast(t('zipReady'), 'ok', 2500);
  } catch (err) {
    showToast(String(err.message || err), 'err');
  }
}

// --- Theme (color-scheme meta + light-dark() + dynamic theme-color) ----------
const THEMES = ['auto', 'light', 'dark'];
const THEME_LBL = { auto: 'Auto', light: 'Light', dark: 'Dark' };
const darkMql = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
let curTheme = 'auto';
try {
  const s = localStorage.getItem('color-scheme') || localStorage.getItem('theme');
  if (THEMES.includes(s)) curTheme = s;
} catch {}

function syncThemeColorMeta() {
  const tc = $('themeColorMeta');
  if (!tc) return;
  const isDark = curTheme === 'dark' || (curTheme === 'auto' && Boolean(darkMql && darkMql.matches));
  tc.content = isDark ? '#0b0f17' : '#f4f6fb';
}

function applyTheme(th, persist = true) {
  curTheme = THEMES.includes(th) ? th : 'auto';
  document.documentElement.classList.add('theme-switching');
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (curTheme === 'auto') {
    document.documentElement.removeAttribute('data-theme');
    if (meta) meta.content = 'light dark';
  } else {
    document.documentElement.setAttribute('data-theme', curTheme);
    if (meta) meta.content = curTheme;
  }
  syncThemeColorMeta();
  void document.documentElement.offsetHeight;
  requestAnimationFrame(() => document.documentElement.classList.remove('theme-switching'));
  $('themeLabel').textContent = THEME_LBL[curTheme];
  if (persist) {
    try {
      if (curTheme === 'auto') {
        localStorage.removeItem('color-scheme');
        localStorage.removeItem('theme');
      } else {
        localStorage.setItem('color-scheme', curTheme);
        localStorage.setItem('theme', curTheme);
      }
    } catch {}
  }
}

applyTheme(curTheme, false);
$('themeBtn').addEventListener('click', () => applyTheme(THEMES[(THEMES.indexOf(curTheme) + 1) % 3], true));
if (darkMql && typeof darkMql.addEventListener === 'function') {
  darkMql.addEventListener('change', () => {
    // Never delete a stored override; only keep theme-color synced when in Auto mode
    syncThemeColorMeta();
  });
}
window.addEventListener('storage', (e) => {
  if (e.key === 'color-scheme' || e.key === 'theme') {
    const next = e.newValue === 'light' || e.newValue === 'dark' ? e.newValue : 'auto';
    applyTheme(next, false);
  }
});

// --- Tabs with Same-Document View Transitions --------------------------------
let activeTab = 'image';
function applyTabDOM(name) {
  activeTab = name;
  document.querySelectorAll('.tab').forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + name));
  if (name !== 'erase') $('brushCursor').hidden = true;
}

function switchTab(name, { focusPanel = false } = {}) {
  if (name === activeTab) return;
  const doSwitch = () => applyTabDOM(name);
  if (typeof document.startViewTransition === 'function' && !prefersReducedMotion()) {
    const vt = document.startViewTransition(doSwitch);
    if (focusPanel) {
      vt.finished.finally(() => { $('tab-' + name)?.focus({ preventScroll: true }); });
    }
  } else {
    doSwitch();
    if (focusPanel) $('tab-' + name)?.focus({ preventScroll: true });
  }
}
document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));

// --- Global State & Native Top-Layer Popover Drawer --------------------------
let healthInfo = {};
let modelSnap = null;
let updateSnap = null;
let pipeline = '';
let drawerOpen = false;
let modelTimer = null;
let modelBusy = false;
let modelAbortCtrl = null;
let pendingDeleteKey = null;

function syncDrawerState(isOpen) {
  drawerOpen = !!isOpen;
  $('modelsToggleBtn').setAttribute('aria-expanded', drawerOpen ? 'true' : 'false');
  if (drawerOpen) {
    pollModels(false);
    fetchUpdateStatus();
  } else {
    pendingDeleteKey = null;
    if (!modelBusy) stopModelPolling();
  }
}

function setModelDrawer(open) {
  const drawer = $('modelDrawer');
  const want = !!open;
  if (supportsPopover()) {
    try {
      const currentlyOpen = drawer.matches(':popover-open');
      if (want && !currentlyOpen) drawer.showPopover();
      else if (!want && currentlyOpen) drawer.hidePopover();
    } catch {
      drawer.classList.toggle('popover-fallback-open', want);
      syncDrawerState(want);
    }
  } else {
    drawer.classList.toggle('popover-fallback-open', want);
    syncDrawerState(want);
  }
}

$('modelDrawer').addEventListener('toggle', (e) => {
  syncDrawerState(e.newState === 'open');
});
$('modelsToggleBtn').addEventListener('click', () => setModelDrawer(!drawerOpen));
$('gpuPill').addEventListener('click', () => setModelDrawer(true));
$('closeDrawerBtn').addEventListener('click', () => setModelDrawer(false));
$('openModelsFromHint').addEventListener('click', () => setModelDrawer(true));

function stopModelPolling() {
  clearTimeout(modelTimer);
  modelTimer = null;
  if (modelAbortCtrl) {
    modelAbortCtrl.abort();
    modelAbortCtrl = null;
  }
}

function scheduleNextModelPoll(fast) {
  clearTimeout(modelTimer);
  modelTimer = null;
  if (document.hidden) return;
  if (!drawerOpen && !modelBusy) return;
  const delay = fast || modelBusy ? 1500 : 8000;
  modelTimer = setTimeout(() => pollModels(false), delay);
}

function pollModels(fast) {
  if (modelAbortCtrl) modelAbortCtrl.abort();
  modelAbortCtrl = new AbortController();
  const url = '/model' + (pipeline ? '?profile=' + encodeURIComponent(pipeline) : '');
  fetch(url, { signal: modelAbortCtrl.signal })
    .then((r) => r.json())
    .then((snap) => {
      renderModels(snap);
      scheduleNextModelPoll(fast);
    })
    .catch((err) => {
      if (err && err.name === 'AbortError') return;
      scheduleNextModelPoll(false);
    });
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    clearTimeout(modelTimer);
    modelTimer = null;
  } else if (drawerOpen || modelBusy) {
    pollModels(modelBusy);
  }
});

// --- GitHub Updates UI (GET /update/status, POST /update/check, POST /update/apply)
function renderUpdateStatus(u) {
  updateSnap = u || null;
  const badge = $('updateStatusBadge');
  const metaRow = $('updateMetaRow');
  const list = $('updateCommitsList');
  const applyBtn = $('applyUpdateBtn');
  if (!u) return;

  if (u.git_available === false) {
    badge.className = 'badge warn';
    badge.textContent = t('gitUnavailable');
    metaRow.innerHTML = `<span>${esc(u.error || 'Not a git checkout — clone from GitHub to enable 1-click updates.')}</span>`;
    applyBtn.disabled = true;
    list.hidden = true;
    return;
  }

  const behindOrigin = Number(u.behind_origin || 0);
  const behindUpstream = Number(u.behind_upstream || 0);
  const totalBehind = Math.max(behindOrigin, behindUpstream);
  const dirty = Boolean(u.dirty);

  if (dirty) {
    badge.className = 'badge warn';
    badge.textContent = t('dirtyWorktree');
  } else if (totalBehind > 0) {
    badge.className = 'badge accent';
    badge.textContent = t('updatesAvailable', { n: totalBehind });
  } else {
    badge.className = 'badge ok';
    badge.textContent = t('upToDate');
  }

  const chips = [];
  if (u.current_version) chips.push(`<span class="badge">v${esc(u.current_version)}</span>`);
  if (u.branch) chips.push(`<span class="badge">${esc(u.branch)}${u.commit ? '@' + esc(String(u.commit).slice(0, 7)) : ''}</span>`);
  if (u.latest_upstream_tag) chips.push(`<span class="badge accent">Upstream ${esc(u.latest_upstream_tag)}</span>`);
  if (u.remotes && u.remotes.origin) {
    chips.push(`<span class="badge ${behindOrigin > 0 ? 'warn' : 'ok'}">origin: ${behindOrigin > 0 ? '-' + behindOrigin : 'synced'}</span>`);
  }
  if (u.remotes && u.remotes.upstream) {
    chips.push(`<span class="badge ${behindUpstream > 0 ? 'warn' : 'ok'}">upstream: ${behindUpstream > 0 ? '-' + behindUpstream : 'synced'}</span>`);
  }
  metaRow.innerHTML = chips.join(' ');

  const commits = Array.isArray(u.recent_commits) ? u.recent_commits : [];
  if (commits.length) {
    list.hidden = false;
    list.innerHTML = commits.slice(0, 8).map((c) => `<li>${esc(typeof c === 'string' ? c : (c.subject || c.message || JSON.stringify(c)))}</li>`).join('');
  } else {
    list.hidden = true;
    list.innerHTML = '';
  }

  applyBtn.disabled = dirty;
  if (u.error) {
    $('updateMsg').className = 'mnow err';
    $('updateMsg').textContent = u.error;
  }
}

async function fetchUpdateStatus() {
  try {
    const r = await fetch('/update/status');
    if (!r.ok) return;
    const data = await r.json();
    renderUpdateStatus(data);
  } catch {}
}

$('checkUpdateBtn').addEventListener('click', async () => {
  $('checkUpdateBtn').disabled = true;
  $('updateMsg').className = 'mnow';
  $('updateMsg').textContent = t('checkingUpdates');
  try {
    const data = await apiPostForm('/update/check', {});
    renderUpdateStatus(data);
    const n = Math.max(Number(data.behind_origin || 0), Number(data.behind_upstream || 0));
    $('updateMsg').className = 'mnow ' + (n > 0 ? 'ok' : '');
    $('updateMsg').textContent = n > 0 ? t('updatesAvailable', { n }) : t('upToDate');
    showToast(n > 0 ? t('updatesAvailable', { n }) : t('upToDate'), n > 0 ? 'ok' : 'info', 2600);
  } catch (err) {
    $('updateMsg').className = 'mnow err';
    $('updateMsg').textContent = String(err.message || err);
    showToast(String(err.message || err), 'err');
  } finally {
    $('checkUpdateBtn').disabled = false;
  }
});

$('applyUpdateBtn').addEventListener('click', async () => {
  $('applyUpdateBtn').disabled = true;
  $('checkUpdateBtn').disabled = true;
  $('updateMsg').className = 'mnow';
  $('updateMsg').textContent = t('updatingStudio');
  try {
    const res = await apiPostForm('/update/apply', { source: $('updateSourceSel').value || 'auto' });
    if (res.restart_required) {
      $('updateMsg').className = 'mnow ok';
      $('updateMsg').textContent = res.message || t('restartRequired');
      showToast(t('restartRequired'), 'ok', 6000);
    } else {
      $('updateMsg').className = 'mnow ' + (res.ok ? 'ok' : 'err');
      $('updateMsg').textContent = res.message || t('upToDate');
      showToast(res.message || t('upToDate'), res.ok ? 'ok' : 'warn', 3500);
    }
    fetchUpdateStatus();
  } catch (err) {
    $('updateMsg').className = 'mnow err';
    $('updateMsg').textContent = String(err.message || err);
    showToast(String(err.message || err), 'err');
  } finally {
    $('applyUpdateBtn').disabled = false;
    $('checkUpdateBtn').disabled = false;
  }
});

// --- Model Selector & Drawer Rendering ---------------------------------------
let lastDeepSelSig = '';
function syncDeepProfileSelect(s) {
  const sel = $('deepProfSel');
  if (document.activeElement === sel) return;
  const vram = healthInfo.vram_gb || 0;
  const sig = s.profiles.map((p) => `${p.id}:${p.ready}:${p.default}:${vram}`).join('|') + '@' + s.profile;
  if (sig === lastDeepSelSig) return;
  lastDeepSelSig = sig;

  sel.innerHTML = '';
  s.profiles.forEach((p) => {
    const o = document.createElement('option');
    o.value = p.id;
    const mark = p.ready ? '✓ ' : '';
    const star = p.default ? ' ★' : '';
    const vramTag = vram && p.min_vram_gb && vram < p.min_vram_gb ? ` [⚠ ≥${p.min_vram_gb}GB]` : '';
    o.textContent = `${mark}${p.short || p.id} — ${p.badge || ''}${vramTag}${star}`;
    sel.appendChild(o);
  });
  sel.value = s.profile;
}

function renderModels(s) {
  modelSnap = s;
  pipeline = s.profile;
  syncDeepProfileSelect(s);

  const curMeta = s.profiles.find((p) => p.id === s.profile) || {};
  const vram = healthInfo.vram_gb || 0;
  const exceedsVram = Boolean(vram && curMeta.min_vram_gb && vram < curMeta.min_vram_gb);
  const vramBadge = exceedsVram
    ? ` <span class="badge err">⚠ Needs ≥${curMeta.min_vram_gb} GB VRAM (${vram} GB GPU)</span>`
    : vram
      ? ` <span class="badge ok">✓ Fits ${vram} GB VRAM</span>`
      : '';

  const ready = s.models.filter((m) => m.stage === 'global').every((m) => m.complete);
  $('deepModeBadge').textContent = curMeta.short || s.profile;
  $('deepProfHintText').innerHTML =
    `<b>${esc(curMeta.short || s.profile)}</b> · ` +
    (ready
      ? `<span style="color:var(--ok);font-weight:600;">✓ Cached (${fmtSize(s.disk_bytes)})</span>`
      : s.total
        ? `${s.percent ?? 0}% cached (${fmtSize(Math.max(0, s.total - s.bytes))} remaining)`
        : 'Checking cache…') +
    vramBadge;

  // Tier 1: Fast Core Pack
  $('lightList').innerHTML = '';
  (s.lightweight || []).forEach((m) => {
    const row = document.createElement('div');
    row.className = 'mrow-item' + (m.complete ? ' ok' : '');
    const sz = m.complete
      ? `✓ ${fmtSize(m.bytes)}`
      : m.total
        ? `${fmtSize(m.bytes)} / ${fmtSize(m.total)}`
        : fmtSize(m.bytes);
    row.innerHTML =
      `<div class="mrow-left"><div class="mrow-name">${esc(m.label)}</div>` +
      `<div class="mrow-sub">${esc(m.repo_id)}</div></div>` +
      `<div class="mrow-right"><span>${sz}${m.rate_mb_s ? ' · ' + m.rate_mb_s + ' MB/s' : ''}</span>` +
      `<span class="badge ${m.complete ? 'ok' : 'warn'}">${m.complete ? 'Ready' : 'Missing'}</span></div>`;
    $('lightList').appendChild(row);
  });
  $('dlLightBtn').textContent = s.lightweight_ready ? t('corePackReady') : t('downloadCorePack');
  $('dlLightBtn').disabled = !!(s.job && s.job.active) || s.lightweight_ready;

  // Tier 2: Selectable Profile Cards
  const pc = $('profileCards');
  pc.innerHTML = '';
  s.profiles.forEach((p) => {
    const tooBig = Boolean(vram && p.min_vram_gb && vram < p.min_vram_gb);
    const card = document.createElement('div');
    card.className = 'prof-card' + (p.id === s.profile ? ' active' : '') + (tooBig ? ' vram-warn' : '');
    card.dataset.profId = p.id;
    const statusPill = p.ready ? `<span class="badge ok">✓ Ready</span>` : `<span class="badge">Not cached</span>`;
    const vPill = tooBig
      ? `<span class="badge err">⚠ ≥${p.min_vram_gb} GB VRAM</span>`
      : vram
        ? `<span class="badge ok">✓ Fits ${vram} GB</span>`
        : '';
    const defStar = p.default ? `<span class="badge accent">★ Default</span>` : '';
    const loadedTag = s.loaded && s.loaded.includes(p.id) ? `<span class="badge accent">In VRAM</span>` : '';
    const compatNote = p.notes ? ` · ${esc(p.notes)}` : '';
    card.innerHTML =
      `<div class="prof-card-top">` +
        `<span class="prof-card-title">${esc(p.short || p.id)} <span class="badge">${esc(p.badge || '')}</span></span>` +
        `<span class="inline-row">${statusPill}${vPill}${defStar}${loadedTag}</span>` +
      `</div>` +
      `<div class="prof-card-desc">${esc(p.desc || '')} · <span>${esc(p.license || '')}</span>${compatNote}</div>`;
    pc.appendChild(card);
  });

  // Diffusion progress bar & controls
  $('modelFolder').textContent = s.cache_root || '—';
  if (s.diffsynth_root && document.activeElement !== $('folderInp')) $('folderInp').value = s.diffsynth_root;

  const pct = s.percent == null ? 0 : s.percent;
  $('modelBar').style.width = pct + '%';
  const active = s.models.filter((m) => m.rate_mb_s);
  const job = s.job || {};
  modelBusy = !!job.active || active.length > 0;
  $('modelsBtnLabel').textContent = modelBusy ? t('modelsDownloading') : t('models');

  $('dlBtn').disabled = !!job.active;
  $('dlBtn').textContent = job.active
    ? job.pausing ? 'Pausing…' : 'Downloading…'
    : ready ? 'Check / Download Missing' : t('downloadProfile');
  $('pauseBtn').disabled = !job.active || !!job.pausing;

  $('dlNow').className = 'mnow' + (job.error ? ' err' : '');
  if (job.error) $('dlNow').textContent = 'Download error: ' + job.error;
  else if (job.pausing) $('dlNow').textContent = 'Finishing current file, then pausing — ' + (job.current || '');
  else if (job.current) $('dlNow').textContent = 'Downloading ' + job.current;
  else $('dlNow').textContent = '';

  if (active.length) {
    $('modelState').className = 'badge accent';
    $('modelState').textContent = `Downloading ${pct}% · ${active[0].rate_mb_s} MB/s`;
  } else if (ready) {
    $('modelState').className = 'badge ok';
    const loaded = s.loaded && s.loaded.includes(s.profile) ? ' · In VRAM' : '';
    $('modelState').textContent = `✓ ${fmtSize(s.disk_bytes)} on disk${loaded}`;
  } else {
    $('modelState').className = 'badge warn';
    $('modelState').textContent = s.total
      ? `${pct}% · ${fmtSize(Math.max(0, s.total - s.bytes))} remaining`
      : 'Checking…';
  }

  // Per-model rows with inline 2-step Delete confirmation
  $('modelList').innerHTML = '';
  s.models.forEach((m) => {
    const row = document.createElement('div');
    row.className = 'mrow-item' + (m.complete ? ' ok' : '');
    const delKey = `${m.store}:${m.repo_id}`;
    const sz = m.complete
      ? `✓ ${fmtSize(m.bytes)} on disk`
      : m.total
        ? `${fmtSize(m.bytes)} / ${fmtSize(m.total)}`
        : fmtSize(m.bytes);
    const stageTag = m.stage === 'face' ? ' <span class="badge">face</span>' : '';
    let delHtml = '';
    if (m.bytes > 1_000_000) {
      if (pendingDeleteKey === delKey) {
        delHtml =
          `<button class="danger-solid xs" data-confirm-del="${esc(delKey)}" data-del-repo="${esc(m.repo_id)}" data-del-store="${esc(m.store)}">${esc(t('confirmDel'))}</button>` +
          `<button class="ghost xs" data-cancel-del="1">${esc(t('cancel'))}</button>`;
      } else {
        delHtml = `<button class="danger xs icon-only" data-ask-del="${esc(delKey)}" title="Delete cached weights">${ICO.trash}</button>`;
      }
    }
    row.innerHTML =
      `<div class="mrow-left"><div class="mrow-name">${esc(m.label)}${stageTag}</div>` +
      `<div class="mrow-sub">${esc(m.repo_id)} (${esc(m.store)})</div></div>` +
      `<div class="mrow-right"><span>${sz}${m.rate_mb_s ? ' · ' + m.rate_mb_s + ' MB/s' : ''}</span>${delHtml}</div>`;
    $('modelList').appendChild(row);
  });

  // Prominent Duplicate Cache Banner
  const stale = s.stale_cache || [];
  if (stale.length) {
    $('staleBox').hidden = false;
    $('staleBox').innerHTML =
      `<b>Duplicate cache detected — reclaim disk space:</b>` +
      stale
        .map((x) => {
          const delKey = `stale_hf:${x.repo_id}`;
          const btns =
            pendingDeleteKey === delKey
              ? `<button class="danger-solid xs" data-confirm-del="${esc(delKey)}" data-del-repo="${esc(x.repo_id)}" data-del-store="stale_hf">${esc(t('confirmDel'))}</button>` +
                `<button class="ghost xs" data-cancel-del="1">${esc(t('cancel'))}</button>`
              : `<button class="danger xs" data-ask-del="${esc(delKey)}">Clean up ${fmtSize(x.bytes)}</button>`;
          return `<div class="stale-row"><span><code>${esc(x.repo_id)}</code> — <b>${fmtSize(x.bytes)}</b></span><span class="inline-row">${btns}</span></div>`;
        })
        .join('');
  } else {
    $('staleBox').hidden = true;
  }
}

$('modelDrawer').addEventListener('click', async (e) => {
  const profCard = e.target.closest('[data-prof-id]');
  if (profCard) {
    pipeline = profCard.dataset.profId;
    pendingDeleteKey = null;
    pollModels(false);
    return;
  }
  const askBtn = e.target.closest('[data-ask-del]');
  if (askBtn) {
    pendingDeleteKey = askBtn.dataset.askDel;
    if (modelSnap) renderModels(modelSnap);
    return;
  }
  if (e.target.closest('[data-cancel-del]')) {
    pendingDeleteKey = null;
    if (modelSnap) renderModels(modelSnap);
    return;
  }
  const confirmBtn = e.target.closest('[data-confirm-del]');
  if (confirmBtn) {
    const repo = confirmBtn.dataset.delRepo;
    const store = confirmBtn.dataset.delStore;
    confirmBtn.disabled = true;
    pendingDeleteKey = null;
    try {
      const res = await apiPostForm('/model/delete', { repo_id: repo, store, profile: pipeline });
      if (res.state) renderModels(res.state);
      if (res.ok) showToast(`Freed ${fmtSize(res.freed_bytes)} from ${repo}`, 'ok');
      else showToast(res.error || 'Delete failed', 'err');
    } catch (err) {
      showToast(String(err.message || err), 'err');
    }
  }
});

$('deepProfSel').addEventListener('change', () => {
  pipeline = $('deepProfSel').value;
  pollModels(false);
});
$('dlBtn').addEventListener('click', () => {
  apiPostForm('/model/download', { profile: pipeline, include_face: $('faceChk').checked ? 'true' : 'false' })
    .then(() => { modelBusy = true; pollModels(true); })
    .catch((e) => showToast(e.message, 'err'));
});
$('dlLightBtn').addEventListener('click', () => {
  apiPostForm('/model/download', { profile: 'lightweight' })
    .then(() => { modelBusy = true; pollModels(true); })
    .catch((e) => showToast(e.message, 'err'));
});
$('pauseBtn').addEventListener('click', () => {
  $('pauseBtn').disabled = true;
  apiPostForm('/model/pause', {}).then(() => pollModels(false)).catch((e) => showToast(e.message, 'err'));
});
$('recheckBtn').addEventListener('click', () => {
  $('recheckBtn').disabled = true;
  apiPostForm('/model/recheck', { profile: pipeline })
    .then((snap) => { renderModels(snap); showToast('Model cache re-checked', 'info', 1800); })
    .catch((e) => showToast(e.message, 'err'))
    .finally(() => { $('recheckBtn').disabled = false; });
});
$('setDefaultProfBtn').addEventListener('click', async () => {
  try {
    await apiPostForm('/settings', { default_profile: pipeline });
    pollModels(false);
    showToast(`Default profile set to ${pipeline}`, 'ok');
  } catch (e) {
    showToast(e.message, 'err');
  }
});
async function saveFolderSetting() {
  $('folderBtn').disabled = true;
  $('folderMsg').className = 'mnow';
  $('folderMsg').textContent = 'Saving…';
  try {
    const r = await apiPostForm('/model/folder', { path: $('folderInp').value, profile: pipeline });
    $('folderMsg').className = 'mnow ' + (r.ok ? 'ok' : 'err');
    $('folderMsg').textContent = r.error ? r.error : 'Saved: ' + r.folder;
    if (r.state) renderModels(r.state);
  } catch (err) {
    $('folderMsg').className = 'mnow err';
    $('folderMsg').textContent = String(err.message || err);
  } finally {
    $('folderBtn').disabled = false;
  }
}
$('folderBtn').addEventListener('click', saveFolderSetting);
$('folderInp').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    if (isImeEvent(e)) return;
    saveFolderSetting();
  }
});

// --- Universal Hardware Formatting & Health Boot -----------------------------
function formatOnnxLabel(provider, npuDetected) {
  if (!provider) return npuDetected ? 'NPU' : '';
  const p = String(provider);
  if (p.includes('CUDA')) return 'CUDA';
  if (p.includes('ROCM') || p.includes('MIGraphX')) return 'ROCm';
  if (p.includes('Dml') || p.includes('DirectML')) return 'DirectML';
  if (p.includes('OpenVINO')) return npuDetected ? 'OpenVINO NPU' : 'OpenVINO';
  if (p.includes('QNN')) return 'QNN NPU';
  if (p.includes('CoreML')) return 'CoreML';
  if (p.includes('CPU')) return 'CPU';
  return p.replace('ExecutionProvider', '');
}

function formatHardwarePill(h) {
  const hw = h.hardware || {};
  const kind = h.accelerator_kind || hw.accelerator_kind || (h.gpu ? 'cuda' : 'cpu');
  const devName = h.device_name || hw.device_name || h.device || 'CPU';
  const vram = h.vram_gb != null ? h.vram_gb : hw.vram_gb;
  const bf16 = h.bf16_supported != null ? h.bf16_supported : hw.bf16_supported;
  const npu = Boolean(h.npu_detected || hw.npu_detected);
  const onnxProv = h.active_onnx_provider || hw.active_onnx_provider || '';
  const onnxShort = formatOnnxLabel(onnxProv, npu);

  const shortName = String(devName)
    .replace(/^NVIDIA\s+GeForce\s+/i, 'NVIDIA ')
    .replace(/^AMD\s+Radeon\(TM\)\s+/i, 'AMD Radeon ')
    .replace(/^Intel\(R\)\s+/i, 'Intel ')
    .trim();

  let label = 'CPU Mode';
  let ok = false;
  if (kind === 'cuda') {
    ok = true;
    const prec = bf16 === false ? ' · FP16' : '';
    label = vram ? `${shortName} · ${vram} GB${prec}` : `${shortName}${prec}`;
  } else if (kind === 'rocm') {
    ok = true;
    label = vram ? `${shortName} (ROCm) · ${vram} GB` : `${shortName} (ROCm)`;
  } else if (kind === 'xpu') {
    ok = true;
    label = vram ? `${shortName} (XPU) · ${vram} GB` : `${shortName} (XPU)`;
  } else if (kind === 'mps') {
    ok = true;
    label = vram ? `Apple MPS · ${vram} GB` : 'Apple MPS';
  } else if (kind === 'dml') {
    ok = true;
    label = `${shortName} (DirectML)`;
  } else if (npu) {
    ok = true;
    label = `NPU (${onnxShort || 'OpenVINO'})`;
  }

  return { kind, devName, vram, bf16, npu, onnxProv, onnxShort, label, ok };
}

function renderHardwareDrawerCard(h, info) {
  const hw = h.hardware || {};
  const onnxBadge = $('hwOnnxBadge');
  onnxBadge.textContent = info.onnxShort ? `ONNX: ${info.onnxShort}` : 'ONNX';
  onnxBadge.className = 'badge ' + (info.onnxShort && info.onnxShort !== 'CPU' ? 'ok' : '');

  const precLabel = info.kind === 'cpu'
    ? 'FP32'
    : info.bf16 === true
      ? 'BF16 / FP16'
      : 'FP16';
  const notes = Array.isArray(hw.notes) ? hw.notes : [];

  $('hwSummaryBox').innerHTML =
    `<div class="hw-grid">` +
      `<div class="hw-stat"><span class="hw-stat-k">Accelerator</span><span class="hw-stat-v">${esc(info.devName)}</span></div>` +
      `<div class="hw-stat"><span class="hw-stat-k">Backend / Precision</span><span class="hw-stat-v">${esc(info.kind.toUpperCase())} · ${esc(precLabel)}</span></div>` +
      `<div class="hw-stat"><span class="hw-stat-k">VRAM</span><span class="hw-stat-v">${info.vram ? esc(info.vram + ' GB') : 'Shared / N/A'}</span></div>` +
      `<div class="hw-stat"><span class="hw-stat-k">ONNX / NPU</span><span class="hw-stat-v">${esc(info.onnxShort || 'CPU')}${info.npu ? ' · NPU ✓' : ''}</span></div>` +
    `</div>` +
    (notes.length ? `<div class="note flush">${notes.map((n) => esc(n)).join(' · ')}</div>` : '');

  // Annotate Compute Device selector with available devices
  const avail = new Set(h.diffusion_devices || hw.diffusion_devices || []);
  if (avail.size) {
    Array.from($('deviceSel').options).forEach((opt) => {
      if (opt.value === 'auto') return;
      const base = opt.dataset.baseLabel || opt.textContent;
      opt.dataset.baseLabel = base;
      const match = avail.has(opt.value) || (opt.value === 'cuda' && avail.has('rocm'));
      opt.textContent = match ? `✓ ${base}` : base;
    });
  }
}

fetch('/health')
  .then((r) => r.json())
  .then((h) => {
    healthInfo = h;
    $('verPill').textContent = 'v' + (h.version || '?');
    if (h.default_backend) $('backendSel').value = h.default_backend;
    if (h.default_profile) pipeline = h.default_profile;
    updateImgOptSummary();

    const info = formatHardwarePill(h);
    const pill = $('gpuPill');
    pill.className = 'gpu-pill ' + (info.ok ? 'ok' : 'warn');
    $('gpuPillText').textContent = info.label;
    if (info.onnxShort) {
      $('onnxPillBadge').textContent = info.onnxShort;
      $('onnxPillBadge').hidden = false;
    }
    pill.title = `${info.devName} (${info.kind.toUpperCase()}${info.vram ? ', ' + info.vram + ' GB' : ''}) · ONNX: ${info.onnxShort || 'CPU'} — Click for Models & Updates`;
    renderHardwareDrawerCard(h, info);

    pollModels(false);
  })
  .catch(() => {
    $('gpuPill').className = 'gpu-pill warn';
    $('gpuPillText').textContent = 'Offline';
  });

// --- Native <dialog> Light-Dismiss Fallback (when closedby is unsupported) ---
(function initDialogClosedByFallback() {
  if ('closedBy' in HTMLDialogElement.prototype) return;
  const outside = (e, dialog) => {
    const r = dialog.getBoundingClientRect();
    return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
  };
  for (const dialog of document.querySelectorAll('dialog[closedby="any"]')) {
    let pressedOutside = false;
    dialog.addEventListener('pointerdown', (e) => { pressedOutside = outside(e, dialog); });
    dialog.addEventListener('pointerup', (e) => {
      if (pressedOutside && outside(e, dialog)) dialog.close();
      pressedOutside = false;
    });
  }
})();

// --- Reusable Compare Slider (used in Modal & Erase In-Place Preview) --------
function buildCompareWidget(mountEl, beforeUrl, afterUrl, opts = {}) {
  const mode = opts.mode || 'split';
  const zoom = opts.zoom || 'fit';
  let panX = 0;
  let panY = 0;
  let scale = zoom === 'fit' ? 1 : Number(zoom);
  let splitPct = 50;
  let peeking = false;

  if (mode === 'sbs') {
    mountEl.innerHTML =
      `<div class="compare-stage" style="padding:0;">` +
        `<div class="compare-sbs">` +
          `<div class="compare-sbs-pane"><img src="${beforeUrl}" alt="Before" /><span class="compare-tag l">${esc(t('before'))}</span></div>` +
          `<div class="compare-sbs-pane"><img src="${afterUrl}" alt="Cleaned" /><span class="compare-tag r">${esc(t('after'))}</span></div>` +
        `</div>` +
      `</div>`;
    return { setPeek: () => {}, setZoom: () => {}, destroy: () => { mountEl.innerHTML = ''; } };
  }

  mountEl.innerHTML =
    `<div class="compare-stage">` +
      `<div class="compare-box">` +
        `<img class="cmp-before" src="${beforeUrl}" alt="Before" />` +
        `<div class="compare-after-wrap" style="clip-path:${mode === 'peek' ? 'inset(0 0 0 0)' : 'inset(0 0 0 50%)'};">` +
          `<img class="cmp-after" src="${afterUrl}" alt="Cleaned" />` +
        `</div>` +
        (mode === 'split' ? `<div class="compare-line" style="left:50%;"><div class="compare-handle">⇄</div></div>` : '') +
      `</div>` +
      `<span class="compare-tag l">${esc(mode === 'peek' ? t('holdSpaceHint') : t('before'))}</span>` +
      (mode === 'split' ? `<span class="compare-tag r">${esc(t('after'))}</span>` : '') +
    `</div>`;

  const stage = mountEl.querySelector('.compare-stage');
  const box = mountEl.querySelector('.compare-box');
  const afterWrap = mountEl.querySelector('.compare-after-wrap');
  const line = mountEl.querySelector('.compare-line');
  const handle = mountEl.querySelector('.compare-handle');
  const leftTag = mountEl.querySelector('.compare-tag.l');

  const applyTransform = () => {
    if (scale <= 1) { panX = 0; panY = 0; }
    box.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
  };

  const applySplit = (pct) => {
    splitPct = clamp(pct, 0, 100);
    if (afterWrap) afterWrap.style.clipPath = `inset(0 0 0 ${splitPct}%)`;
    if (line) line.style.left = splitPct + '%';
  };

  const setPeek = (on) => {
    if (mode === 'sbs') return;
    peeking = !!on;
    afterWrap.style.opacity = peeking ? '0' : '1';
    if (line) line.style.opacity = peeking ? '0' : '1';
    if (mode === 'peek') {
      leftTag.textContent = peeking ? t('before') : t('after') + ' · ' + t('holdSpaceHint');
    }
  };
  if (mode === 'peek') setPeek(false);

  let dragKind = null;
  let startX = 0;
  let startY = 0;
  let origPanX = 0;
  let origPanY = 0;

  stage.addEventListener('pointerdown', (e) => {
    if (mode === 'peek') {
      if (scale > 1) {
        dragKind = 'pan';
        startX = e.clientX; startY = e.clientY; origPanX = panX; origPanY = panY;
        stage.setPointerCapture(e.pointerId);
      } else {
        setPeek(true);
        stage.setPointerCapture(e.pointerId);
      }
      return;
    }
    const onHandle = handle && (e.target === handle || handle.contains(e.target));
    if (scale > 1 && !onHandle) {
      dragKind = 'pan';
      startX = e.clientX; startY = e.clientY; origPanX = panX; origPanY = panY;
    } else {
      dragKind = 'split';
      const rect = box.getBoundingClientRect();
      applySplit(((e.clientX - rect.left) / Math.max(1, rect.width)) * 100);
    }
    stage.setPointerCapture(e.pointerId);
  });

  stage.addEventListener('pointermove', (e) => {
    if (!dragKind) return;
    if (dragKind === 'pan') {
      panX = origPanX + (e.clientX - startX);
      panY = origPanY + (e.clientY - startY);
      applyTransform();
    } else if (dragKind === 'split') {
      const rect = box.getBoundingClientRect();
      applySplit(((e.clientX - rect.left) / Math.max(1, rect.width)) * 100);
    }
  });

  const endDrag = () => {
    dragKind = null;
    if (mode === 'peek' && peeking) setPeek(false);
  };
  stage.addEventListener('pointerup', endDrag);
  stage.addEventListener('pointercancel', endDrag);

  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.18 : 1 / 1.18;
    scale = clamp(scale * factor, 1, 5);
    applyTransform();
    if (opts.onZoomChange) opts.onZoomChange(scale);
  }, { passive: false });

  const resolveScale = (z) => {
    if (z === 'fit') return 1;
    const n = Number(z) || 1;
    const imgEl = mountEl.querySelector('.cmp-before');
    if (imgEl && imgEl.naturalWidth > 0 && imgEl.clientWidth > 0) {
      const nativeScale = imgEl.naturalWidth / imgEl.clientWidth;
      if (nativeScale > 1.05) return clamp(nativeScale * n, 1, 6);
    }
    return clamp(n === 1 ? 1.5 : n, 1, 6);
  };

  applyTransform();
  return {
    setPeek,
    setZoom: (z) => {
      scale = resolveScale(z);
      applyTransform();
    },
    destroy: () => { mountEl.innerHTML = ''; },
  };
}

// --- Native <dialog> Compare Modal -------------------------------------------
let cmpList = [];
let cmpIdx = 0;
let cmpMode = 'split';
let cmpZoom = 'fit';
let cmpWidget = null;

function renderCompareModal() {
  const item = cmpList[cmpIdx];
  if (!item) return;
  $('compareTitle').textContent = item.title;
  const multi = cmpList.length > 1;
  $('cmpPrevBtn').hidden = !multi;
  $('cmpNextBtn').hidden = !multi;
  $('cmpCounter').hidden = !multi;
  if (multi) {
    $('cmpCounter').textContent = `${cmpIdx + 1} / ${cmpList.length}`;
    $('cmpPrevBtn').disabled = cmpIdx === 0;
    $('cmpNextBtn').disabled = cmpIdx === cmpList.length - 1;
  }

  document.querySelectorAll('#cmpModeSeg button').forEach((b) => b.classList.toggle('active', b.dataset.cmode === cmpMode));
  document.querySelectorAll('#cmpZoomSeg button').forEach((b) => b.classList.toggle('active', b.dataset.czoom === String(cmpZoom)));
  $('cmpZoomSeg').hidden = cmpMode === 'sbs';

  if (cmpWidget) cmpWidget.destroy();
  cmpWidget = buildCompareWidget($('compareModalMount'), item.beforeUrl, item.afterUrl, {
    mode: cmpMode,
    zoom: cmpZoom,
    onZoomChange: (sc) => {
      cmpZoom = sc <= 1.02 ? 'fit' : sc;
      document.querySelectorAll('#cmpZoomSeg button').forEach((b) => {
        const match = (b.dataset.czoom === 'fit' && sc <= 1.02) || Number(b.dataset.czoom) === Math.round(sc);
        b.classList.toggle('active', match);
      });
    },
  });

  const parts = [];
  if (item.origSize != null && item.summary && item.summary.size_bytes != null) {
    parts.push(`<span class="badge">${fmtSize(item.origSize)} → ${fmtSize(item.summary.size_bytes)}</span>`);
  }
  if (item.summary) parts.push(renderSummaryChips(item.summary));
  $('cmpFootInfo').innerHTML = parts.join(' ');
}

function openCompareModalBatch(items, startIdx = 0) {
  cmpList = items;
  cmpIdx = clamp(startIdx, 0, Math.max(0, items.length - 1));
  cmpMode = 'split';
  cmpZoom = 'fit';
  const dlg = $('compareModal');
  if (!dlg.open) dlg.showModal();
  renderCompareModal();
}

function closeCompareModal() {
  const dlg = $('compareModal');
  if (dlg.open) dlg.close();
}

$('compareModal').addEventListener('close', () => {
  $('compareModal').returnValue = '';
  if (cmpWidget) { cmpWidget.destroy(); cmpWidget = null; }
  $('compareModalMount').innerHTML = '';
  cmpList = [];
});
$('compareCloseBtn').addEventListener('click', closeCompareModal);
$('cmpPrevBtn').addEventListener('click', () => { if (cmpIdx > 0) { cmpIdx--; renderCompareModal(); } });
$('cmpNextBtn').addEventListener('click', () => { if (cmpIdx < cmpList.length - 1) { cmpIdx++; renderCompareModal(); } });
document.querySelectorAll('#cmpModeSeg button').forEach((b) => {
  b.addEventListener('click', () => { cmpMode = b.dataset.cmode; renderCompareModal(); });
});
document.querySelectorAll('#cmpZoomSeg button').forEach((b) => {
  b.addEventListener('click', () => {
    cmpZoom = b.dataset.czoom;
    document.querySelectorAll('#cmpZoomSeg button').forEach((x) => x.classList.toggle('active', x === b));
    if (cmpWidget) cmpWidget.setZoom(cmpZoom);
  });
});
$('compareDlBtn').addEventListener('click', () => {
  const item = cmpList[cmpIdx];
  if (item) triggerDownload(item.dlUrl, item.dlName);
});
$('compareCopyBtn').addEventListener('click', () => {
  const item = cmpList[cmpIdx];
  if (item) copyImageToClipboard(item.afterUrl);
});
$('compareEraseBtn').addEventListener('click', async () => {
  const item = cmpList[cmpIdx];
  if (!item) return;
  closeCompareModal();
  await loadUrlIntoErase(item.afterUrl, item.dlName || item.title);
});

// --- Native <dialog> Video Preview Modal -------------------------------------
let vidPrevDl = null;
function openVideoPreview(title, previewUrl, dlUrl, dlName) {
  $('vidPreviewTitle').textContent = title;
  vidPrevDl = { dlUrl, dlName };
  const player = $('vidPreviewPlayer');
  player.src = previewUrl;
  const dlg = $('vidPreviewModal');
  if (!dlg.open) dlg.showModal();
  player.play().catch(() => {});
}
function closeVideoPreview() {
  const dlg = $('vidPreviewModal');
  if (dlg.open) dlg.close();
}
$('vidPreviewModal').addEventListener('close', () => {
  $('vidPreviewModal').returnValue = '';
  const player = $('vidPreviewPlayer');
  player.pause();
  player.removeAttribute('src');
  player.load();
  vidPrevDl = null;
});
$('vidPreviewCloseBtn').addEventListener('click', closeVideoPreview);
$('vidPreviewDlBtn').addEventListener('click', () => {
  if (vidPrevDl) triggerDownload(vidPrevDl.dlUrl, vidPrevDl.dlName);
});

// --- Native <dialog> Keyboard Shortcuts Modal --------------------------------
function toggleKbdModal(force) {
  const dlg = $('kbdModal');
  const want = force !== undefined ? Boolean(force) : !dlg.open;
  if (want && !dlg.open) dlg.showModal();
  else if (!want && dlg.open) dlg.close();
}
$('kbdModal').addEventListener('close', () => {
  $('kbdModal').returnValue = '';
});
$('kbdBtn').addEventListener('click', () => toggleKbdModal());
$('kbdCloseBtn').addEventListener('click', () => toggleKbdModal(false));

// ==================== TAB 1: IMAGE CLEAN ====================
let imgMode = 'quick';
let imgItems = [];
let imgActiveWorkers = 0;
let imgStopRequested = false;
let autoCleanUserTouched = false;

function updateImgOptSummary() {
  const beMap = { auto: t('beAuto'), lama: 'big-LaMa', migan: 'MI-GAN', cv2: 'OpenCV' };
  const sMap = { auto: t('sensAuto'), strict: 'Strict' };
  const beLbl = beMap[$('backendSel').value] || $('backendSel').value;
  const sLbl = sMap[$('sensSel').value] || $('sensSel').value;
  $('imgOptSummary').textContent = `${beLbl} · ${sLbl}`;
}

function updateImageModeUI() {
  const isDeep = imgMode === 'deep';
  const isMeta = imgMode === 'metadata';
  $('deepStrip').hidden = !isDeep;
  $('imgOptToggleBtn').hidden = isMeta;
  if (isMeta) {
    $('imgOptPanel').hidden = true;
    $('imgOptToggleBtn').setAttribute('aria-expanded', 'false');
    $('imgOptCaret').textContent = '▾';
  }
  if (!isDeep) {
    $('advDetails').open = false;
  }
  if (!autoCleanUserTouched) {
    $('autoCleanChk').checked = !isDeep;
  }
  updateImageActionRow();
}

document.querySelectorAll('#imgModes .mode').forEach((el) =>
  el.addEventListener('click', () => {
    document.querySelectorAll('#imgModes .mode').forEach((x) => x.classList.remove('active'));
    el.classList.add('active');
    imgMode = el.dataset.mode;
    autoCleanUserTouched = false;
    updateImageModeUI();
  }),
);
$('autoCleanChk').addEventListener('change', () => { autoCleanUserTouched = true; });
$('imgOptToggleBtn').addEventListener('click', () => {
  const open = $('imgOptPanel').hidden;
  $('imgOptPanel').hidden = !open;
  $('imgOptToggleBtn').setAttribute('aria-expanded', open ? 'true' : 'false');
  $('imgOptCaret').textContent = open ? '▴' : '▾';
});
$('backendSel').addEventListener('change', () => {
  updateImgOptSummary();
  apiPostForm('/settings', { default_backend: $('backendSel').value }).catch(() => {});
});
$('sensSel').addEventListener('change', updateImgOptSummary);
updateImageModeUI();

function wireDrop(dropEl, inputEl, onFiles) {
  ['dragenter', 'dragover'].forEach((ev) =>
    dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.add('hover'); }),
  );
  ['dragleave', 'drop'].forEach((ev) =>
    dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.remove('hover'); }),
  );
  dropEl.addEventListener('drop', (e) => {
    e.stopPropagation();
    dragDepth = 0;
    $('globalDropOverlay').hidden = true;
    onFiles(e.dataTransfer.files);
  });
  dropEl.addEventListener('click', () => inputEl.click());
  dropEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      if (isImeEvent(e)) return;
      e.preventDefault();
      inputEl.click();
    }
  });
  inputEl.addEventListener('change', () => { onFiles(inputEl.files); inputEl.value = ''; });
}

function updateImageActionRow() {
  const hasItems = imgItems.length > 0;
  $('imgActionRow').hidden = !hasItems;
  if (!hasItems) {
    $('overall').hidden = true;
    return;
  }
  const running = imgActiveWorkers > 0;
  const doneItems = imgItems.filter((i) => i.done && i.jobId);
  const pendingCount = imgItems.filter((i) => !i.done && !i.running).length;
  const diffModeDone = doneItems.filter((i) => i.cleanedMode && i.cleanedMode !== imgMode).length;

  $('go').hidden = running;
  $('go').disabled = pendingCount === 0;
  $('goLabel').textContent = pendingCount > 1 ? `${t('cleanBtn')} (${pendingCount})` : t('cleanBtn');
  $('stopBtn').hidden = !running;
  $('clear').disabled = running;
  $('zipAllBtn').hidden = doneItems.length < 2;
  $('recleanModeBtn').hidden = running || diffModeDone === 0;
  if (diffModeDone > 0) {
    const modeNames = { quick: t('modeQuick'), deep: t('modeDeep'), metadata: t('modeMeta') };
    $('recleanModeLabel').textContent = `${t('recleanIn')} ${modeNames[imgMode] || imgMode}`;
  }
}

function updateOverall() {
  if (!imgItems.length) { $('overall').hidden = true; return; }
  const done = imgItems.filter((i) => i.done).length;
  const pct = Math.round(imgItems.reduce((s, i) => s + i.pct, 0) / imgItems.length);
  $('overallBar').style.width = pct + '%';
  $('overallLbl').textContent = `${done} / ${imgItems.length}`;
  $('overallPct').textContent = `${pct}%`;
  updateImageActionRow();
}

function setImgItem(it, pct, text, cls) {
  if (pct != null) { it.pct = Math.max(it.pct, pct); it.bar.style.width = it.pct + '%'; }
  if (text != null) it.st.textContent = text;
  if (cls !== undefined) it.el.className = 'item' + (cls ? ' ' + cls : '');
}

function renderSummaryChips(sum) {
  if (!sum) return '';
  const chips = [];
  if (sum.visible_marks && sum.visible_marks.length) {
    chips.push(`<span class="badge ok">✓ ${esc(sum.visible_marks.join(', '))} (${esc(sum.backend || 'auto')})</span>`);
  } else if (sum.mode === 'quick') {
    chips.push(`<span class="badge">No visible mark · metadata stripped</span>`);
  }
  if (sum.invisible_outcome === 'removed') {
    chips.push(`<span class="badge accent">${esc(sum.pipeline)} scrubbed</span>`);
  } else if (sum.invisible_outcome === 'no-signal') {
    chips.push(`<span class="badge warn">Hidden pass skipped (no metadata signal)</span>`);
  }
  if (sum.auto_tiled) {
    chips.push(`<span class="badge accent">Auto-tiled</span>`);
  }
  if (sum.mode === 'metadata') {
    const n = (sum.metadata_found || []).length;
    chips.push(`<span class="badge ok">${n ? n + ' AI tag(s) stripped' : 'Verified clean'}</span>`);
  }
  if (sum.elapsed_s != null) chips.push(`<span class="badge">${sum.elapsed_s}s</span>`);
  return chips.join(' ');
}

function resetImgItemForRun(it) {
  it.pct = 0;
  it.done = false;
  it.error = false;
  it.cancelled = false;
  it.running = false;
  it.summary = null;
  it.bar.style.width = '0%';
  it.chips.innerHTML = '';
  it.cmpBtn.hidden = true;
  it.copyBtn.hidden = true;
  it.dlBtn.hidden = true;
  it.rerunBtn.hidden = true;
  setImgItem(it, 0, t('ready'), '');
}

function addImageFiles(fl, { autoStart = true, dedupe = false } = {}) {
  const added = [];
  for (const f of fl) {
    if (!isImageFile(f)) continue;
    if (dedupe) {
      const existing = imgItems.find((x) => x.file.name === f.name && x.file.size === f.size && x.file.lastModified === f.lastModified);
      if (existing) {
        if (existing.done || existing.error || existing.cancelled) resetImgItemForRun(existing);
        added.push(existing);
        continue;
      }
    }
    const url = URL.createObjectURL(f);
    const el = document.createElement('div');
    el.className = 'item';
    el.innerHTML =
      `<div class="thumb-box"><img class="thumb" alt="" /></div>` +
      `<div class="mid">` +
        `<div class="nm-row"><span class="nm"></span><span class="sz">${fmtSize(f.size)}</span></div>` +
        `<div class="ibar"><i></i></div>` +
        `<div class="meta-line"><span class="st">${esc(t('ready'))}</span><span class="chips"></span></div>` +
      `</div>` +
      `<div class="acts">` +
        `<button class="ghost xs act-compare" hidden title="${esc(t('compare'))}">${ICO.compare} <span>${esc(t('compare'))}</span></button>` +
        `<button class="ghost xs icon-only act-copy" hidden title="${esc(t('copyBtn'))}">${ICO.copy}</button>` +
        `<button class="ghost xs icon-only act-erase" title="${esc(t('tabErase'))}">${ICO.erase}</button>` +
        `<button class="ghost xs icon-only act-inspect" title="${esc(t('tabInspect'))}">${ICO.inspect}</button>` +
        `<button class="ghost xs icon-only act-dl" hidden title="${esc(t('downloadBtn'))}">${ICO.dl}</button>` +
        `<button class="ghost xs icon-only act-rerun" hidden title="Re-run">${ICO.rerun}</button>` +
        `<button class="danger xs icon-only act-del" title="Remove">×</button>` +
      `</div>`;

    const thumbImg = el.querySelector('.thumb');
    thumbImg.src = url;
    el.querySelector('.nm').textContent = f.name;
    $('list').appendChild(el);

    const it = {
      file: f,
      el,
      url,
      previewFallbackUrl: null,
      bar: el.querySelector('.ibar > i'),
      st: el.querySelector('.st'),
      chips: el.querySelector('.chips'),
      cmpBtn: el.querySelector('.act-compare'),
      copyBtn: el.querySelector('.act-copy'),
      dlBtn: el.querySelector('.act-dl'),
      rerunBtn: el.querySelector('.act-rerun'),
      pct: 0,
      done: false,
      running: false,
      error: false,
      cancelled: false,
      jobId: null,
      es: null,
      outName: null,
      summary: null,
      cleanedMode: null,
    };

    thumbImg.addEventListener('error', async () => {
      if (it.previewFallbackUrl) return;
      try {
        const dec = await decodePreviewFallback(f, 1200);
        it.previewFallbackUrl = dec.url;
        thumbImg.src = dec.url;
      } catch {
        el.querySelector('.thumb-box').innerHTML = ICO.img;
      }
    });

    el.querySelector('.act-del').addEventListener('click', () => removeImgItem(it));
    el.querySelector('.act-inspect').addEventListener('click', () => { switchTab('inspect'); runInspect(f); });
    el.querySelector('.act-erase').addEventListener('click', async () => {
      switchTab('erase');
      if (it.done && it.jobId) {
        await loadUrlIntoErase('/preview/' + it.jobId, it.outName || f.name);
      } else {
        loadEraseImage(f);
      }
    });
    it.cmpBtn.addEventListener('click', () => {
      if (!it.jobId) return;
      const doneList = imgItems.filter((x) => x.done && x.jobId);
      const startIdx = Math.max(0, doneList.indexOf(it));
      openCompareModalBatch(
        doneList.map((x) => ({
          title: x.file.name,
          beforeUrl: x.previewFallbackUrl || x.url,
          afterUrl: '/preview/' + x.jobId,
          dlUrl: '/result/' + x.jobId,
          dlName: x.outName,
          origSize: x.file.size,
          summary: x.summary,
        })),
        startIdx,
      );
    });
    it.copyBtn.addEventListener('click', () => {
      if (it.jobId) copyImageToClipboard('/preview/' + it.jobId);
    });
    it.dlBtn.addEventListener('click', () => {
      if (it.jobId) triggerDownload('/result/' + it.jobId, it.outName);
    });
    it.rerunBtn.addEventListener('click', () => {
      resetImgItemForRun(it);
      startImageQueue();
    });

    imgItems.push(it);
    added.push(it);
  }
  updateImageActionRow();
  if (added.length && autoStart && $('autoCleanChk').checked) {
    startImageQueue();
  }
  return added;
}

wireDrop($('drop'), $('file'), (fl) => addImageFiles(fl));

function removeImgItem(it) {
  if (it.es) { it.es.close(); it.es = null; }
  if (it.running && it.jobId) {
    apiPostForm('/cancel/' + it.jobId, {}).catch(() => {});
  }
  URL.revokeObjectURL(it.url);
  if (it.previewFallbackUrl) URL.revokeObjectURL(it.previewFallbackUrl);
  it.el.remove();
  imgItems = imgItems.filter((x) => x !== it);
  updateOverall();
}

$('clear').addEventListener('click', () => {
  if (imgActiveWorkers > 0) return;
  imgItems.forEach((i) => {
    URL.revokeObjectURL(i.url);
    if (i.previewFallbackUrl) URL.revokeObjectURL(i.previewFallbackUrl);
  });
  imgItems = [];
  $('list').innerHTML = '';
  updateOverall();
});

function processOneImage(it, batchTotal) {
  return new Promise(async (resolve) => {
    it.pct = 0;
    it.done = false;
    it.error = false;
    it.cancelled = false;
    it.running = true;
    it.chips.innerHTML = '';
    const runMode = imgMode;
    setImgItem(it, 2, t('uploading'), 'run');
    updateOverall();

    try {
      const fd = new FormData();
      fd.append('file', it.file);
      fd.append('mode', runMode);
      fd.append('backend', $('backendSel').value);
      fd.append('sensitivity', $('sensSel').value);
      if (runMode === 'deep') {
        fd.append('pipeline', pipeline || $('deepProfSel').value);
        fd.append('device', $('deviceSel').value || 'auto');
        fd.append('force', $('forceChk').checked ? 'true' : 'false');
        fd.append('vendor', $('vendorSel').value);
        fd.append('cpu_offload', $('offloadChk').checked ? 'true' : 'false');
        fd.append('adaptive_polish', $('polishSel').value);
        fd.append('humanize', $('grainInp').value || '0');
        fd.append('unsharp', $('sharpInp').value || '0');
        fd.append('tile', $('tileSel').value || 'auto');
      }
      const { job_id } = await apiPostForm('/clean', fd);
      if (!imgItems.includes(it) || imgStopRequested) {
        apiPostForm('/cancel/' + job_id, {}).catch(() => {});
        it.running = false;
        it.cancelled = true;
        setImgItem(it, null, t('cancelled'), '');
        it.rerunBtn.hidden = false;
        resolve();
        return;
      }
      it.jobId = job_id;
      if (runMode === 'deep' && drawerOpen) pollModels(true);

      const es = new EventSource('/events/' + job_id);
      it.es = es;
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        es.close();
        if (it.es === es) it.es = null;
        it.running = false;
        updateOverall();
        resolve();
      };

      es.onmessage = (e) => {
        if (!imgItems.includes(it)) { finish(); return; }
        const ev = JSON.parse(e.data);
        if (ev.type === 'status') {
          setImgItem(it, ev.percent, ev.message);
          updateOverall();
        } else if (ev.type === 'done') {
          const sum = ev.summary || {};
          it.summary = sum;
          it.cleanedMode = runMode;
          it.outName = sum.out_name || it.file.name.replace(/(\.[^.]+)$/, '_clean$1');
          it.done = true;
          setImgItem(it, 100, t('done'), 'done');
          it.chips.innerHTML = renderSummaryChips(sum);
          it.cmpBtn.hidden = false;
          it.copyBtn.hidden = false;
          it.dlBtn.hidden = false;
          it.rerunBtn.hidden = false;
          if ($('autoDlChk').checked && batchTotal === 1 && imgItems.length === 1) {
            triggerDownload('/result/' + job_id, it.outName);
          }
          finish();
        } else if (ev.type === 'cancelled') {
          it.cancelled = true;
          setImgItem(it, null, t('cancelled'), '');
          it.rerunBtn.hidden = false;
          finish();
        } else if (ev.type === 'error') {
          it.error = true;
          setImgItem(it, null, ev.message || 'Failed', 'err');
          it.rerunBtn.hidden = false;
          finish();
        }
      };
      es.onerror = () => {
        if (!settled) {
          it.error = true;
          setImgItem(it, null, 'Connection lost', 'err');
          it.rerunBtn.hidden = false;
          finish();
        }
      };
    } catch (err) {
      it.running = false;
      it.error = true;
      setImgItem(it, null, String(err.message || err), 'err');
      it.rerunBtn.hidden = false;
      updateOverall();
      resolve();
    }
  });
}

function nextPendingImage() {
  return imgItems.find((i) => !i.done && !i.running && !i.error && !i.cancelled) || null;
}

function startImageQueue() {
  imgStopRequested = false;
  const concurrency = imgMode === 'metadata' ? 4 : imgMode === 'quick' ? 4 : 1;
  const pendingAtStart = imgItems.filter((i) => !i.done && !i.running && !i.error && !i.cancelled).length;
  if (!pendingAtStart) return;

  $('overall').hidden = false;
  updateOverall();

  const spawn = Math.max(0, concurrency - imgActiveWorkers);
  const batchTotal = Math.max(pendingAtStart, imgItems.length);
  for (let w = 0; w < spawn; w++) {
    imgActiveWorkers++;
    (async () => {
      try {
        while (!imgStopRequested) {
          const next = nextPendingImage();
          if (!next) break;
          await processOneImage(next, batchTotal);
        }
      } finally {
        imgActiveWorkers--;
        updateOverall();
        if (imgActiveWorkers === 0) {
          const doneCnt = imgItems.filter((i) => i.done && i.jobId).length;
          if (!imgStopRequested && doneCnt >= 2 && $('autoDlChk').checked) {
            showToast(t('batchTipZip'), 'ok', 4200);
          }
        }
      }
    })();
  }
  updateImageActionRow();
}

$('go').addEventListener('click', () => {
  imgItems.forEach((it) => { if (it.error || it.cancelled) resetImgItemForRun(it); });
  startImageQueue();
});

$('stopBtn').addEventListener('click', () => {
  imgStopRequested = true;
  imgItems.forEach((it) => {
    if (it.running && it.jobId) {
      apiPostForm('/cancel/' + it.jobId, {}).catch(() => {});
    }
  });
  showToast(t('cancelled'), 'warn', 2000);
});

$('recleanModeBtn').addEventListener('click', () => {
  imgItems.forEach((it) => { if (!it.running) resetImgItemForRun(it); });
  startImageQueue();
});

$('zipAllBtn').addEventListener('click', () => {
  const ids = imgItems.filter((i) => i.done && i.jobId).map((i) => i.jobId);
  downloadBatchZip(ids);
});

// ==================== TAB 2: MANUAL ERASE (PRO) ====================
let eraseTool = 'box';
let eraseFileObj = null;
let eraseObjUrl = null;
let eraseNatW = 0;
let eraseNatH = 0;
let eraseOps = [];
let eraseDrawing = false;
let eraseCurOp = null;
let eraseLastRes = null;
let eraseView = 'edit';
let eraseCompareWidget = null;
let eraseZoom = 1;
let erasePanX = 0;
let erasePanY = 0;
let eraseSpaceDown = false;
let erasePanning = false;
let erasePanStart = null;
let eraseRafPending = false;

function setEraseTool(tool) {
  eraseTool = tool;
  $('toolBoxBtn').classList.toggle('active', tool === 'box');
  $('toolBrushBtn').classList.toggle('active', tool === 'brush');
  $('brushSizeField').hidden = tool !== 'brush';
  $('eraseCanvas').classList.toggle('brush-mode', tool === 'brush' && !eraseSpaceDown);
  if (tool !== 'brush') $('brushCursor').hidden = true;
}
$('toolBoxBtn').addEventListener('click', () => setEraseTool('box'));
$('toolBrushBtn').addEventListener('click', () => setEraseTool('brush'));

function updateBrushSizeReadout() {
  const v = Number($('brushSize').value);
  $('brushSizeVal').textContent = v + ' px';
  const cur = $('brushCursor');
  cur.style.width = v + 'px';
  cur.style.height = v + 'px';
}
$('brushSize').addEventListener('input', updateBrushSizeReadout);
updateBrushSizeReadout();

function applyEraseViewport() {
  if (eraseZoom <= 1) { eraseZoom = 1; erasePanX = 0; erasePanY = 0; }
  $('eraseViewport').style.transform = `translate(${erasePanX}px, ${erasePanY}px) scale(${eraseZoom})`;
  $('eraseZoomPct').textContent = Math.round(eraseZoom * 100) + '%';
}

function resetEraseZoom() {
  eraseZoom = 1; erasePanX = 0; erasePanY = 0;
  applyEraseViewport();
}
$('eraseZoomIn').addEventListener('click', () => { eraseZoom = clamp(eraseZoom * 1.25, 1, 6); applyEraseViewport(); });
$('eraseZoomOut').addEventListener('click', () => { eraseZoom = clamp(eraseZoom / 1.25, 1, 6); applyEraseViewport(); });
$('eraseZoomReset').addEventListener('click', resetEraseZoom);
$('eraseZoomFit').addEventListener('click', resetEraseZoom);

function setEraseView(v) {
  eraseView = v;
  const isRes = v === 'result' && !!eraseLastRes;
  $('eraseStage').hidden = isRes;
  $('eraseResultBox').hidden = !isRes;
  $('eraseViewEditBtn').classList.toggle('active', !isRes);
  $('eraseViewResBtn').classList.toggle('active', isRes);
  if (isRes) $('brushCursor').hidden = true;
}
$('eraseViewEditBtn').addEventListener('click', () => setEraseView('edit'));
$('eraseViewResBtn').addEventListener('click', () => setEraseView('result'));

function setupEraseCanvas(w, h) {
  eraseNatW = w;
  eraseNatH = h;
  const c = $('eraseCanvas');
  const scale = Math.min(1, 2048 / Math.max(1, w, h));
  c.width = Math.max(1, Math.round(w * scale));
  c.height = Math.max(1, Math.round(h * scale));
  $('eraseFileInfo').textContent = `${eraseFileObj.name} · ${w} × ${h} px`;
  resetEraseZoom();
  scheduleEraseRedraw();
  updateEraseButtons();
}

function loadEraseImage(file, initialBoxes = null) {
  if (eraseObjUrl) URL.revokeObjectURL(eraseObjUrl);
  if (eraseCompareWidget) { eraseCompareWidget.destroy(); eraseCompareWidget = null; }
  eraseFileObj = file;
  eraseObjUrl = URL.createObjectURL(file);
  eraseOps = Array.isArray(initialBoxes) ? initialBoxes.slice() : [];
  eraseLastRes = null;
  $('eraseViewSwitch').hidden = true;
  setEraseView('edit');
  $('eraseStatus').textContent = '';
  $('eraseDrop').hidden = true;
  $('eraseWorkspace').hidden = false;

  const img = $('eraseImg');
  let triedFallback = false;
  img.onload = () => {
    if (!triedFallback) setupEraseCanvas(img.naturalWidth, img.naturalHeight);
  };
  img.onerror = async () => {
    if (triedFallback) return;
    triedFallback = true;
    try {
      const dec = await decodePreviewFallback(file, 2048);
      if (eraseObjUrl) URL.revokeObjectURL(eraseObjUrl);
      eraseObjUrl = dec.url;
      img.onload = () => setupEraseCanvas(dec.width || img.naturalWidth, dec.height || img.naturalHeight);
      img.src = dec.url;
    } catch {
      showToast('Could not preview this image format', 'err');
    }
  };
  img.src = eraseObjUrl;
}

async function loadUrlIntoErase(url, filename) {
  try {
    const blob = await fetch(url).then((r) => r.blob());
    const nextFile = new File([blob], filename || 'cleaned.png', { type: blob.type || 'image/png' });
    switchTab('erase');
    loadEraseImage(nextFile);
  } catch (err) {
    showToast(String(err.message || err), 'err');
  }
}

wireDrop($('eraseDrop'), $('eraseFile'), (fl) => { if (fl && fl[0]) loadEraseImage(fl[0]); });
$('erasePickOther').addEventListener('click', () => $('eraseFile').click());

function updateEraseButtons() {
  const hasFile = !!eraseFileObj;
  const hasOps = eraseOps.length > 0;
  $('eraseAutoDetectBtn').disabled = !hasFile;
  $('eraseUndoBtn').disabled = !hasOps;
  $('eraseClearBtn').disabled = !hasOps;
  $('eraseRunBtn').disabled = !hasOps || !hasFile;
}

function redrawEraseCanvasNow() {
  eraseRafPending = false;
  const c = $('eraseCanvas');
  if (!c.width || !c.height || !eraseNatW || !eraseNatH) return;
  const ctx = c.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, c.width, c.height);
  const sx = c.width / eraseNatW;
  const sy = c.height / eraseNatH;
  ctx.setTransform(sx, 0, 0, sy, 0, 0);

  const drawOp = (op) => {
    if (op.type === 'box') {
      ctx.fillStyle = 'rgba(239, 68, 68, 0.30)';
      ctx.strokeStyle = 'rgba(239, 68, 68, 0.95)';
      ctx.lineWidth = Math.max(2, Math.round(Math.max(eraseNatW, eraseNatH) / 400));
      ctx.fillRect(op.x, op.y, op.w, op.h);
      ctx.strokeRect(op.x, op.y, op.w, op.h);
    } else if (op.type === 'brush' && op.pts.length) {
      ctx.strokeStyle = 'rgba(239, 68, 68, 0.62)';
      ctx.fillStyle = 'rgba(239, 68, 68, 0.62)';
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.lineWidth = op.r * 2;
      if (op.pts.length === 1) {
        ctx.beginPath();
        ctx.arc(op.pts[0][0], op.pts[0][1], op.r, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.beginPath();
        ctx.moveTo(op.pts[0][0], op.pts[0][1]);
        for (let i = 1; i < op.pts.length; i++) ctx.lineTo(op.pts[i][0], op.pts[i][1]);
        ctx.stroke();
      }
    }
  };
  eraseOps.forEach(drawOp);
  if (eraseCurOp) drawOp(eraseCurOp);
}

function scheduleEraseRedraw() {
  if (eraseRafPending) return;
  eraseRafPending = true;
  requestAnimationFrame(redrawEraseCanvasNow);
}

function canvasNatPoint(e) {
  const c = $('eraseCanvas');
  const rect = c.getBoundingClientRect();
  return [
    clamp(((e.clientX - rect.left) / Math.max(1, rect.width)) * eraseNatW, 0, eraseNatW),
    clamp(((e.clientY - rect.top) / Math.max(1, rect.height)) * eraseNatH, 0, eraseNatH),
  ];
}

const eraseCanvasEl = $('eraseCanvas');
eraseCanvasEl.addEventListener('pointerenter', () => {
  if (eraseTool === 'brush' && !eraseSpaceDown && eraseView === 'edit') $('brushCursor').hidden = false;
});
eraseCanvasEl.addEventListener('pointerleave', () => {
  $('brushCursor').hidden = true;
});

eraseCanvasEl.addEventListener('pointerdown', (e) => {
  if (e.button === 1 || eraseSpaceDown) {
    erasePanning = true;
    erasePanStart = { x: e.clientX, y: e.clientY, px: erasePanX, py: erasePanY };
    eraseCanvasEl.setPointerCapture(e.pointerId);
    return;
  }
  if (e.button !== 0) return;
  eraseCanvasEl.setPointerCapture(e.pointerId);
  eraseDrawing = true;
  const [x, y] = canvasNatPoint(e);
  if (eraseTool === 'box') {
    eraseCurOp = { type: 'box', sx: x, sy: y, x, y, w: 0, h: 0 };
  } else {
    const rect = eraseCanvasEl.getBoundingClientRect();
    const scale = eraseNatW / Math.max(1, rect.width);
    eraseCurOp = { type: 'brush', r: (Number($('brushSize').value) / 2) * scale, pts: [[x, y]] };
  }
  scheduleEraseRedraw();
});

eraseCanvasEl.addEventListener('pointermove', (e) => {
  if (eraseTool === 'brush' && !eraseSpaceDown && eraseView === 'edit') {
    const cur = $('brushCursor');
    cur.hidden = false;
    cur.style.left = e.clientX + 'px';
    cur.style.top = e.clientY + 'px';
  }
  if (erasePanning && erasePanStart) {
    erasePanX = erasePanStart.px + (e.clientX - erasePanStart.x);
    erasePanY = erasePanStart.py + (e.clientY - erasePanStart.y);
    applyEraseViewport();
    return;
  }
  if (!eraseDrawing || !eraseCurOp) return;
  const [x, y] = canvasNatPoint(e);
  if (eraseCurOp.type === 'box') {
    eraseCurOp.x = Math.min(eraseCurOp.sx, x);
    eraseCurOp.y = Math.min(eraseCurOp.sy, y);
    eraseCurOp.w = Math.abs(x - eraseCurOp.sx);
    eraseCurOp.h = Math.abs(y - eraseCurOp.sy);
  } else {
    const last = eraseCurOp.pts[eraseCurOp.pts.length - 1];
    const dist = Math.hypot(x - last[0], y - last[1]);
    if (dist >= 1.5) eraseCurOp.pts.push([x, y]);
  }
  scheduleEraseRedraw();
});

function finishErasePointer() {
  if (erasePanning) {
    erasePanning = false;
    erasePanStart = null;
    return;
  }
  if (!eraseDrawing || !eraseCurOp) return;
  eraseDrawing = false;
  if (eraseCurOp.type === 'box') {
    if (eraseCurOp.w >= 3 && eraseCurOp.h >= 3) eraseOps.push(eraseCurOp);
  } else if (eraseCurOp.pts.length) {
    eraseOps.push(eraseCurOp);
  }
  eraseCurOp = null;
  scheduleEraseRedraw();
  updateEraseButtons();
}
eraseCanvasEl.addEventListener('pointerup', finishErasePointer);
eraseCanvasEl.addEventListener('pointercancel', finishErasePointer);

$('eraseStage').addEventListener('wheel', (e) => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.18 : 1 / 1.18;
  eraseZoom = clamp(eraseZoom * factor, 1, 6);
  applyEraseViewport();
}, { passive: false });

$('eraseUndoBtn').addEventListener('click', () => {
  eraseOps.pop();
  scheduleEraseRedraw();
  updateEraseButtons();
});
$('eraseClearBtn').addEventListener('click', () => {
  eraseOps = [];
  scheduleEraseRedraw();
  updateEraseButtons();
});

$('eraseAutoDetectBtn').addEventListener('click', async () => {
  if (!eraseFileObj) return;
  $('eraseAutoDetectBtn').disabled = true;
  try {
    const fd = new FormData();
    fd.append('file', eraseFileObj);
    fd.append('run_classifier', 'false');
    const d = await apiPostForm('/inspect', fd);
    const boxes = (d.visible_boxes || []).filter((b) => Array.isArray(b.region) && b.region.length === 4);
    if (!boxes.length) {
      showToast(t('autoDetectNone'), 'info');
    } else {
      boxes.forEach((b) => {
        const [x, y, w, h] = b.region;
        eraseOps.push({ type: 'box', x, y, w, h });
      });
      setEraseView('edit');
      scheduleEraseRedraw();
      showToast(t('autoDetectFound', { n: boxes.length }), 'ok');
    }
  } catch (err) {
    showToast(String(err.message || err), 'err');
  } finally {
    updateEraseButtons();
  }
});

async function runManualErase() {
  if (!eraseFileObj || !eraseOps.length) return;
  $('eraseRunBtn').disabled = true;
  $('eraseStatus').className = 'mnow';
  $('eraseStatus').textContent = `Erasing with ${$('eraseBackend').value}…`;
  try {
    const boxes = eraseOps.filter((o) => o.type === 'box').map((o) => [Math.round(o.x), Math.round(o.y), Math.round(o.w), Math.round(o.h)]);
    const strokes = eraseOps
      .filter((o) => o.type === 'brush' && o.pts.length)
      .map((o) => ({ r: Math.round(o.r * 10) / 10, pts: o.pts.map(([x, y]) => [Math.round(x), Math.round(y)]) }));
    const fd = new FormData();
    fd.append('file', eraseFileObj);
    fd.append('boxes', JSON.stringify(boxes));
    fd.append('strokes', JSON.stringify(strokes));
    fd.append('backend', $('eraseBackend').value);
    fd.append('strip_metadata', $('eraseMetaChk').checked ? 'true' : 'false');
    const data = await apiPostForm('/erase', fd);
    eraseLastRes = data;
    $('eraseStatus').className = 'mnow ok';
    $('eraseStatus').textContent =
      `✓ Erased with ${data.backend} in ${data.elapsed_s}s` +
      (data.metadata_stripped ? ' · AI metadata stripped' : '') +
      ` · ${fmtSize(data.size_bytes)}`;
    $('eraseViewSwitch').hidden = false;
    setEraseView('result');
    if (eraseCompareWidget) eraseCompareWidget.destroy();
    eraseCompareWidget = buildCompareWidget($('eraseCompareMount'), eraseObjUrl, data.preview_url, { mode: 'split' });
  } catch (err) {
    $('eraseStatus').className = 'mnow err';
    $('eraseStatus').textContent = String(err.message || err);
    showToast(String(err.message || err), 'err');
  } finally {
    updateEraseButtons();
  }
}

$('eraseRunBtn').addEventListener('click', runManualErase);
$('eraseDlBtn').addEventListener('click', () => {
  if (eraseLastRes) triggerDownload(eraseLastRes.download_url, eraseLastRes.out_name);
});
$('eraseCopyBtn').addEventListener('click', () => {
  if (eraseLastRes) copyImageToClipboard(eraseLastRes.preview_url);
});
$('eraseChainBtn').addEventListener('click', async () => {
  if (!eraseLastRes) return;
  await loadUrlIntoErase(eraseLastRes.preview_url, eraseLastRes.out_name);
});

// ==================== TAB 3: INSPECT & AI DETECT ====================
let lastInspectedFile = null;
let inspectSeq = 0;
let inspectAbortCtrl = null;
let inspectPreviewUrl = null;
let inspectPreviewDecoded = false;
let inspectPreviewFallbackPromise = null;

function ensureInspectFallback(file, seq) {
  if (inspectPreviewDecoded) return Promise.resolve(inspectPreviewUrl);
  if (!inspectPreviewFallbackPromise) {
    inspectPreviewFallbackPromise = decodePreviewFallback(file, 1400)
      .then((dec) => {
        if (seq !== inspectSeq) {
          URL.revokeObjectURL(dec.url);
          return null;
        }
        if (inspectPreviewUrl) URL.revokeObjectURL(inspectPreviewUrl);
        inspectPreviewUrl = dec.url;
        inspectPreviewDecoded = true;
        const liveImg = $('inspectResultImg') || $('inspectPreviewImg');
        if (liveImg) liveImg.src = dec.url;
        return dec.url;
      })
      .catch(() => null);
  }
  return inspectPreviewFallbackPromise;
}

async function runInspect(file) {
  const mySeq = ++inspectSeq;
  if (inspectAbortCtrl) inspectAbortCtrl.abort();
  inspectAbortCtrl = new AbortController();
  lastInspectedFile = file;

  if (inspectPreviewUrl) { URL.revokeObjectURL(inspectPreviewUrl); inspectPreviewUrl = null; }
  inspectPreviewDecoded = false;
  inspectPreviewFallbackPromise = null;
  const isVid = isVideoFile(file);
  if (!isVid) inspectPreviewUrl = URL.createObjectURL(file);

  $('inspectOut').hidden = false;
  if (!isVid) {
    $('inspectOut').innerHTML =
      `<div class="inspect-top-grid">` +
        `<div class="card inspect-preview-card">` +
          `<div class="inspect-img-wrap"><img id="inspectPreviewImg" src="${inspectPreviewUrl}" alt="" /><div class="scan-shimmer"></div></div>` +
          `<div class="note flush" style="text-align:center;">${esc(file.name)} · ${fmtSize(file.size)}</div>` +
        `</div>` +
        `<div class="card"><div class="kpi-title">Scanning…</div><p class="note flush">Running single-decode provenance, visible mark detectors &amp; Source Classify v8…</p></div>` +
      `</div>`;
    const pImg = $('inspectPreviewImg');
    pImg.addEventListener('error', () => { ensureInspectFallback(file, mySeq); }, { once: true });
  } else {
    $('inspectOut').innerHTML = `<div class="card mt-sm"><div class="kpi-title">Scanning video…</div><p class="note flush">Inspecting ${esc(file.name)} (${fmtSize(file.size)})…</p></div>`;
  }

  try {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('run_classifier', 'true');
    const d = await apiPostForm('/inspect', fd, inspectAbortCtrl.signal);
    if (mySeq !== inspectSeq) return;
    renderInspectResult(d, file, mySeq);
  } catch (err) {
    if (err && err.name === 'AbortError') return;
    if (mySeq !== inspectSeq) return;
    $('inspectOut').hidden = false;
    $('inspectOut').innerHTML = `<div class="card mt-sm" style="color:var(--err);">Error: ${esc(err.message || err)}</div>`;
  }
}

wireDrop($('inspectDrop'), $('inspectFile'), (fl) => { if (fl && fl[0]) runInspect(fl[0]); });

function renderInspectResult(d, file, mySeq = inspectSeq) {
  $('inspectOut').hidden = false;
  if (d.kind === 'video') {
    const marks = d.visible_marks && d.visible_marks.length ? d.visible_marks.join(', ') : (d.visible_mark || 'None detected');
    const metaKeys = Object.keys(d.metadata_markers || {});
    $('inspectOut').innerHTML =
      `<div class="verdict-banner ${d.is_ai_generated ? 'ai' : 'clean'}">` +
        `<div class="verdict-left">` +
          `<div class="verdict-title">${esc(d.platform || 'Video Analysis')} <span class="badge ${d.is_ai_generated ? 'warn' : 'ok'}">${d.is_ai_generated ? 'AI Provenance' : 'No local metadata'}</span></div>` +
          `<div class="verdict-reason">${esc(d.recommended_recipe || 'Use Video Clean to remove visible marks and strip metadata.')}</div>` +
        `</div>` +
        `<button id="sendVidBtn" class="sm" type="button">${ICO.play} <span>Send to Video Clean</span></button>` +
      `</div>` +
      `<div class="card mt-sm">` +
        `<div class="kv-list">` +
          `<div class="kv"><span>File</span><span>${esc(d.filename)} (${fmtSize(d.size_bytes)})</span></div>` +
          `<div class="kv"><span>Visible marks</span><span>${esc(marks)} (${d.visible_detected_frames}/${d.total_frames || '?'} frames)</span></div>` +
          `<div class="kv"><span>AI metadata tags</span><span>${metaKeys.length ? esc(metaKeys.join(', ')) : 'None'}</span></div>` +
          `<div class="kv"><span>Invisible hints</span><span>${(d.invisible_watermark_hints || []).length ? esc(d.invisible_watermark_hints.join('; ')) : 'None'}</span></div>` +
        `</div>` +
      `</div>`;
    $('sendVidBtn').addEventListener('click', () => {
      switchTab('video');
      if (file) addVideoFiles([file]);
    });
    return;
  }

  const p = d.provenance || {};
  const sc = d.source_classify;
  const boxes = d.visible_boxes || [];
  const metaEntries = Object.entries(d.ai_metadata || {});
  const rec = d.recommendation || {};
  const dims = Array.isArray(d.dimensions) && d.dimensions.length === 2 ? d.dimensions : null;

  const isAiVerdict = Boolean(p.is_ai_generated || (sc && sc.synthetic_detected) || boxes.length || metaEntries.length);
  const verdictHeadline = p.platform
    ? p.platform
    : sc && sc.synthetic_detected
      ? `AI-Generated (${sc.label !== 'unknown' ? sc.label : 'Synthetic'})`
      : boxes.length
        ? `Visible Mark: ${boxes.map((b) => b.label).join(', ')}`
        : 'No Local AI Signals Detected';

  const recLabel = rec.mode === 'deep' ? t('modeDeep') : t('modeQuick');

  const svgBoxes = boxes
    .map((b, idx) => {
      if (!Array.isArray(b.region) || b.region.length !== 4) return '';
      const [x, y, w, h] = b.region;
      return `<rect class="inspect-box-rect" data-box-idx="${idx}" x="${x}" y="${y}" width="${w}" height="${h}" rx="3"><title>${esc(b.label)} (${Math.round(b.confidence * 100)}%)</title></rect>`;
    })
    .join('');

  const svgOverlay = dims && svgBoxes
    ? `<svg class="inspect-svg" viewBox="0 0 ${dims[0]} ${dims[1]}" preserveAspectRatio="xMidYMid meet">${svgBoxes}</svg>`
    : '';

  let scHtml = `<div class="note flush">Source Classify v8 unavailable.</div>`;
  if (sc && sc.error) {
    scHtml = `<div class="mnow err">${esc(sc.error)}</div>`;
  } else if (sc) {
    const probPct = Math.round((sc.synthetic_probability || 0) * 100);
    const isSyn = !!sc.synthetic_detected;
    scHtml =
      `<div class="big-val">` +
        `<span class="badge ${isSyn ? 'warn' : 'ok'}" style="font-size:0.78rem;padding:0.25rem 0.625rem;">${isSyn ? 'Synthetic / AI Detected' : 'Likely Real / Unconfirmed'}</span>` +
        `<span>${probPct}%</span>` +
      `</div>` +
      `<div class="bar" style="margin:0.375rem 0 0.625rem;"><i style="width:${probPct}%;background:${isSyn ? 'var(--warn)' : 'var(--ok)'};"></i></div>` +
      `<div class="kv-list">` +
        `<div class="kv"><span>Provider Family</span><span><b>${esc(sc.label)}</b></span></div>` +
        `<div class="kv"><span>Model Version</span><span>${esc(sc.version_subfamily || '—')}</span></div>` +
        `<div class="kv"><span>Confidence</span><span>${Math.round((sc.confidence || 0) * 100)}% (${esc(sc.reason)})</span></div>` +
      `</div>`;
  }

  const visHtml = boxes.length
    ? boxes
        .map(
          (b, idx) =>
            `<div class="kv" data-mark-idx="${idx}"><span>${esc(b.label)}</span><span>${Math.round(b.confidence * 100)}% · ${esc(b.location)}</span></div>`,
        )
        .join('')
    : `<div class="kv"><span>Visible marks</span><span>None detected</span></div>`;

  const sigHtml = (p.signals || []).length
    ? p.signals.map((s) => `<div class="kv"><span>${esc(s.name)}</span><span>${esc(s.detail)}</span></div>`).join('')
    : `<div class="kv"><span>Provenance signals</span><span>None</span></div>`;

  const metaHtml = metaEntries.length
    ? metaEntries.map(([k, v]) => `<div class="kv"><span>${esc(k)}</span><span>${esc(String(v).slice(0, 140))}</span></div>`).join('')
    : `<div class="kv"><span>AI Metadata Tags</span><span>None</span></div>`;

  $('inspectOut').innerHTML =
    `<div class="verdict-banner ${isAiVerdict ? 'ai' : 'clean'}">` +
      `<div class="verdict-left">` +
        `<div class="verdict-title">${esc(verdictHeadline)} <span class="badge ${isAiVerdict ? 'warn' : 'ok'}">${p.is_ai_generated ? 'Provenance: ' + esc(p.confidence) : (isAiVerdict ? 'Detected' : 'Unconfirmed')}</span></div>` +
        `<div class="verdict-reason">${esc(rec.reason || '')}</div>` +
      `</div>` +
      `<div class="inline-row">` +
        `<button id="cleanNowBtn" class="sm" type="button">✨ ${esc(t('cleanNow'))} (${esc(recLabel)})</button>` +
        `<button id="sendEraseFromInspect" class="ghost sm" type="button">${ICO.erase} <span>${esc(t('tabErase'))}</span></button>` +
      `</div>` +
    `</div>` +
    `<div class="inspect-top-grid">` +
      `<div class="card inspect-preview-card">` +
        `<div class="inspect-img-wrap" id="inspectImgWrap">` +
          `<img id="inspectResultImg" src="${inspectPreviewUrl || ''}" alt="" />` +
          svgOverlay +
        `</div>` +
        `<div class="note flush" style="text-align:center;">${esc(d.filename)} · ${fmtSize(d.size_bytes)}${dims ? ` · ${dims[0]}×${dims[1]}` : ''}</div>` +
      `</div>` +
      `<div class="inspect-right-col">` +
        `<div class="card"><div class="kpi-title">Source Classify v8 (Pixels Only)</div>${scHtml}</div>` +
        `<div class="card"><div class="kpi-title">Detected Visible Marks</div><div class="kv-list">${visHtml}</div></div>` +
        `<div class="card">` +
          `<details class="studio-details" style="border-top:0;padding-top:0;">` +
            `<summary class="studio-summary">${esc(t('techDetails'))} (${(p.signals || []).length + metaEntries.length})</summary>` +
            `<div class="kv-list mt-sm">${sigHtml}${metaHtml}</div>` +
          `</details>` +
        `</div>` +
      `</div>` +
    `</div>`;

  const resImg = $('inspectResultImg');
  if (resImg && file && !inspectPreviewDecoded) {
    resImg.addEventListener('error', () => { ensureInspectFallback(file, mySeq); }, { once: true });
  }

  const outEl = $('inspectOut');
  outEl.querySelectorAll('[data-mark-idx]').forEach((row) => {
    const idx = row.dataset.markIdx;
    const rect = outEl.querySelector(`[data-box-idx="${idx}"]`);
    if (!rect) return;
    row.addEventListener('mouseenter', () => { row.classList.add('hi'); rect.classList.add('hi'); });
    row.addEventListener('mouseleave', () => { row.classList.remove('hi'); rect.classList.remove('hi'); });
    rect.addEventListener('mouseenter', () => { row.classList.add('hi'); rect.classList.add('hi'); });
    rect.addEventListener('mouseleave', () => { row.classList.remove('hi'); rect.classList.remove('hi'); });
  });

  $('cleanNowBtn').addEventListener('click', () => {
    switchTab('image');
    imgMode = rec.mode === 'deep' ? 'deep' : 'quick';
    document.querySelectorAll('#imgModes .mode').forEach((x) => x.classList.toggle('active', x.dataset.mode === imgMode));
    if (rec.pipeline) {
      pipeline = rec.pipeline;
      $('deepProfSel').value = rec.pipeline;
    }
    $('vendorSel').value = rec.vendor || '';
    updateImageModeUI();
    if (file) {
      addImageFiles([file], { autoStart: false, dedupe: true });
      startImageQueue();
    }
  });

  $('sendEraseFromInspect').addEventListener('click', () => {
    switchTab('erase');
    if (file) {
      const preBoxes = boxes
        .filter((b) => Array.isArray(b.region) && b.region.length === 4)
        .map((b) => ({ type: 'box', x: b.region[0], y: b.region[1], w: b.region[2], h: b.region[3] }));
      loadEraseImage(file, preBoxes);
    }
  });
}

// ==================== TAB 4: VIDEO CLEAN ====================
let vidMode = 'quick';
let vidItems = [];
let vidRunning = false;
let vidStopRequested = false;

function updateVidOptSummary() {
  const markTxt = $('vidMarkSel').options[$('vidMarkSel').selectedIndex]?.text || 'Auto';
  const beTxt = ($('vidBackendSel').options[$('vidBackendSel').selectedIndex]?.text || 'MI-GAN').split('·')[0].trim();
  const invTxt = $('vidInvProf').value;
  $('vidOptSummary').textContent =
    vidMode === 'deep' ? `${markTxt} · ${beTxt} · ${invTxt}` : `${markTxt} · ${beTxt}`;
}

function updateVideoModeUI() {
  const isMeta = vidMode === 'metadata';
  const isDeep = vidMode === 'deep';
  $('vidOptFooter').hidden = isMeta;
  if (isMeta) {
    $('vidOptPanel').hidden = true;
    $('vidOptToggleBtn').setAttribute('aria-expanded', 'false');
    $('vidOptCaret').textContent = '▾';
  }
  $('vidMarkField').hidden = isMeta;
  $('vidBackendField').hidden = isMeta;
  $('vidTempField').hidden = isMeta;
  $('vidInvField').hidden = !isDeep;
  updateVidOptSummary();
}

document.querySelectorAll('#vidModes .mode').forEach((el) =>
  el.addEventListener('click', () => {
    document.querySelectorAll('#vidModes .mode').forEach((x) => x.classList.remove('active'));
    el.classList.add('active');
    vidMode = el.dataset.vmode;
    updateVideoModeUI();
  }),
);
$('vidOptToggleBtn').addEventListener('click', () => {
  const open = $('vidOptPanel').hidden;
  $('vidOptPanel').hidden = !open;
  $('vidOptToggleBtn').setAttribute('aria-expanded', open ? 'true' : 'false');
  $('vidOptCaret').textContent = open ? '▴' : '▾';
});
['vidMarkSel', 'vidBackendSel', 'vidInvProf'].forEach((id) => $(id).addEventListener('change', updateVidOptSummary));
updateVideoModeUI();

function captureVideoThumb(file, thumbBox, metaEl) {
  const tmpUrl = URL.createObjectURL(file);
  const v = document.createElement('video');
  v.muted = true;
  v.preload = 'metadata';
  v.playsInline = true;
  const cleanup = () => { v.removeAttribute('src'); v.load(); URL.revokeObjectURL(tmpUrl); };
  v.addEventListener('loadedmetadata', () => {
    const dur = fmtDuration(v.duration);
    const dims = v.videoWidth && v.videoHeight ? `${v.videoWidth}×${v.videoHeight}` : '';
    const extra = [dims, dur].filter(Boolean).join(' · ');
    if (extra && metaEl) metaEl.textContent = `${fmtSize(file.size)} · ${extra}`;
    if (dur) {
      const b = document.createElement('span');
      b.className = 'thumb-badge';
      b.textContent = dur;
      thumbBox.appendChild(b);
    }
    try { v.currentTime = Math.min(0.5, (v.duration || 0) / 3); } catch { cleanup(); }
  });
  v.addEventListener('seeked', () => {
    try {
      const c = document.createElement('canvas');
      const w = 120;
      const h = Math.max(68, Math.round((v.videoHeight / Math.max(1, v.videoWidth)) * w));
      c.width = w; c.height = h;
      c.getContext('2d').drawImage(v, 0, 0, w, h);
      const img = document.createElement('img');
      img.className = 'thumb';
      img.src = c.toDataURL('image/jpeg', 0.78);
      const badge = thumbBox.querySelector('.thumb-badge');
      thumbBox.innerHTML = '';
      thumbBox.appendChild(img);
      if (badge) thumbBox.appendChild(badge);
    } catch {}
    cleanup();
  });
  v.addEventListener('error', cleanup);
  v.src = tmpUrl;
}

function updateVideoActionRow() {
  const has = vidItems.length > 0;
  $('vidActionRow').hidden = !has;
  if (!has) return;
  const doneItems = vidItems.filter((i) => i.done && i.jobId);
  const pending = vidItems.filter((i) => !i.done && !i.running).length;
  $('vidGo').hidden = vidRunning;
  $('vidGo').disabled = pending === 0;
  $('vidStopBtn').hidden = !vidRunning;
  $('vidClear').disabled = vidRunning;
  $('vidZipAllBtn').hidden = doneItems.length < 2;
}

function addVideoFiles(fl) {
  for (const f of fl) {
    if (!isVideoFile(f)) continue;
    const el = document.createElement('div');
    el.className = 'item';
    el.innerHTML =
      `<div class="thumb-box">${ICO.film}</div>` +
      `<div class="mid">` +
        `<div class="nm-row"><span class="nm"></span><span class="sz">${fmtSize(f.size)}</span></div>` +
        `<div class="ibar"><i></i></div>` +
        `<div class="meta-line"><span class="st">${esc(t('ready'))}</span><span class="chips"></span></div>` +
      `</div>` +
      `<div class="acts">` +
        `<button class="ghost xs act-vprev" hidden>${ICO.play} <span>${esc(t('preview'))}</span></button>` +
        `<button class="ghost xs icon-only act-vinspect" title="${esc(t('tabInspect'))}">${ICO.inspect}</button>` +
        `<button class="ghost xs icon-only act-vdl" hidden title="${esc(t('downloadBtn'))}">${ICO.dl}</button>` +
        `<button class="ghost xs icon-only act-vrerun" hidden title="Re-run">${ICO.rerun}</button>` +
        `<button class="danger xs icon-only act-vdel" title="Remove">×</button>` +
      `</div>`;
    el.querySelector('.nm').textContent = f.name;
    $('vidList').appendChild(el);

    const it = {
      file: f,
      el,
      ibarWrap: el.querySelector('.ibar'),
      bar: el.querySelector('.ibar > i'),
      st: el.querySelector('.st'),
      chips: el.querySelector('.chips'),
      prevBtn: el.querySelector('.act-vprev'),
      dlBtn: el.querySelector('.act-vdl'),
      rerunBtn: el.querySelector('.act-vrerun'),
      done: false,
      running: false,
      error: false,
      cancelled: false,
      jobId: null,
      es: null,
      timer: null,
      outName: null,
    };

    captureVideoThumb(f, el.querySelector('.thumb-box'), el.querySelector('.sz'));

    el.querySelector('.act-vinspect').addEventListener('click', () => { switchTab('inspect'); runInspect(f); });
    el.querySelector('.act-vdel').addEventListener('click', () => {
      if (it.es) { it.es.close(); it.es = null; }
      clearInterval(it.timer);
      if (it.running && it.jobId) apiPostForm('/cancel/' + it.jobId, {}).catch(() => {});
      el.remove();
      vidItems = vidItems.filter((x) => x !== it);
      updateVideoActionRow();
    });
    it.prevBtn.addEventListener('click', () => {
      if (it.jobId) openVideoPreview(it.outName || f.name, '/preview/' + it.jobId, '/result/' + it.jobId, it.outName);
    });
    it.dlBtn.addEventListener('click', () => {
      if (it.jobId) triggerDownload('/result/' + it.jobId, it.outName);
    });
    it.rerunBtn.addEventListener('click', () => {
      it.done = false; it.error = false; it.cancelled = false;
      it.prevBtn.hidden = true; it.dlBtn.hidden = true; it.rerunBtn.hidden = true;
      it.chips.innerHTML = ''; it.bar.style.width = '0%';
      it.el.className = 'item'; it.st.textContent = t('ready');
      runVideoQueue();
    });
    vidItems.push(it);
  }
  updateVideoActionRow();
}

wireDrop($('vidDrop'), $('vidFile'), addVideoFiles);

$('vidClear').addEventListener('click', () => {
  if (vidRunning) return;
  vidItems = [];
  $('vidList').innerHTML = '';
  updateVideoActionRow();
});

function renderVideoChips(sum) {
  const chips = [];
  if (sum.visible_marks && sum.visible_marks.length) {
    chips.push(`<span class="badge ok">✓ ${esc(sum.visible_marks.join(', '))} (${sum.visible_removed_frames}/${sum.total_frames || '?'} frames)</span>`);
  } else if (sum.mode === 'quick') {
    chips.push(`<span class="badge">No visible mark found</span>`);
  }
  if (sum.detected_metadata && sum.detected_metadata.length) {
    chips.push(`<span class="badge ok">${sum.detected_metadata.length} metadata tag(s) stripped</span>`);
  } else if (sum.mode === 'metadata') {
    chips.push(`<span class="badge ok">Verified clean</span>`);
  }
  if (sum.invisible_removed) {
    chips.push(`<span class="badge accent">${esc(sum.invisible_profile || 'regen')}</span>`);
  }
  if (sum.elapsed_s != null) chips.push(`<span class="badge">${sum.elapsed_s}s</span>`);
  return chips.join(' ');
}

function processOneVideo(it, batchTotal) {
  return new Promise(async (resolve) => {
    it.done = false; it.error = false; it.cancelled = false; it.running = true;
    it.el.className = 'item run';
    it.ibarWrap.classList.add('indet');
    it.chips.innerHTML = '';
    const t0 = Date.now();
    let baseMsg = t('uploading');
    it.st.textContent = baseMsg;
    it.timer = setInterval(() => {
      const sec = Math.floor((Date.now() - t0) / 1000);
      it.st.textContent = `${baseMsg} (${sec}s)`;
    }, 1000);

    const stopTimer = () => {
      clearInterval(it.timer);
      it.timer = null;
      it.ibarWrap.classList.remove('indet');
    };

    try {
      const fd = new FormData();
      fd.append('file', it.file);
      fd.append('mode', vidMode);
      fd.append('mark', $('vidMarkSel').value);
      fd.append('backend', $('vidBackendSel').value);
      fd.append('invisible_profile', $('vidInvProf').value);
      fd.append('temporal_consistency', $('vidTempChk').checked ? 'true' : 'false');
      const { job_id } = await apiPostForm('/video/clean', fd);
      if (!vidItems.includes(it) || vidStopRequested) {
        apiPostForm('/cancel/' + job_id, {}).catch(() => {});
        stopTimer();
        it.running = false; it.cancelled = true;
        it.el.className = 'item'; it.st.textContent = t('cancelled'); it.rerunBtn.hidden = false;
        resolve();
        return;
      }
      it.jobId = job_id;
      const es = new EventSource('/events/' + job_id);
      it.es = es;
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        es.close();
        if (it.es === es) it.es = null;
        stopTimer();
        it.running = false;
        updateVideoActionRow();
        resolve();
      };
      es.onmessage = (e) => {
        if (!vidItems.includes(it)) { finish(); return; }
        const ev = JSON.parse(e.data);
        if (ev.type === 'status') {
          baseMsg = ev.message || baseMsg;
          const sec = Math.floor((Date.now() - t0) / 1000);
          it.st.textContent = `${baseMsg} (${sec}s)`;
        } else if (ev.type === 'done') {
          const sum = ev.summary || {};
          it.done = true;
          it.outName = sum.out_name || it.file.name.replace(/(\.[^.]+)$/, '_clean$1');
          it.el.className = 'item done';
          it.bar.style.width = '100%';
          it.st.textContent = t('done');
          it.chips.innerHTML = renderVideoChips(sum);
          it.prevBtn.hidden = false;
          it.dlBtn.hidden = false;
          it.rerunBtn.hidden = false;
          if ($('vidAutoDlChk').checked && batchTotal === 1 && vidItems.length === 1) {
            triggerDownload('/result/' + job_id, it.outName);
          }
          finish();
        } else if (ev.type === 'cancelled') {
          it.cancelled = true;
          it.el.className = 'item';
          it.st.textContent = t('cancelled');
          it.rerunBtn.hidden = false;
          finish();
        } else if (ev.type === 'error') {
          it.error = true;
          it.el.className = 'item err';
          it.st.textContent = ev.message || 'Failed';
          it.rerunBtn.hidden = false;
          finish();
        }
      };
      es.onerror = () => {
        if (!settled) {
          it.error = true;
          it.el.className = 'item err';
          it.st.textContent = 'Connection lost';
          it.rerunBtn.hidden = false;
          finish();
        }
      };
    } catch (err) {
      stopTimer();
      it.running = false; it.error = true;
      it.el.className = 'item err';
      it.st.textContent = String(err.message || err);
      it.rerunBtn.hidden = false;
      updateVideoActionRow();
      resolve();
    }
  });
}

async function runVideoQueue() {
  if (vidRunning) return;
  vidRunning = true;
  vidStopRequested = false;
  updateVideoActionRow();
  const batchTotal = vidItems.filter((i) => !i.done).length;
  try {
    while (!vidStopRequested) {
      const next = vidItems.find((i) => !i.done && !i.running && !i.error && !i.cancelled);
      if (!next) break;
      await processOneVideo(next, batchTotal);
    }
  } finally {
    vidRunning = false;
    updateVideoActionRow();
  }
}

$('vidGo').addEventListener('click', () => {
  vidItems.forEach((it) => { if (it.error || it.cancelled) { it.error = false; it.cancelled = false; } });
  runVideoQueue();
});
$('vidStopBtn').addEventListener('click', () => {
  vidStopRequested = true;
  vidItems.forEach((it) => { if (it.running && it.jobId) apiPostForm('/cancel/' + it.jobId, {}).catch(() => {}); });
  showToast(t('cancelled'), 'warn', 2000);
});
$('vidZipAllBtn').addEventListener('click', () => {
  const ids = vidItems.filter((i) => i.done && i.jobId).map((i) => i.jobId);
  downloadBatchZip(ids);
});

// ==================== GLOBAL WINDOW DRAG-DROP & CLIPBOARD PASTE ==============
let dragDepth = 0;
function hasFilePayload(e) {
  return e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
}

window.addEventListener('dragenter', (e) => {
  if (!hasFilePayload(e)) return;
  e.preventDefault();
  dragDepth++;
  $('globalDropOverlay').hidden = false;
});
window.addEventListener('dragover', (e) => {
  if (!hasFilePayload(e)) return;
  e.preventDefault();
});
window.addEventListener('dragleave', (e) => {
  if (!hasFilePayload(e)) return;
  e.preventDefault();
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) $('globalDropOverlay').hidden = true;
});
window.addEventListener('drop', (e) => {
  e.preventDefault();
  dragDepth = 0;
  $('globalDropOverlay').hidden = true;
  const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
  if (!files.length) return;

  const videos = files.filter(isVideoFile);
  const images = files.filter((f) => !isVideoFile(f) && isImageFile(f));

  if (videos.length && !images.length) {
    if (activeTab === 'inspect') {
      runInspect(videos[0]);
    } else {
      switchTab('video');
      addVideoFiles(videos);
    }
    return;
  }
  if (images.length) {
    if (activeTab === 'erase') {
      loadEraseImage(images[0]);
    } else if (activeTab === 'inspect') {
      runInspect(images[0]);
    } else {
      switchTab('image');
      addImageFiles(images);
    }
  }
  if (videos.length) {
    addVideoFiles(videos);
  }
});

// Global Ctrl+V / Cmd+V Clipboard Paste
window.addEventListener('paste', (e) => {
  const tag = (document.activeElement && document.activeElement.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') return;
  const items = Array.from((e.clipboardData && e.clipboardData.items) || []);
  const imgItem = items.find((i) => i.kind === 'file' && i.type.startsWith('image/'));
  if (!imgItem) return;
  const blob = imgItem.getAsFile();
  if (!blob) return;
  e.preventDefault();
  const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
  const file = new File([blob], `pasted_${Date.now()}.${ext}`, { type: blob.type || 'image/png' });
  showToast(t('pastedToast'), 'info', 2000);
  if (activeTab === 'erase') {
    loadEraseImage(file);
  } else if (activeTab === 'inspect') {
    runInspect(file);
  } else {
    switchTab('image');
    addImageFiles([file]);
  }
});

// ==================== GLOBAL KEYBOARD SHORTCUTS (IME-Safe) ===================
function isTypingElement(el) {
  if (!el) return false;
  const tag = (el.tagName || '').toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable;
}

document.addEventListener('keydown', (e) => {
  // Compare modal shortcuts (Escape is handled natively by <dialog>)
  if ($('compareModal').open) {
    if (e.key === 'ArrowLeft' && cmpIdx > 0) { e.preventDefault(); cmpIdx--; renderCompareModal(); return; }
    if (e.key === 'ArrowRight' && cmpIdx < cmpList.length - 1) { e.preventDefault(); cmpIdx++; renderCompareModal(); return; }
    if (e.code === 'Space') {
      e.preventDefault();
      if (cmpWidget) cmpWidget.setPeek(true);
      return;
    }
    return;
  }

  if ($('vidPreviewModal').open) return;

  if ($('kbdModal').open) {
    if (e.key === '?') { e.preventDefault(); toggleKbdModal(false); }
    return;
  }

  // Fallback Escape handling only when native popover is unsupported
  if (drawerOpen && !supportsPopover() && e.key === 'Escape') {
    e.preventDefault();
    setModelDrawer(false);
    return;
  }

  if (isTypingElement(document.activeElement)) return;

  if (e.key === '?') { e.preventDefault(); toggleKbdModal(true); return; }

  // Tab switch 1-4
  if (!e.ctrlKey && !e.metaKey && !e.altKey) {
    if (e.key === '1') { switchTab('image', { focusPanel: true }); return; }
    if (e.key === '2') { switchTab('erase', { focusPanel: true }); return; }
    if (e.key === '3') { switchTab('inspect', { focusPanel: true }); return; }
    if (e.key === '4') { switchTab('video', { focusPanel: true }); return; }
  }

  // Manual Erase shortcuts
  if (activeTab === 'erase' && eraseFileObj && eraseView === 'edit') {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      if (eraseOps.length) { eraseOps.pop(); scheduleEraseRedraw(); updateEraseButtons(); }
      return;
    }
    if (e.key.toLowerCase() === 'r') { setEraseTool('box'); return; }
    if (e.key.toLowerCase() === 'b') { setEraseTool('brush'); return; }
    if (e.key === '[') {
      $('brushSize').value = String(clamp(Number($('brushSize').value) - 6, 6, 120));
      updateBrushSizeReadout();
      return;
    }
    if (e.key === ']') {
      $('brushSize').value = String(clamp(Number($('brushSize').value) + 6, 6, 120));
      updateBrushSizeReadout();
      return;
    }
    if (e.key === 'Enter' && eraseOps.length && !$('eraseRunBtn').disabled) {
      if (isImeEvent(e)) return;
      e.preventDefault();
      runManualErase();
      return;
    }
    if (e.code === 'Space' && !eraseSpaceDown) {
      e.preventDefault();
      eraseSpaceDown = true;
      eraseCanvasEl.classList.add('panning');
      eraseCanvasEl.classList.remove('brush-mode');
      $('brushCursor').hidden = true;
    }
  }
});

document.addEventListener('keyup', (e) => {
  if (e.code === 'Space') {
    if ($('compareModal').open && cmpWidget) {
      cmpWidget.setPeek(false);
    }
    if (eraseSpaceDown) {
      eraseSpaceDown = false;
      eraseCanvasEl.classList.remove('panning');
      eraseCanvasEl.classList.toggle('brush-mode', eraseTool === 'brush');
    }
  }
});

// Initialize language labels
applyLanguage(curLang);
