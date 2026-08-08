"""Create master PPTX and bulletin PDF background + slot map."""

from __future__ import annotations

import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"
TEMPLATES.mkdir(exist_ok=True)

# Senior-friendly projection palette (charcoal + warm gold, not purple/cream defaults)
BG = RGBColor(0x1A, 0x1D, 0x22)
BG_SOFT = RGBColor(0x24, 0x28, 0x2E)
FG = RGBColor(0xFF, 0xFF, 0xFF)
MUTED = RGBColor(0xB8, 0xBE, 0xC6)
ACCENT = RGBColor(0xC9, 0xA8, 0x5C)  # warm gold
RULE = RGBColor(0x3A, 0x40, 0x4A)
FONT = "Malgun Gothic"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def _blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _solid_rect(slide, left, top, width, height, color: RGBColor):
    shape = slide.shapes.add_shape(1, left, top, width, height)  # MSO_SHAPE.RECTANGLE = 1
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def _bg(slide):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG
    # Soft side panels for depth (atmosphere without clutter)
    _solid_rect(slide, Inches(0), Inches(0), Inches(0.18), SLIDE_H, ACCENT)
    _solid_rect(slide, Inches(0.18), Inches(0), Inches(0.55), SLIDE_H, BG_SOFT)
    _solid_rect(slide, Inches(12.6), Inches(0), Inches(0.733), SLIDE_H, BG_SOFT)


def _box(
    slide,
    left,
    top,
    width,
    height,
    text: str,
    *,
    size=40,
    bold=True,
    color=FG,
    align=PP_ALIGN.CENTER,
    v_anchor=MSO_ANCHOR.MIDDLE,
    name: str | None = None,
):
    shape = slide.shapes.add_textbox(left, top, width, height)
    if name:
        shape.name = name
    tf = shape.text_frame
    tf.word_wrap = True
    try:
        tf.vertical_anchor = v_anchor
    except Exception:
        pass
    p = tf.paragraphs[0]
    p.alignment = align
    try:
        p.line_spacing = 1.5
    except Exception:
        pass
    run = p.add_run()
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return shape


def _gold_rule(slide, left, top, width):
    """Thin accent rule under section labels."""
    line = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT,
        left,
        top,
        left + width,
        top,
    )
    line.line.color.rgb = ACCENT
    line.line.width = Pt(1.75)
    return line


def _section_label(slide, text: str, *, top=Inches(0.42)):
    _box(slide, Inches(1.05), top, Inches(11.1), Inches(0.42), text, size=22, bold=False, color=ACCENT)
    _gold_rule(slide, Inches(5.4), top + Inches(0.48), Inches(2.5))


def _hero_token(slide, token: str, *, top=Inches(2.6), height=Inches(1.4), size=54, name: str | None = None):
    return _box(
        slide,
        Inches(1.05),
        top,
        Inches(11.1),
        height,
        token,
        size=size,
        bold=True,
        color=FG,
        name=name,
    )


def _body_token(slide, token: str, *, top=Inches(2.2), height=Inches(4.6), size=40, name: str | None = None):
    return _box(
        slide,
        Inches(1.05),
        top,
        Inches(11.1),
        height,
        token,
        size=size,
        bold=True,
        color=FG,
        v_anchor=MSO_ANCHOR.TOP,
        name=name,
    )


def _title_slide(prs, section: str, token: str, *, subtitle: str = "", token_name: str | None = None):
    slide = _blank(prs)
    _bg(slide)
    _section_label(slide, section)
    if subtitle:
        _box(slide, Inches(1.05), Inches(1.15), Inches(11.1), Inches(0.45), subtitle, size=24, bold=False, color=MUTED)
        _hero_token(slide, token, top=Inches(2.8), name=token_name)
    else:
        _hero_token(slide, token, top=Inches(2.9), name=token_name)
    return slide


def _lyrics_slide(prs, section: str, title_token: str, lyrics_token: str, *, lyrics_name: str | None = None):
    slide = _blank(prs)
    _bg(slide)
    _section_label(slide, section)
    _box(slide, Inches(1.05), Inches(1.1), Inches(11.1), Inches(0.7), title_token, size=32, bold=True, color=MUTED)
    _body_token(slide, lyrics_token, top=Inches(1.95), height=Inches(4.9), size=40, name=lyrics_name)
    return slide


def _reading_slide(prs, section: str, title_token: str, body_token: str, *, body_name: str | None = None, body_size=36):
    slide = _blank(prs)
    _bg(slide)
    _section_label(slide, section)
    _box(slide, Inches(1.05), Inches(1.1), Inches(11.1), Inches(0.65), title_token, size=36, bold=True, color=FG)
    _body_token(slide, body_token, top=Inches(1.95), height=Inches(4.9), size=body_size, name=body_name)
    return slide


def build_master_pptx(path: Path) -> Path:
    """
    Build a polished 16:9 master worship deck with injection tokens including:
    {{HYMN_1}}, {{HYMN_1_LYRICS}}, {{RESPONSIVE}}, {{BIBLE_TEXT}},
    {{SERMON_TITLE}}, {{HYMN_2}}.
    """
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    # ── Cover ──────────────────────────────────────────────
    s = _blank(prs)
    _bg(s)
    _box(s, Inches(1.05), Inches(1.35), Inches(11.1), Inches(0.45), "{{CHURCH_EN}}", size=22, bold=False, color=ACCENT)
    _box(s, Inches(1.05), Inches(1.95), Inches(11.1), Inches(0.95), "{{CHURCH_KO}}", size=54, bold=True, color=FG)
    _gold_rule(s, Inches(5.4), Inches(3.1), Inches(2.5))
    _box(s, Inches(1.05), Inches(3.4), Inches(11.1), Inches(0.7), "{{SERVICE_TITLE}}", size=40, bold=True, color=FG)
    _box(s, Inches(1.05), Inches(4.35), Inches(11.1), Inches(0.9), "{{META_LINE}}", size=28, bold=False, color=MUTED)

    # ── Order ──────────────────────────────────────────────
    _reading_slide(prs, "예배 순서  ·  Order of Worship", "주일 예배", "{{ORDER_TEXT}}", body_size=28)

    # ── 1. Praise — requested tokens HYMN_1 / HYMN_1_LYRICS ─
    _title_slide(prs, "1. 찬양과 기도", "{{HYMN_1}}", subtitle="Praise & Prayer", token_name="HYMN_1")
    _lyrics_slide(prs, "1. 찬양과 기도  ·  가사", "{{HYMN_1}}", "{{HYMN_1_LYRICS}}", lyrics_name="HYMN_1_LYRICS")
    _lyrics_slide(prs, "1. 찬양과 기도  ·  가사 (계속)", "{{HYMN_1}}", "{{HYMN_1_LYRICS_2}}")

    # ── 2. Creed ───────────────────────────────────────────
    _reading_slide(prs, "2. 사도신경", "The Apostles' Creed", "{{APOSTLES_CREED}}", body_size=32)

    # ── 3. Responsive — requested token RESPONSIVE ─────────
    _reading_slide(
        prs,
        "3. 교독문",
        "{{RESPONSIVE_TITLE}}",
        "{{RESPONSIVE}}",
        body_name="RESPONSIVE",
        body_size=36,
    )

    # ── 4. Hymn — requested token HYMN_2 ───────────────────
    _title_slide(prs, "4. 찬송가", "{{HYMN_2}}", subtitle="Hymn", token_name="HYMN_2")
    _lyrics_slide(prs, "4. 찬송가  ·  가사", "{{HYMN_2}}", "{{HYMN_2_LYRICS}}", lyrics_name="HYMN_2_LYRICS")

    # ── 5. Prayer ──────────────────────────────────────────
    _reading_slide(prs, "5. 예배의 기도", "{{PRAYER_LEADER}}", "{{PRAYER_TEXT}}", body_size=36)

    # ── 6. Scripture — requested token BIBLE_TEXT ──────────
    _reading_slide(
        prs,
        "6. 오늘의 말씀",
        "{{SCRIPTURE_REF}}",
        "{{BIBLE_TEXT}}",
        body_name="BIBLE_TEXT",
        body_size=36,
    )

    # ── 7. Response hymn ───────────────────────────────────
    _title_slide(prs, "7. 찬양", "{{HYMN_3}}", subtitle="Hymn of Response", token_name="HYMN_3")
    _lyrics_slide(prs, "7. 찬양  ·  가사", "{{HYMN_3}}", "{{HYMN_3_LYRICS}}")

    # ── 8. Sermon — requested token SERMON_TITLE ───────────
    s = _blank(prs)
    _bg(s)
    _section_label(s, "8. 생명의 말씀")
    _box(s, Inches(1.05), Inches(1.2), Inches(11.1), Inches(0.45), "{{SCRIPTURE_REF}}", size=24, bold=False, color=MUTED)
    _hero_token(s, "{{SERMON_TITLE}}", top=Inches(2.3), height=Inches(1.6), size=54, name="SERMON_TITLE")
    _box(s, Inches(1.05), Inches(4.2), Inches(11.1), Inches(0.6), "{{SERMON_SUBTITLE}}", size=32, bold=False, color=MUTED)
    _box(s, Inches(1.05), Inches(5.0), Inches(11.1), Inches(0.55), "{{PREACHER}}", size=28, bold=False, color=ACCENT)

    # ── 9. Offering ────────────────────────────────────────
    _title_slide(prs, "9. 감사와 봉헌", "{{HYMN_4}}", subtitle="Offering", token_name="HYMN_4")
    _lyrics_slide(prs, "9. 감사와 봉헌  ·  가사", "{{HYMN_4}}", "{{HYMN_4_LYRICS}}")

    # ── 10. Benediction ────────────────────────────────────
    _reading_slide(prs, "10. 축도", "{{BENEDICTION}}", "{{CLOSING_NOTE}}", body_size=36)

    # ── Announcements ──────────────────────────────────────
    _reading_slide(prs, "소식 · 광고", "Announcements", "{{ANNOUNCEMENTS}}", body_size=32)

    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return path


def build_master_pdf(path: Path) -> Path:
    """Visual shell only (borders/fold). Content slots live in master_bulletin_slots.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter)
    page_w, page_h = letter
    cream = HexColor("#FBF8F1")
    border = HexColor("#3D5A40")
    rule = HexColor("#B7A992")
    muted = HexColor("#5A5A5A")

    def paint_shell(page_label: str, *, fold: bool):
        c.setFillColor(cream)
        c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
        c.setStrokeColor(border)
        c.setLineWidth(1.4)
        inset = 20
        c.rect(inset, inset, page_w - 2 * inset, page_h - 2 * inset, fill=0, stroke=1)
        c.setLineWidth(0.5)
        c.rect(inset + 4, inset + 4, page_w - 2 * inset - 8, page_h - 2 * inset - 8, fill=0, stroke=1)
        if fold:
            c.setStrokeColor(rule)
            c.setDash(1, 3)
            c.setLineWidth(0.4)
            c.line(page_w / 2, inset + 8, page_w / 2, page_h - inset - 8)
            c.setDash()
        c.setFillColor(muted)
        c.setFont("Helvetica", 8)
        c.drawCentredString(page_w / 2, page_h - 28, page_label)

    paint_shell("SUNDAY BULLETIN  ·  MASTER PAGE 1 (COVER / ORDER)", fold=True)
    c.showPage()
    paint_shell("SUNDAY BULLETIN  ·  MASTER PAGE 2 (READINGS / NEWS)", fold=False)
    c.save()

    slots = {
        "page_size": "letter",
        "slots": [
            {"page": 1, "key": "CHURCH_EN", "x": 40, "y": 720, "w": 250, "h": 14, "size": 9, "align": "center", "bold": True},
            {"page": 1, "key": "CHURCH_KO", "x": 40, "y": 698, "w": 250, "h": 20, "size": 14, "align": "center", "bold": True},
            {"page": 1, "key": "SERVICE_TITLE", "x": 40, "y": 674, "w": 250, "h": 16, "size": 12, "align": "center", "bold": True},
            {"page": 1, "key": "META_LINE", "x": 40, "y": 656, "w": 250, "h": 14, "size": 9, "align": "center", "bold": False},
            {"page": 1, "key": "ORDER_TEXT", "x": 40, "y": 80, "w": 250, "h": 560, "size": 9, "align": "left", "bold": False, "multiline": True},
            {"page": 1, "key": "PRAISE_HYMN", "x": 330, "y": 700, "w": 240, "h": 36, "size": 10, "align": "left", "bold": True, "prefix": "1. "},
            {"page": 1, "key": "HYMN", "x": 330, "y": 650, "w": 240, "h": 36, "size": 10, "align": "left", "bold": True, "prefix": "4. "},
            {"page": 1, "key": "RESPONSE_HYMN", "x": 330, "y": 600, "w": 240, "h": 36, "size": 10, "align": "left", "bold": True, "prefix": "7. "},
            {"page": 1, "key": "SERMON_TITLE", "x": 330, "y": 530, "w": 240, "h": 50, "size": 10, "align": "left", "bold": True, "prefix": "8. ", "multiline": True},
            {"page": 1, "key": "OFFERING_HYMN", "x": 330, "y": 470, "w": 240, "h": 36, "size": 10, "align": "left", "bold": True, "prefix": "9. "},
            {"page": 1, "key": "BENEDICTION", "x": 330, "y": 100, "w": 240, "h": 60, "size": 10, "align": "left", "bold": False, "prefix": "10. ", "multiline": True},
            {"page": 2, "key": "SCRIPTURE_REF", "x": 40, "y": 720, "w": 530, "h": 18, "size": 12, "align": "left", "bold": True, "prefix": "6. "},
            {"page": 2, "key": "SCRIPTURE_TEXT", "x": 40, "y": 420, "w": 530, "h": 280, "size": 10, "align": "left", "bold": False, "multiline": True},
            {"page": 2, "key": "RESPONSIVE_TITLE", "x": 40, "y": 390, "w": 530, "h": 16, "size": 11, "align": "left", "bold": True, "prefix": "3. "},
            {"page": 2, "key": "RESPONSIVE_BODY", "x": 40, "y": 250, "w": 530, "h": 130, "size": 10, "align": "left", "bold": False, "multiline": True},
            {"page": 2, "key": "PRAYER_TEXT", "x": 40, "y": 150, "w": 260, "h": 80, "size": 9, "align": "left", "bold": False, "multiline": True},
            {"page": 2, "key": "APOSTLES_CREED", "x": 310, "y": 150, "w": 260, "h": 80, "size": 8, "align": "left", "bold": False, "multiline": True},
            {"page": 2, "key": "ANNOUNCEMENTS", "x": 40, "y": 40, "w": 530, "h": 95, "size": 10, "align": "left", "bold": False, "multiline": True},
        ],
    }
    (TEMPLATES / "master_bulletin_slots.json").write_text(
        json.dumps(slots, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    pptx = build_master_pptx(TEMPLATES / "master_worship.pptx")
    pdf = build_master_pdf(TEMPLATES / "master_bulletin.pdf")
    print("wrote", pptx)
    print("wrote", pdf)
    print("wrote", TEMPLATES / "master_bulletin_slots.json")
