"""Printable A4 Sunday bulletin — Platypus layout, separate from PPT injection."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import List, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)

from data_enrich import enrich_worship_data, hymn_label
from models import HymnEntry, WorshipData
from text_normalize import normalize_breaks

INK = colors.HexColor("#1F2420")
MUTED = colors.HexColor("#5C635C")
ACCENT = colors.HexColor("#3D5A40")
BAND = colors.HexColor("#F1F5F0")
RULE = colors.HexColor("#CBD5C8")

_FONT_READY = False
FONT = "BulletinBody"
FONT_BOLD = "BulletinBody-Bold"


def clean_text(text: str | None) -> str:
    """Clean _x000B_ / soft breaks into real newlines (proposal-compatible alias)."""
    return normalize_breaks(text or "").replace("\xa0", " ").strip()


def _clean(text: str | None) -> str:
    return clean_text(text)


def _ensure_fonts() -> None:
    global _FONT_READY, FONT, FONT_BOLD
    if _FONT_READY:
        return
    regular = Path(r"C:\Windows\Fonts\malgun.ttf")
    bold = Path(r"C:\Windows\Fonts\malgunbd.ttf")
    if regular.exists():
        pdfmetrics.registerFont(TTFont(FONT, str(regular)))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold if bold.exists() else regular)))
    else:
        FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"
    _FONT_READY = True


def _hymn_line(h: HymnEntry) -> str:
    return _clean(hymn_label(h) if h else "")


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    """Paragraph with XML-safe text and real line breaks as <br/>."""
    cleaned = _clean(text)
    html = escape(cleaned).replace("\n", "<br/>")
    return Paragraph(html or " ", style)


def _styles() -> dict[str, ParagraphStyle]:
    _ensure_fonts()
    return {
        "church_en": ParagraphStyle(
            "ChurchEn",
            fontName=FONT,
            fontSize=9,
            leading=12,
            alignment=1,
            textColor=MUTED,
        ),
        "church_ko": ParagraphStyle(
            "ChurchKo",
            fontName=FONT_BOLD,
            fontSize=18,
            leading=22,
            alignment=1,
            textColor=ACCENT,
            spaceAfter=4,
        ),
        "service": ParagraphStyle(
            "ServiceTitle",
            fontName=FONT_BOLD,
            fontSize=14,
            leading=18,
            alignment=1,
            textColor=INK,
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "Meta",
            fontName=FONT,
            fontSize=10,
            leading=14,
            alignment=1,
            textColor=MUTED,
            spaceAfter=10,
        ),
        "section": ParagraphStyle(
            "Section",
            fontName=FONT_BOLD,
            fontSize=12,
            leading=16,
            textColor=ACCENT,
            spaceBefore=8,
            spaceAfter=6,
        ),
        "order_left": ParagraphStyle(
            "OrderLeft",
            fontName=FONT_BOLD,
            fontSize=10,
            leading=14,
            textColor=INK,
        ),
        "order_right": ParagraphStyle(
            "OrderRight",
            fontName=FONT,
            fontSize=10,
            leading=14,
            textColor=MUTED,
            alignment=2,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName=FONT,
            fontSize=9.5,
            leading=14,
            textColor=INK,
            spaceAfter=4,
        ),
        "body_bold": ParagraphStyle(
            "BodyBold",
            fontName=FONT_BOLD,
            fontSize=10.5,
            leading=15,
            textColor=INK,
            spaceAfter=4,
        ),
        "footer": ParagraphStyle(
            "Footer",
            fontName=FONT,
            fontSize=9,
            leading=12,
            alignment=1,
            textColor=MUTED,
            spaceBefore=12,
        ),
    }


def _order_items(data: WorshipData) -> List[Tuple[str, str, str]]:
    return [
        ("1", "찬양과 기도", _hymn_line(data.praise_hymn)),
        ("2", "사도신경", ""),
        ("3", "교독문", _clean(data.responsive_reading_title)),
        ("4", "찬송가", _hymn_line(data.hymn)),
        ("5", "예배의 기도", _clean(data.worship_prayer_leader)),
        ("6", "오늘의 말씀", _clean(data.scripture_reference)),
        ("7", "찬양", _hymn_line(data.response_hymn)),
        ("8", "생명의 말씀", _clean(data.sermon_title)),
        ("9", "감사와 봉헌", _hymn_line(data.offering_hymn)),
        ("10", "축도", _clean(data.benediction)[:48] if data.benediction else ""),
    ]


def _lyrics_block(h: HymnEntry) -> str:
    label = _hymn_line(h)
    lines = [ln for ln in (h.lyrics or []) if str(ln).strip() or ln == ""]
    body = _clean("\n".join(str(ln) for ln in lines))
    if not label and not body:
        return ""
    if label and body:
        return f"{label}\n{body}"
    return label or body


def draw_bulletin(data: WorshipData) -> BytesIO:
    """
    Clean A4 printable bulletin via Platypus — no overlapping canvas slots,
    no _x000B_, full scripture + hymn lyrics from WorshipData.
    """
    data = enrich_worship_data(data, allow_remote=True, force_hymn_lyrics=True)
    styles = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=_clean(data.service_title) or "주일 예배 주보",
    )

    story: list = []

    # Header
    if _clean(data.church_name_en):
        story.append(_para(data.church_name_en, styles["church_en"]))
    story.append(_para(data.church_name_ko or "플로튼 빌라 교회", styles["church_ko"]))
    story.append(_para(data.service_title or "주일 예배", styles["service"]))
    meta_bits = [
        b
        for b in (
            _clean(data.date),
            _clean(data.service_time),
            f"설교 {_clean(data.preacher)}" if _clean(data.preacher) else "",
        )
        if b
    ]
    if meta_bits:
        story.append(_para("  ·  ".join(meta_bits), styles["meta"]))
    story.append(Spacer(1, 4))

    # Order table
    story.append(_para("예배 순서", styles["section"]))
    table_data = []
    for num, title, detail in _order_items(data):
        left = f"{num}.  {title}"
        table_data.append(
            [
                _para(left, styles["order_left"]),
                _para(detail or " ", styles["order_right"]),
            ]
        )
    t = Table(table_data, colWidths=[70 * mm, 104 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BAND),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
                ("LINEBELOW", (0, -1), (-1, -1), 0.8, ACCENT),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    # soft band only on header row visually via first row background after rebuild
    # Re-style first row band
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BAND)]))
    story.append(t)
    story.append(Spacer(1, 10))

    # Scripture — full text
    ref = _clean(data.scripture_reference)
    body = _clean(data.scripture_text)
    if ref or body:
        block = [_para("오늘의 말씀", styles["section"])]
        if ref:
            block.append(_para(ref, styles["body_bold"]))
        if body:
            block.append(_para(body, styles["body"]))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 6))

    # Sermon
    if _clean(data.sermon_title) or _clean(data.sermon_subtitle):
        block = [_para("생명의 말씀", styles["section"])]
        if _clean(data.sermon_title):
            block.append(_para(data.sermon_title, styles["body_bold"]))
        if _clean(data.sermon_subtitle):
            block.append(_para(data.sermon_subtitle, styles["body"]))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 6))

    # Responsive
    rt = _clean(data.responsive_reading_title)
    rb = _clean(data.responsive_reading)
    if rt or rb:
        heading = "교독문" + (f"  ·  {rt}" if rt else "")
        block = [_para(heading, styles["section"])]
        if rb:
            block.append(_para(rb, styles["body"]))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 6))

    # Hymn lyrics (full, cleaned)
    lyric_parts = []
    for h in (data.praise_hymn, data.hymn, data.response_hymn, data.offering_hymn):
        chunk = _lyrics_block(h)
        if chunk and len(chunk.splitlines()) >= 2:
            lyric_parts.append(chunk)
    if lyric_parts:
        block = [_para("찬송가 가사", styles["section"])]
        for i, chunk in enumerate(lyric_parts):
            block.append(_para(chunk, styles["body"]))
            if i < len(lyric_parts) - 1:
                block.append(Spacer(1, 6))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 6))

    # Announcements
    if _clean(data.announcements):
        story.append(_para("소식 · 광고", styles["section"]))
        story.append(_para(data.announcements, styles["body"]))

    if _clean(data.closing_note):
        story.append(_para(data.closing_note, styles["footer"]))

    doc.build(story)
    buf.seek(0)
    # Safety: never ship soft-break escapes
    raw = buf.getvalue()
    if b"_x000B_" in raw or b"_x000b_" in raw:
        raise RuntimeError("Bulletin PDF still contains soft-break escape codes")
    buf.seek(0)
    return buf


def bulletin_preview_text(data: WorshipData) -> str:
    """Plain-text preview matching the printable A4 bulletin structure."""
    data = enrich_worship_data(data, allow_remote=False, force_hymn_lyrics=True)
    lines: List[str] = [
        _clean(data.church_name_en),
        _clean(data.church_name_ko),
        _clean(data.service_title or "주일 예배"),
    ]
    meta = [b for b in (_clean(data.date), _clean(data.service_time), _clean(data.preacher)) if b]
    if meta:
        lines.append("  ·  ".join(meta))
    lines += ["", "──────── 예배 순서 ────────"]
    for num, title, detail in _order_items(data):
        row = f"{num}. {title}"
        if detail:
            row += f"  —  {detail}"
        lines.append(row)

    ref = _clean(data.scripture_reference)
    body = _clean(data.scripture_text)
    if ref or body:
        lines += ["", "──────── 오늘의 말씀 ────────"]
        if ref:
            lines.append(ref)
        if body:
            lines.extend(body.splitlines())

    if _clean(data.sermon_title):
        lines += ["", "──────── 생명의 말씀 ────────", _clean(data.sermon_title)]
        if _clean(data.sermon_subtitle):
            lines.append(_clean(data.sermon_subtitle))

    for label, h in (
        ("찬양과 기도", data.praise_hymn),
        ("찬송가", data.hymn),
    ):
        chunk = _lyrics_block(h)
        if chunk and len(chunk.splitlines()) >= 2:
            lines += ["", f"──────── {label} 가사 ────────", *chunk.splitlines()]

    if _clean(data.announcements):
        lines += ["", "──────── 소식 · 광고 ────────"]
        lines.extend(_clean(data.announcements).splitlines()[:12])

    text = "\n".join(lines)
    return clean_text(text)


def generate_worship_pdf(data: WorshipData, *, allow_remote: bool = True) -> BytesIO:
    """
    Build a clean A4 printable Sunday bulletin (BytesIO for Streamlit download).

    Uses Malgun Gothic + Platypus flowables — not Helvetica, not hardcoded stubs.
    """
    _ = allow_remote
    return draw_bulletin(data)


def generate_bulletin_pdf(output_path: str | Path, data: WorshipData | dict) -> str:
    """
    Convenience wrapper matching the proposal API (writes a file path).
    Accepts WorshipData or a simple dict of fields.
    """
    if isinstance(data, dict):
        wd = WorshipData(
            date=_clean(data.get("date", "")),
            praise_hymn=HymnEntry(number=_clean(data.get("hymn_1", ""))),
            hymn=HymnEntry(number=_clean(data.get("hymn_2", ""))),
            responsive_reading_title=_clean(data.get("responsive", "")),
            scripture_reference=_clean(data.get("bible_text", "")),
            sermon_title=_clean(data.get("sermon_title", "")),
            include_hymn_lyrics=True,
        )
    else:
        wd = data
    out = Path(output_path)
    buf = generate_worship_pdf(wd)
    out.write_bytes(buf.getvalue())
    return str(out)
