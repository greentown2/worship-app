"""Render HTML worship slides to images, then drop them into a 16:9 PPTX.

Native python-pptx boxes cannot match the HTML flex layout. Capturing the same
slide markup the browser uses keeps type, spacing, and design identical.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from html_presentation import TEMPLATE_PATH, build_presentation_slides
from models import WorshipData

_CAPTURE_VERSION = "2026-09-18-html-capture-cloud-v1"

ROOT = Path(__file__).resolve().parent
SLIDE_W_PX = 1920
SLIDE_H_PX = 1080
SLIDE_W_IN = Inches(13.333)
SLIDE_H_IN = Inches(7.5)

_CAPTURE_CSS = """
html, body {
  margin: 0 !important;
  padding: 0 !important;
  width: 1920px !important;
  background: #0a0f1d !important;
  overflow: hidden !important;
  font-family: Pretendard, "Noto Sans KR", NanumGothic, "Malgun Gothic", sans-serif;
  color: #f8fafc;
  position: relative !important;
  inset: auto !important;
  height: auto !important;
  font-size: 16px;
}
.present-exit-btn, .present-fs-btn, .present-nav-hint, header, .dashboard-layout, #mobile-present-gate {
  display: none !important;
}
.ppt-page {
  width: 1920px;
  height: 1080px;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: radial-gradient(circle at center, #1a233a 0%, #0a0f1d 100%);
  color: #f8fafc;
}
.ppt-page .slide-content,
.ppt-page .slide-content.active {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  opacity: 1;
  transform: none;
  pointer-events: none;
  z-index: 10;
}
.text-white { color: #fff; }
.text-yellow-500 { color: #eab308; }
.text-blue-300 { color: #93c5fd; }
.text-slate-200 { color: #e2e8f0; }
.text-slate-300 { color: #cbd5e1; }
.text-slate-400 { color: #94a3b8; }
.font-bold { font-weight: 700; }
.font-semibold { font-weight: 600; }
.font-medium { font-weight: 500; }
.font-light { font-weight: 300; }
.mb-2 { margin-bottom: 0.5rem; }
.mb-6 { margin-bottom: 1.5rem; }
.mb-8 { margin-bottom: 2rem; }
.mb-5 { margin-bottom: 1.25rem; }
.mt-2 { margin-top: 0.5rem; }
.mt-6 { margin-top: 1.5rem; }
.mt-8 { margin-top: 2rem; }
.w-24 { width: 6rem; }
.h-1 { height: 0.25rem; }
.bg-yellow-500 { background: #eab308; }
.rounded-full { border-radius: 999px; }
.tracking-wide { letter-spacing: 0.04em; }
.tracking-wider { letter-spacing: 0.06em; }
.tracking-widest { letter-spacing: 0.12em; }
.drop-shadow-lg { text-shadow: 0 4px 14px rgba(0,0,0,0.45); }
.drop-shadow-2xl { text-shadow: 0 10px 24px rgba(0,0,0,0.55); }
.text-center { text-align: center; }
.text-left { text-align: left; }
.leading-tight { line-height: 1.28; }
.leading-relaxed { line-height: 1.65; }
.w-full { width: 100%; }
.max-w-6xl { max-width: 72rem; }
.max-w-5xl { max-width: 64rem; }
.max-w-full { max-width: 100%; }
.mx-auto { margin-left: auto; margin-right: auto; }
.justify-center { justify-content: center; }
.grid { display: grid; }
.grid-cols-1 { grid-template-columns: 1fr; }
.gap-y-3 { row-gap: 0.75rem; }
.w-max { width: max-content; }
.uppercase { text-transform: uppercase; }
.text-2xl { font-size: 1.5rem; line-height: 2rem; }
.text-3xl { font-size: 1.875rem; line-height: 2.25rem; }
.text-xl { font-size: 1.25rem; line-height: 1.75rem; }
.absolute { position: absolute; }
.bottom-10 { bottom: 2.5rem; left: 0; right: 0; }
.list-disc { list-style: disc; padding-left: 1.2em; }
.list-inside { list-style-position: inside; }
.space-y-6 > li + li { margin-top: 1.15rem; }
.ppt-page ul { margin: 0; }
.ppt-page li { font-weight: 400; color: #e2e8f0; }
/* vh/vmin in worship-deck.css are relative to the STACKED capture page.
   Force a 1920x1080 type scale so every tile matches the HTML preview. */
.ppt-page .text-huge { font-size: 72px !important; line-height: 1.28 !important; }
.ppt-page .text-title { font-size: 48px !important; line-height: 1.35 !important; }
.ppt-page .text-lyric { font-size: 80px !important; line-height: 1.45 !important; font-weight: 600; }
.ppt-page .text-body { font-size: 40px !important; line-height: 1.55 !important; }
.ppt-page .text-responsive { font-size: 80px !important; line-height: 1.45 !important; font-weight: 600; }
.ppt-page .slide-header { padding: 28px 72px !important; flex-shrink: 0; }
.ppt-page .slide-body { padding: 24px 8% 56px !important; overflow: hidden !important; }
.ppt-page .slide-body.scripture-body { padding-top: 36px !important; padding-bottom: 72px !important; }
.ppt-page .cover-footer { bottom: 40px !important; font-size: 26px !important; }
.ppt-page .cover-leader { font-size: 38px !important; }
.ppt-page .cover-body .text-huge { font-size: 92px !important; line-height: 1.25 !important; }
.ppt-page .cover-body .text-title { font-size: 56px !important; line-height: 1.35 !important; }
.ppt-page .order-list { font-size: 30px !important; line-height: 1.32 !important; row-gap: 4px !important; gap: 4px !important; }
.ppt-page .order-stack > h2 { font-size: 48px !important; }
.ppt-page .order-stack > p { font-size: 22px !important; margin-bottom: 18px !important; }
.ppt-page .slide-body > .w-full {
  width: max-content;
  max-width: 92%;
}
.ppt-page .slide-header > div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 48%; }
.ppt-page.ppt-end-large .text-huge { font-size: 92px !important; line-height: 1.25 !important; }
.ppt-page.ppt-end-large .text-title { font-size: 64px !important; line-height: 1.3 !important; }
.ppt-page.ppt-end-large .text-2xl { font-size: 36px !important; line-height: 1.4 !important; }
.ppt-page.ppt-end-large ul,
.ppt-page.ppt-end-large li { font-size: 44px !important; line-height: 1.5 !important; font-weight: 500; }
"""


def _on_cloud() -> bool:
    return bool(
        os.environ.get("STREAMLIT_SHARING_MODE")
        or str(os.environ.get("HOME") or "").startswith("/home/appuser")
        or Path("/mount/src").is_dir()
    )


def _browser() -> str | None:
    env = (
        os.environ.get("WORSHIP_CHROME")
        or os.environ.get("CHROME_PATH")
        or os.environ.get("CHROMIUM_PATH")
    )
    if env and Path(env).exists():
        return env
    candidates = [
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/lib/chromium/chromium"),
        Path("/usr/lib/chromium-browser/chromium-browser"),
        Path("/snap/bin/chromium"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for path in candidates:
        if path and path.exists():
            return str(path)
    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "msedge",
    ):
        found = shutil.which(name)
        if found:
            return found
    return None


def _bundled_font_css() -> str:
    """Point capture HTML at Nanum files copied next to the deck HTML."""
    parts: list[str] = []
    for filename, weight in (
        ("NanumGothic-Regular.ttf", 400),
        ("NanumGothic-Bold.ttf", 700),
    ):
        if (ROOT / "fonts" / filename).exists():
            parts.append(
                f"@font-face {{ font-family: 'NanumGothic'; "
                f"src: url('{filename}') format('truetype'); "
                f"font-weight: {weight}; font-style: normal; }}"
            )
    return "\n".join(parts)


def _prepare_capture_dir(tmp_path: Path) -> None:
    fonts_dir = ROOT / "fonts"
    for filename in ("NanumGothic-Regular.ttf", "NanumGothic-Bold.ttf"):
        src = fonts_dir / filename
        if src.exists():
            shutil.copy2(src, tmp_path / filename)


def _get_slide_html_js() -> str:
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    start = text.index("function getSlideHTML(slide)")
    end = text.index("function updatePreview()", start)
    return text[start:end].strip()


def _deck_css() -> str:
    css_path = ROOT / "worship-deck.css"
    if css_path.exists():
        return css_path.read_text(encoding="utf-8")
    return ""


def build_capture_html(slides: list[dict]) -> str:
    payload = json.dumps(slides, ensure_ascii=False)
    js_fn = _get_slide_html_js()
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1920, height=1080">
<title>PPT capture</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.8/dist/web/static/pretendard.css">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;700&display=swap" rel="stylesheet">
<style>{_deck_css()}</style>
<style>{_bundled_font_css()}</style>
<style>{_CAPTURE_CSS}</style>
</head>
<body>
<div id="root"></div>
<script>
const SLIDES = {payload};
{js_fn}
(function () {{
  const root = document.getElementById('root');
  SLIDES.forEach(function (slide, i) {{
    const page = document.createElement('div');
    page.className = 'ppt-page';
    const title = String(slide.title || '');
    const prev = i > 0 ? String(SLIDES[i - 1].title || '') : '';
    if (title.indexOf('축도') !== -1 || (slide.type === 'title' && prev.indexOf('축도') !== -1 && !(slide.content || '').trim())) {{
      page.classList.add('ppt-end-large');
    }}
    if (title.indexOf('안내') !== -1 || title.indexOf('광고') !== -1 || title.indexOf('11.') === 0 || title.indexOf('12.') === 0) {{
      page.classList.add('ppt-end-large');
    }}
    page.innerHTML = '<div class="slide-bg-decoration"></div><div class="slide-content active"></div>';
    page.querySelector('.slide-content').innerHTML = getSlideHTML(slide);
    root.appendChild(page);
  }});
}})();
</script>
</body>
</html>
"""


def _run_chrome_screenshot(browser: str, html_path: Path, png_path: Path, *, height: int) -> None:
    html_uri = html_path.resolve().as_uri()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    if png_path.exists():
        png_path.unlink()
    profile = png_path.parent / "chrome-profile"
    profile.mkdir(exist_ok=True)
    budget = "3000" if _on_cloud() else "2500"
    common = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--hide-scrollbars",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-crash-reporter",
        "--allow-file-access-from-files",
        f"--user-data-dir={str(profile)}",
        "--force-device-scale-factor=1",
        "--high-dpi-support=1",
        f"--window-size={SLIDE_W_PX},{height}",
        f"--screenshot={str(png_path)}",
        f"--virtual-time-budget={budget}",
        html_uri,
    ]
    creation = 0
    if os.name == "nt":
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    last_err = ""
    for headless in ("--headless=new", "--headless"):
        proc = subprocess.run(
            [browser, headless, *common],
            capture_output=True,
            timeout=120,
            creationflags=creation,
        )
        if proc.returncode == 0 and png_path.exists() and png_path.stat().st_size >= 1000:
            return
        last_err = (proc.stderr or b"").decode("utf-8", "ignore")[-800:]
        if png_path.exists():
            try:
                png_path.unlink()
            except OSError:
                pass
    raise RuntimeError(f"Chrome screenshot failed: {last_err}")


def capture_slide_pngs(slides: list[dict]) -> list[bytes]:
    """Return one PNG (1920x1080) per slide, cropped from a stacked capture."""
    if not slides:
        return []
    browser = _browser()
    if not browser:
        raise RuntimeError("Chrome/Edge not found")

    from PIL import Image

    def _capture_chunk(chunk: list[dict], tmp_path: Path, tag: str) -> list[bytes]:
        html_path = tmp_path / f"deck_{tag}.html"
        html_path.write_text(build_capture_html(chunk), encoding="utf-8")
        shot = tmp_path / f"shot_{tag}.png"
        height = SLIDE_H_PX * max(1, len(chunk))
        _run_chrome_screenshot(browser, html_path, shot, height=height)
        im = Image.open(shot).convert("RGB")
        n = len(chunk)
        if im.width < 800 or im.height < 400:
            raise RuntimeError(f"Screenshot too small: {im.size}")
        page_h = im.height / n
        if page_h < 400:
            raise RuntimeError(f"Did not capture stacked slides: {im.size} for {n} pages")
        out: list[bytes] = []
        for i, _slide in enumerate(chunk):
            top = int(round(i * page_h))
            bottom = int(round((i + 1) * page_h))
            tile = im.crop((0, top, im.width, min(bottom, im.height)))
            if tile.size != (SLIDE_W_PX, SLIDE_H_PX):
                tile = tile.resize((SLIDE_W_PX, SLIDE_H_PX), Image.Resampling.LANCZOS)
            buf = BytesIO()
            tile.save(buf, format="JPEG", quality=92)
            out.append(buf.getvalue())
        return out

    n = len(slides)
    pngs: list[bytes] = [b""] * n
    # Cloud Chromium OOMs on a tall stacked screenshot — capture one slide at a time.
    batch = 6 if _on_cloud() else min(n, 20)
    with tempfile.TemporaryDirectory(prefix="worship_ppt_") as tmp:
        tmp_path = Path(tmp)
        _prepare_capture_dir(tmp_path)
        start = 0
        while start < n:
            size = min(batch, n - start)
            chunk = slides[start : start + size]
            try:
                captured = _capture_chunk(chunk, tmp_path, str(start))
            except Exception:
                if size == 1:
                    raise
                batch = max(1, size // 2)
                continue
            for i, blob in enumerate(captured):
                pngs[start + i] = blob
            start += size

    if any(not p for p in pngs):
        raise RuntimeError("Missing captured slides")
    return pngs


def generate_pptx_from_html_capture(
    data: WorshipData,
    *,
    allow_remote: bool = True,
) -> BytesIO:
    specs = build_presentation_slides(data, allow_remote=bool(allow_remote))
    pngs = capture_slide_pngs(specs)
    prs = Presentation()
    prs.slide_width = SLIDE_W_IN
    prs.slide_height = SLIDE_H_IN
    blank = prs.slide_layouts[6]
    for png in pngs:
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_picture(BytesIO(png), 0, 0, prs.slide_width, prs.slide_height)
    out = BytesIO()
    prs.save(out)
    out.seek(0)
    return out
