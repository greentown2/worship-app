"""Build worship PPTX from the same slide list as the HTML presentation.

Content-first: no master token injection, no 4-slot body rewrite.
"""

from __future__ import annotations

import html as html_lib
import re
from io import BytesIO
from typing import Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from build_master_templates import (
    ACCENT,
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
    _bg,
    _pair_ornaments,
)
from html_presentation import build_presentation_slides
from models import WorshipData
from text_normalize import normalize_breaks

_PPTX_SLIDES_VERSION = "2026-08-24-pptx-from-slides-v1"

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
    try:
        from pptx.oxml import OxmlElement
        from pptx.oxml.ns import qn

        rPr = run._r.get_or_add_rPr()  # noqa: SLF001
        for tag in ("latin", "ea", "cs"):
            el = rPr.find(qn(f"a:{tag}"))
            if el is None:
                el = OxmlElement(f"a:{tag}")
                rPr.append(el)
            el.set("typeface", font_name)
    except Exception:
        pass


def _textbox(
    slide,
    left,
    top,
    width,
    height,
    *,
    word_wrap: bool = True,
    anchor=MSO_ANCHOR.TOP,
):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = word_wrap
    try:
        tf.auto_size = None
        tf.vertical_anchor = anchor
        tf.margin_left = Inches(0.06)
        tf.margin_right = Inches(0.06)
        tf.margin_top = Inches(0.04)
        tf.margin_bottom = Inches(0.04)
    except Exception:
        pass
    return box, tf


def _write_lines(
    tf,
    lines: list[str],
    *,
    size_pt: float,
    align=PP_ALIGN.CENTER,
    bold: bool = False,
    color: RGBColor = FG,
    line_spacing: float = 1.35,
    colorize_responsive: bool = False,
) -> None:
    if not lines:
        lines = [""]
    for i, line in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        try:
            para.line_spacing = line_spacing
            para.space_after = Pt(4)
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


def _add_header(slide, text: str) -> None:
    if not (text or "").strip():
        return
    _, tf = _textbox(slide, MARGIN_L, _Y_HEADER, CONTENT_W, Inches(0.45))
    _write_lines(tf, [text.strip()], size_pt=SIZE_EYEBROW, align=PP_ALIGN.LEFT, color=ACCENT, bold=True)


def _add_title_bar(slide, text: str, *, size: float = SIZE_TITLE) -> None:
    if not (text or "").strip():
        return
    _, tf = _textbox(slide, MARGIN_L, _Y_TITLE, CONTENT_W, Inches(0.85))
    _write_lines(tf, [text.strip()], size_pt=size, align=PP_ALIGN.CENTER, color=FG, bold=True)


def _add_body(
    slide,
    lines: list[str],
    *,
    size: float = SIZE_BODY,
    align=PP_ALIGN.CENTER,
    colorize_responsive: bool = False,
) -> None:
    _, tf = _textbox(slide, MARGIN_L, _Y_BODY, CONTENT_W, _H_BODY)
    _write_lines(
        tf,
        lines,
        size_pt=size,
        align=align,
        color=FG,
        line_spacing=1.4,
        colorize_responsive=colorize_responsive,
    )


def _render_cover(slide, spec: dict) -> None:
    _bg(slide, "cover")
    title = (spec.get("title") or "주일 예배").strip()
    subtitle = (spec.get("subtitle") or "").strip()
    extra = (spec.get("extra") or "").strip()
    footer = (spec.get("footer") or "").strip()

    _, tf = _textbox(
        slide,
        MARGIN_L,
        Inches(2.1),
        CONTENT_W,
        Inches(1.3),
        anchor=MSO_ANCHOR.MIDDLE,
    )
    _write_lines(tf, [title], size_pt=SIZE_COVER_BRAND, align=PP_ALIGN.CENTER, bold=True, color=FG)

    if subtitle:
        _, tf = _textbox(slide, MARGIN_L, Inches(3.5), CONTENT_W, Inches(0.7))
        _write_lines(tf, [subtitle], size_pt=SIZE_COVER_SUB, align=PP_ALIGN.CENTER, color=MUTED)

    if extra:
        _, tf = _textbox(slide, MARGIN_L, Inches(4.4), CONTENT_W, Inches(0.55))
        _write_lines(tf, [extra], size_pt=SIZE_COVER_LEADER, align=PP_ALIGN.CENTER, bold=True, color=ACCENT)

    if footer:
        _, tf = _textbox(slide, MARGIN_L, _Y_FOOT, CONTENT_W, Inches(0.45))
        _write_lines(tf, [footer], size_pt=SIZE_META, align=PP_ALIGN.CENTER, color=MUTED)


def _render_section(slide, spec: dict) -> None:
    _bg(slide, "section")
    _pair_ornaments(slide, "section")
    title = (spec.get("title") or "").strip()
    subtitle = (spec.get("subtitle") or "").strip()
    _, tf = _textbox(
        slide,
        MARGIN_L,
        Inches(2.6),
        CONTENT_W,
        Inches(1.4),
        anchor=MSO_ANCHOR.MIDDLE,
    )
    _write_lines(tf, [title], size_pt=SIZE_COVER_BRAND * 0.85, align=PP_ALIGN.CENTER, bold=True, color=ACCENT)
    if subtitle:
        _, tf = _textbox(slide, MARGIN_L, Inches(4.2), CONTENT_W, Inches(0.9))
        _write_lines(tf, [subtitle], size_pt=SIZE_TITLE, align=PP_ALIGN.CENTER, color=FG)


def _render_sermon(slide, spec: dict) -> None:
    _bg(slide, "sermon")
    _pair_ornaments(slide, "sermon")
    _add_header(slide, spec.get("header") or "8. 생명의 말씀")
    title = (spec.get("title") or "").strip()
    subtitle = (spec.get("subtitle") or "").strip()
    footer = (spec.get("footer") or "").strip()
    _, tf = _textbox(
        slide,
        MARGIN_L,
        Inches(2.4),
        CONTENT_W,
        Inches(2.2),
        anchor=MSO_ANCHOR.MIDDLE,
    )
    _write_lines(tf, [f'"{title}"' if title else "생명의 말씀"], size_pt=SIZE_SERMON, align=PP_ALIGN.CENTER, bold=True)
    if subtitle:
        _, tf = _textbox(slide, MARGIN_L, Inches(4.8), CONTENT_W, Inches(0.6))
        _write_lines(tf, [subtitle], size_pt=SIZE_META, align=PP_ALIGN.CENTER, color=MUTED)
    if footer:
        _, tf = _textbox(slide, MARGIN_L, _Y_FOOT, CONTENT_W, Inches(0.4))
        _write_lines(tf, [footer], size_pt=SIZE_EYEBROW, align=PP_ALIGN.CENTER, color=MUTED)


def _render_reading(slide, spec: dict, *, responsive: bool = False) -> None:
    motif = "responsive" if responsive else "reading"
    _bg(slide, motif)
    _pair_ornaments(slide, motif)
    _add_header(slide, spec.get("header") or "")
    _add_title_bar(slide, spec.get("title") or "")
    lines = _lines(spec.get("content"))
    align = PP_ALIGN.LEFT if responsive else PP_ALIGN.CENTER
    _add_body(slide, lines, align=align, colorize_responsive=responsive)


def _render_title(slide, spec: dict) -> None:
    _bg(slide, "title")
    _pair_ornaments(slide, "title")
    title = (spec.get("title") or "").strip()
    subtitle = (spec.get("subtitle") or "").strip()
    lines = _lines(spec.get("content"))
    _add_header(slide, subtitle if subtitle and title == "예배 순서" else "")
    if title == "예배 순서":
        _add_title_bar(slide, title)
        _add_body(slide, lines or _lines(spec.get("content")), size=24, align=PP_ALIGN.LEFT)
        return
    _, tf = _textbox(
        slide,
        MARGIN_L,
        Inches(2.5),
        CONTENT_W,
        Inches(1.5),
        anchor=MSO_ANCHOR.MIDDLE,
    )
    _write_lines(tf, [title], size_pt=SIZE_COVER_BRAND * 0.8, align=PP_ALIGN.CENTER, bold=True, color=ACCENT)
    if subtitle:
        _, tf = _textbox(slide, MARGIN_L, Inches(4.2), CONTENT_W, Inches(1.2))
        _write_lines(tf, [subtitle], size_pt=SIZE_BODY, align=PP_ALIGN.CENTER, color=FG)


def _render_slide(slide, spec: dict) -> None:
    kind = (spec.get("type") or "title").lower()
    if kind == "cover":
        _render_cover(slide, spec)
    elif kind == "section":
        _render_section(slide, spec)
    elif kind == "sermon":
        _render_sermon(slide, spec)
    elif kind == "responsive":
        _render_reading(slide, spec, responsive=True)
    elif kind in {"creed", "scripture", "lyric"}:
        _render_reading(slide, spec, responsive=False)
    else:
        _render_title(slide, spec)


def generate_pptx_from_slides(
    data: WorshipData,
    *,
    allow_remote: bool = True,
) -> BytesIO:
    """Build a full worship deck mirroring HTML slide order and content."""
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
            # Never leave a blank hole — at least show the title
            _bg(slide, "default")
            _add_title_bar(slide, (spec.get("title") or spec.get("header") or "예배").strip())

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
    generate_worship_pptx_slides_first.last_insert_notes = [  # type: ignore[attr-defined]
        f"PPT {_PPTX_SLIDES_VERSION}: HTML과 동일한 슬라이드 목록으로 생성"
    ]
    return generate_pptx_from_slides(data, allow_remote=allow_remote)
