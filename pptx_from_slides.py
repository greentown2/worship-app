"""Build worship PPTX from the same slide list as the HTML presentation.

Content-first: no master token injection, no 4-slot body rewrite.
"""

from __future__ import annotations

import html as html_lib
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from build_master_templates import (
    ACCENT,
    BG,
    BG_READ,
    BG_WASH,
    CONG_YELLOW,
    CONTENT_W,
    FG,
    FONT,
    LEADER_RED,
    MARGIN_L,
    MUTED,
    SIZE_BODY,
    SIZE_COVER_BRAND,
    SIZE_COVER_LEADER,
    SIZE_COVER_SUB,
    SIZE_EYEBROW,
    SIZE_META,
    SIZE_SERMON,
    SIZE_TITLE,
    SLIDE_H,
    SLIDE_W,
)
from html_presentation import build_presentation_slides
from models import WorshipData
from text_normalize import normalize_breaks

_PPTX_SLIDES_VERSION = "2026-09-18-office-safe-v2"


def _rect(slide, left, top, width, height, color: RGBColor):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    try:
        shape.line.fill.background()
    except Exception:
        pass
    return shape


def _bg_safe(slide, motif: str = "default") -> None:
    """Background with rectangles only — no connectors/ovals/p:bg (Office rejects those)."""
    _ = motif
    _rect(slide, Inches(0), Inches(0), SLIDE_W, SLIDE_H, BG)
    _rect(slide, Inches(0), Inches(0), SLIDE_W, Inches(2.4), BG_WASH)
    _rect(
        slide,
        MARGIN_L - Inches(0.30),
        Inches(0.28),
        CONTENT_W + Inches(0.60),
        Inches(6.80),
        BG_READ,
    )
    _rect(slide, Inches(0), Inches(0), Inches(0.14), SLIDE_H, ACCENT)

_Y_HEADER = Inches(0.38)
_Y_TITLE = Inches(0.95)
_Y_BODY = Inches(1.95)
_H_BODY = Inches(4.85)
_Y_FOOT = Inches(6.85)


def _plain(content: str | None) -> str:
    """Strip HTML from slide content into plain multiline text."""
    t = content or ""
    if not t.strip():
        return ""
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(p|div|li|h\d)\s*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html_lib.unescape(t)
    return normalize_breaks(t).strip()


def _lines(content: str | None) -> list[str]:
    plain = _plain(content)
    return [ln.strip() for ln in plain.splitlines() if ln.strip()]


def _set_run(
    run,
    text: str,
    *,
    size_pt: float,
    bold: bool = False,
    color: RGBColor = FG,
    font_name: str = FONT,
) -> None:
    run.text = text
    try:
        run.font.name = font_name
        run.font.size = Pt(size_pt)
        run.font.bold = bold
        run.font.color.rgb = color
    except Exception:
        pass
    # Skip a:ea XML injection — some Office builds treat it as a corrupt package.


def _textbox(
    slide,
    left,
    top,
    width,
    height,
    *,
    word_wrap: bool = True,
    anchor=MSO_ANCHOR.TOP,
    role: str = "",
):
    box = slide.shapes.add_textbox(left, top, width, height)
    if role:
        box.name = f"role:{role}"
    tf = box.text_frame
    tf.word_wrap = word_wrap
    try:
        tf.vertical_anchor = anchor
        tf.margin_left = Inches(0.06)
        tf.margin_right = Inches(0.06)
        tf.margin_top = Inches(0.04)
        tf.margin_bottom = Inches(0.04)
    except Exception:
        pass
    return box, tf


def _gold_bar(slide, left, top, width, height, *, role: str = "rule"):
    shape = _rect(slide, left, top, width, height, ACCENT)
    if role:
        shape.name = f"role:{role}"
    return shape


def _write_lines(
    tf,
    lines: list[str],
    *,
    size_pt: float,
    align=PP_ALIGN.CENTER,
    bold: bool = False,
    color: RGBColor = FG,
    line_spacing: float = 1.35,
    space_after_pt: float = 4,
    colorize_responsive: bool = False,
) -> None:
    if not lines:
        lines = [""]
    for i, line in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        try:
            para.line_spacing = line_spacing
            para.space_after = Pt(space_after_pt)
        except Exception:
            pass
        # clear first para runs
        if para.runs:
            for r in list(para.runs)[1:]:
                r.text = ""
            run0 = para.runs[0]
            run0.text = ""
        else:
            run0 = para.add_run()

        if colorize_responsive and (":" in line or "：" in line):
            m = re.match(r"^([^:：]+)([:：]\s*)(.*)$", line)
            role = None
            head = line[:4]
            if "인도" in head or "인도자" in line[:6]:
                role = "leader"
            elif "회중" in head:
                role = "cong"
            if m and role:
                label, colon, rest = m.group(1), m.group(2), m.group(3)
                c = LEADER_RED if role == "leader" else CONG_YELLOW
                _set_run(run0, label + colon, size_pt=size_pt, bold=True, color=c)
                if rest:
                    run1 = para.add_run()
                    _set_run(run1, rest, size_pt=size_pt, bold=False, color=c)
                continue

        _set_run(run0, line, size_pt=size_pt, bold=bold, color=color)


def _add_header(slide, text: str, *, role: str = "header") -> None:
    if not (text or "").strip():
        return
    _, tf = _textbox(slide, MARGIN_L, _Y_HEADER, CONTENT_W, Inches(0.45), role=role)
    _write_lines(tf, [text.strip()], size_pt=18, align=PP_ALIGN.LEFT, color=ACCENT, bold=True)


def _add_header_row(slide, left_text: str, right_text: str = "") -> None:
    left_text = (left_text or "").strip()
    right_text = (right_text or "").strip()
    half = Inches(float(CONTENT_W) / 914400.0 * 0.50)
    if left_text:
        _, tf = _textbox(slide, MARGIN_L, _Y_HEADER, half - Inches(0.08), Inches(0.45), role="header")
        _write_lines(tf, [left_text], size_pt=18, align=PP_ALIGN.LEFT, color=ACCENT, bold=True)
    if right_text:
        _, tf = _textbox(
            slide,
            MARGIN_L + half + Inches(0.08),
            _Y_HEADER,
            half - Inches(0.08),
            Inches(0.45),
            role="header_right",
        )
        _write_lines(tf, [right_text], size_pt=18, align=PP_ALIGN.RIGHT, color=MUTED, bold=False)
    if left_text or right_text:
        _gold_bar(
            slide,
            MARGIN_L,
            Inches(0.86),
            CONTENT_W,
            Inches(0.015),
            role="rule",
        )


def _add_title_bar(slide, text: str, *, size: float = SIZE_TITLE, role: str = "title", color: RGBColor = FG) -> None:
    if not (text or "").strip():
        return
    _, tf = _textbox(slide, MARGIN_L, _Y_TITLE, CONTENT_W, Inches(0.85), role=role)
    _write_lines(tf, [text.strip()], size_pt=size, align=PP_ALIGN.CENTER, color=color, bold=True)


def _add_body(
    slide,
    lines: list[str],
    *,
    size: float = SIZE_BODY,
    align=PP_ALIGN.CENTER,
    colorize_responsive: bool = False,
    role: str = "body",
    anchor=MSO_ANCHOR.TOP,
    line_spacing: float = 1.4,
    bold: bool = False,
) -> None:
    _, tf = _textbox(slide, MARGIN_L, _Y_BODY, CONTENT_W, _H_BODY, anchor=anchor, role=role)
    _write_lines(
        tf,
        lines,
        size_pt=size,
        align=align,
        color=FG,
        bold=bold,
        line_spacing=line_spacing,
        space_after_pt=2 if len(lines) >= 6 else 4,
        colorize_responsive=colorize_responsive,
    )


def _render_cover(slide, spec: dict) -> None:
    _bg_safe(slide, "cover")
    title = (spec.get("title") or "주일 예배").strip()
    subtitle = (spec.get("subtitle") or "").strip()
    extra = (spec.get("extra") or "").strip()
    footer = (spec.get("footer") or "").strip()

    bar_w = Inches(1.55)
    bar_left = Inches(float(MARGIN_L) / 914400.0 + (float(CONTENT_W) / 914400.0 - 1.55) / 2.0)
    _gold_bar(slide, bar_left, Inches(2.05), bar_w, Inches(0.055), role="accent")
    _, tf = _textbox(
        slide,
        MARGIN_L,
        Inches(2.2),
        CONTENT_W,
        Inches(1.3),
        anchor=MSO_ANCHOR.MIDDLE,
        role="title",
    )
    _write_lines(tf, [title], size_pt=SIZE_COVER_BRAND, align=PP_ALIGN.CENTER, bold=True, color=FG)

    if subtitle:
        _, tf = _textbox(slide, MARGIN_L, Inches(3.55), CONTENT_W, Inches(0.7), role="subtitle")
        _write_lines(tf, [subtitle], size_pt=SIZE_COVER_SUB, align=PP_ALIGN.CENTER, color=MUTED)

    if extra:
        _, tf = _textbox(slide, MARGIN_L, Inches(4.35), CONTENT_W, Inches(0.55), role="extra")
        _write_lines(tf, [extra], size_pt=SIZE_COVER_LEADER, align=PP_ALIGN.CENTER, bold=True, color=ACCENT)

    if footer:
        _, tf = _textbox(slide, MARGIN_L, _Y_FOOT, CONTENT_W, Inches(0.45), role="footer")
        _write_lines(tf, [footer], size_pt=SIZE_META, align=PP_ALIGN.CENTER, color=MUTED)


def _render_section(slide, spec: dict) -> None:
    _bg_safe(slide, "section")
    title = (spec.get("title") or "").strip()
    subtitle = (spec.get("subtitle") or "").strip()
    _, tf = _textbox(
        slide,
        MARGIN_L,
        Inches(2.6),
        CONTENT_W,
        Inches(1.4),
        anchor=MSO_ANCHOR.MIDDLE,
        role="title",
    )
    _write_lines(tf, [title], size_pt=SIZE_COVER_BRAND * 0.85, align=PP_ALIGN.CENTER, bold=True, color=ACCENT)
    if subtitle:
        _, tf = _textbox(slide, MARGIN_L, Inches(4.2), CONTENT_W, Inches(0.9), role="subtitle")
        _write_lines(tf, [subtitle], size_pt=SIZE_TITLE, align=PP_ALIGN.CENTER, color=FG)


def _render_sermon(slide, spec: dict) -> None:
    _bg_safe(slide, "sermon")
    _add_header_row(slide, spec.get("header") or "9. 생명의 말씀", spec.get("subtitle") or "")
    title = (spec.get("title") or "").strip()
    footer = (spec.get("footer") or "").strip()
    _, tf = _textbox(slide, MARGIN_L, Inches(1.7), CONTENT_W, Inches(0.45), role="kicker")
    _write_lines(tf, ["오늘의 말씀"], size_pt=SIZE_META, align=PP_ALIGN.CENTER, color=MUTED)
    _, tf = _textbox(
        slide,
        MARGIN_L,
        Inches(2.3),
        CONTENT_W,
        Inches(2.4),
        anchor=MSO_ANCHOR.MIDDLE,
        role="title",
    )
    _write_lines(tf, [f'"{title}"' if title else "생명의 말씀"], size_pt=SIZE_SERMON, align=PP_ALIGN.CENTER, bold=True)
    if footer:
        _, tf = _textbox(slide, MARGIN_L, _Y_FOOT, CONTENT_W, Inches(0.4), role="footer")
        _write_lines(tf, [footer], size_pt=SIZE_EYEBROW, align=PP_ALIGN.CENTER, color=MUTED)


def _render_lyric(slide, spec: dict) -> None:
    _bg_safe(slide, "reading")
    _add_header_row(slide, spec.get("header") or "", spec.get("title") or "")
    lines = _lines(spec.get("content"))
    _add_body(
        slide,
        lines,
        size=36,
        align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
        line_spacing=1.42,
        bold=True,
    )


def _render_creed(slide, spec: dict) -> None:
    _bg_safe(slide, "reading")
    _add_header_row(slide, spec.get("header") or "3. 사도신경", "")
    _add_title_bar(slide, spec.get("title") or "사도신경", size=40, color=ACCENT)
    _add_body(slide, _lines(spec.get("content")), size=32, align=PP_ALIGN.CENTER, line_spacing=1.45)


def _render_scripture(slide, spec: dict) -> None:
    _bg_safe(slide, "reading")
    _add_header_row(slide, spec.get("header") or "", spec.get("title") or "")
    _add_body(slide, _lines(spec.get("content")), size=30, align=PP_ALIGN.CENTER, line_spacing=1.45)


def _render_responsive(slide, spec: dict) -> None:
    _bg_safe(slide, "responsive")
    _add_header_row(slide, spec.get("header") or "", spec.get("title") or "")
    _add_body(
        slide,
        _lines(spec.get("content")),
        size=30,
        align=PP_ALIGN.LEFT,
        colorize_responsive=True,
        line_spacing=1.42,
        bold=True,
    )


def _render_title(slide, spec: dict) -> None:
    _bg_safe(slide, "title")
    title = (spec.get("title") or "").strip()
    subtitle = (spec.get("subtitle") or "").strip()
    content = spec.get("content") or ""
    lines = _lines(content)
    is_list = (
        title == "예배 순서"
        or title.startswith("11.")
        or title.startswith("12.")
        or "order-list" in content
        or "list-disc" in content
    )
    if is_list:
        _, tf = _textbox(slide, MARGIN_L, Inches(0.42), CONTENT_W, Inches(0.7), role="title")
        _write_lines(tf, [title], size_pt=SIZE_TITLE, align=PP_ALIGN.CENTER, bold=True, color=ACCENT)
        if subtitle:
            _, tf = _textbox(slide, MARGIN_L, Inches(1.12), CONTENT_W, Inches(0.4), role="subtitle")
            _write_lines(tf, [subtitle], size_pt=SIZE_META, align=PP_ALIGN.CENTER, color=MUTED)
        if lines:
            _add_body(slide, lines, size=22 if title.startswith(("11.", "12.")) else 24, align=PP_ALIGN.LEFT, line_spacing=1.35)
        return
    _, tf = _textbox(
        slide,
        MARGIN_L,
        Inches(2.5),
        CONTENT_W,
        Inches(1.5),
        anchor=MSO_ANCHOR.MIDDLE,
        role="title",
    )
    _write_lines(tf, [title], size_pt=SIZE_COVER_BRAND * 0.8, align=PP_ALIGN.CENTER, bold=True, color=ACCENT)
    if subtitle:
        _, tf = _textbox(slide, MARGIN_L, Inches(4.2), CONTENT_W, Inches(1.2), role="subtitle")
        _write_lines(tf, [subtitle], size_pt=SIZE_BODY, align=PP_ALIGN.CENTER, color=FG)


def _render_slide(slide, spec: dict) -> None:
    kind = (spec.get("type") or "title").lower()
    if kind == "cover":
        _render_cover(slide, spec)
    elif kind == "section":
        _render_section(slide, spec)
    elif kind == "sermon":
        _render_sermon(slide, spec)
    elif kind == "lyric":
        _render_lyric(slide, spec)
    elif kind == "creed":
        _render_creed(slide, spec)
    elif kind == "responsive":
        _render_responsive(slide, spec)
    elif kind == "scripture":
        _render_scripture(slide, spec)
    else:
        _render_title(slide, spec)


def generate_pptx_from_slides(
    data: WorshipData,
    *,
    allow_remote: bool = True,
) -> BytesIO:
    """Build a 16:9 deck that looks like the HTML presentation."""
    import os
    on_cloud = bool(
        os.environ.get("STREAMLIT_SHARING_MODE")
        or str(os.environ.get("HOME") or "").startswith("/home/appuser")
        or Path("/mount/src").is_dir()
    )
    if not on_cloud:
        try:
            from pptx_html_capture import generate_pptx_from_html_capture

            out = generate_pptx_from_html_capture(data, allow_remote=allow_remote)
            generate_pptx_from_slides.last_mode = "html-capture"  # type: ignore[attr-defined]
            return out
        except Exception as exc:
            generate_pptx_from_slides.last_mode = f"native-fallback:{type(exc).__name__}"  # type: ignore[attr-defined]
    else:
        generate_pptx_from_slides.last_mode = "native-cloud"  # type: ignore[attr-defined]

    specs = build_presentation_slides(data, allow_remote=bool(allow_remote))
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    blank = prs.slide_layouts[6]
    for spec in specs:
        slide = prs.slides.add_slide(blank)
        try:
            _render_slide(slide, spec)
        except Exception:
            _bg_safe(slide, "default")
            _add_title_bar(slide, (spec.get("title") or spec.get("header") or "예배").strip())
    # Never run polish on the native builder — XML reorder/auto-size breaks Office.
    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf


def generate_worship_pptx_slides_first(
    data: WorshipData,
    *,
    allow_remote: bool = True,
    master: Optional[object] = None,
    this_week_hymns=None,
    insert_this_week: bool = False,
) -> BytesIO:
    """
    Primary PPT path: same content model as HTML.
    master / this_week insert kept for API compatibility but unused by default
    (lyrics are already projected as lyric slides).
    """
    _ = master, this_week_hymns, insert_this_week
    out = generate_pptx_from_slides(data, allow_remote=allow_remote)
    note = getattr(generate_pptx_from_slides, "last_mode", "")
    generate_worship_pptx_slides_first.last_insert_notes = [  # type: ignore[attr-defined]
        f"PPT {_PPTX_SLIDES_VERSION}: HTML 화면을 그대로 담음"
        + (f" ({note})" if note else "")
    ]
    return out
