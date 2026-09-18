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
try:
    TEMPLATES.mkdir(exist_ok=True)
except OSError:
    pass

# Bump when slide background / type system changes — app auto-reloads master
MASTER_DESIGN_VERSION = "2026-08-24-worship-prep"

# ── Design system: senior-friendly sanctuary projection ───
# Deep slate + warm ivory type + champagne gold + dusty rose accents.
BG = RGBColor(0x0E, 0x12, 0x18)          # deep slate base
BG_WASH = RGBColor(0x18, 0x1F, 0x2A)      # soft upper wash
BG_PANEL = RGBColor(0x15, 0x1C, 0x26)     # mid field
BG_READ = RGBColor(0x1A, 0x23, 0x2E)      # reading column plane
BG_FOOT = RGBColor(0x0A, 0x0D, 0x12)      # footer vignette
FG = RGBColor(0xFF, 0xF8, 0xF0)           # warm ivory (high contrast)
MUTED = RGBColor(0xB6, 0xC0, 0xCA)        # soft secondary
ACCENT = RGBColor(0xD8, 0xB8, 0x7A)       # champagne gold
ACCENT_SOFT = RGBColor(0x7E, 0x9E, 0x90)  # soft sage edge
ROSE = RGBColor(0xC4, 0x8A, 0x94)         # dusty rose
ROSE_PETAL = RGBColor(0xD6, 0xA4, 0xAC)   # lighter petal
ROSE_DEEP = RGBColor(0x8E, 0x5E, 0x6A)     # rose stem/edge
LEADER_RED = RGBColor(0xFF, 0x5C, 0x5C)   # 교독문 인도자
CONG_YELLOW = RGBColor(0xFF, 0xE0, 0x66)  # 교독문 회중
FONT = "Malgun Gothic"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

# Optically centered reading column (not flush-left)
MARGIN_L = Inches(1.85)
CONTENT_W = Inches(9.6)
MARGIN_R_EDGE = MARGIN_L + CONTENT_W

# Type scale (pt) — senior-first, large and calm
SIZE_EYEBROW = 16
SIZE_COVER_EN = 34  # Full "Fullerton Villa Community Church" (wraps cleanly)
SIZE_COVER_BRAND = 54
SIZE_COVER_LEADER = 34
SIZE_COVER_SUB = 30
SIZE_ANNOUNCE = 44
SIZE_SERMON = 52
SIZE_TITLE = 36
SIZE_BODY = 28
SIZE_BODY_DENSE = 28
SIZE_META = 22

# Vertical rhythm (inches from top)
Y_EYEBROW = 0.42
Y_RULE = 0.82
Y_TITLE = 1.05
Y_BODY = 2.00  # breathing room under title
H_TITLE = 0.85  # room for 교독문 번호·성경 / 성경 구절 without "…"
H_BODY = 4.70
HYMN_LINES_PER_SLIDE = 4
CREED_LINES_PER_SLIDE = 4
BIBLE_LINES_PER_SLIDE = 4


def _blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _solid_rect(slide, left, top, width, height, color: RGBColor):
    shape = slide.shapes.add_shape(1, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def _oval(slide, left, top, width, height, color: RGBColor):
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def _rose(slide, cx, cy, *, scale: float = 1.0):
    """Simple 5-petal dusty rose — quiet corner accent, not a sticker."""
    s = float(scale)
    petal = Inches(0.15 * s)
    for dx, dy in (
        (0.0, -0.11),
        (0.10, -0.03),
        (0.07, 0.09),
        (-0.07, 0.09),
        (-0.10, -0.03),
    ):
        _oval(
            slide,
            cx + Inches(dx * s) - petal / 2,
            cy + Inches(dy * s) - petal / 2,
            petal,
            petal,
            ROSE_PETAL,
        )
    bud = Inches(0.11 * s)
    _oval(slide, cx - bud / 2, cy - bud / 2, bud, bud, ROSE)
    # Small leaf
    leaf_w, leaf_h = Inches(0.14 * s), Inches(0.07 * s)
    _oval(slide, cx + Inches(0.11 * s), cy + Inches(0.05 * s), leaf_w, leaf_h, ACCENT_SOFT)


def _corner_bracket_mirrored(slide, left, top, arm=Inches(0.35), *, weight=1.15, corner: str = "tl"):
    """Paired L-brackets at reading-column corners (tl/tr/bl/br)."""
    corner = (corner or "tl").lower()
    if corner == "tl":
        _hairline(slide, left, top, arm, weight=weight)
        _vline(slide, left, top, arm, weight=weight)
    elif corner == "tr":
        _hairline(slide, left - arm, top, arm, weight=weight)
        _vline(slide, left, top, arm, weight=weight)
    elif corner == "bl":
        _hairline(slide, left, top, arm, weight=weight)
        _vline(slide, left, top - arm, arm, weight=weight)
    elif corner == "br":
        _hairline(slide, left - arm, top, arm, weight=weight)
        _vline(slide, left, top - arm, arm, weight=weight)


def _pair_ornaments(slide, motif: str) -> None:
    """Quiet symmetric accents on content slides (never on cover)."""
    if (motif or "").lower() == "cover":
        return

    # One rose pair bottom corners + light top ticks — avoid clutter
    _rose(slide, Inches(0.78), Inches(6.60), scale=0.85)
    _rose(slide, Inches(12.52), Inches(6.60), scale=0.85)

    arm = Inches(0.30)
    _corner_bracket_mirrored(slide, MARGIN_L - Inches(0.10), Inches(0.40), arm=arm, corner="tl")
    _corner_bracket_mirrored(slide, MARGIN_R_EDGE + Inches(0.10), Inches(0.40), arm=arm, corner="tr")
    _diamond(slide, MARGIN_L - Inches(0.50), Inches(3.65), half=Inches(0.045))
    _diamond(slide, MARGIN_R_EDGE + Inches(0.50), Inches(3.65), half=Inches(0.045))


def _bg(slide, motif: str = "default"):
    """
    Senior-friendly projection field:
    layered slate wash + soft reading plane + gold/rose edges.
    Atmosphere without competing with large ivory text.
    """
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG

    # Soft vertical wash (stepped bands ≈ gentle gradient)
    _solid_rect(slide, Inches(0), Inches(0), SLIDE_W, Inches(2.35), BG_WASH)
    _solid_rect(slide, Inches(0), Inches(2.15), SLIDE_W, Inches(2.9), BG_PANEL)
    _solid_rect(slide, Inches(0), Inches(6.50), SLIDE_W, Inches(1.0), BG_FOOT)

    # Soft reading column — lifts lyrics/scripture off the field
    _solid_rect(
        slide,
        MARGIN_L - Inches(0.35),
        Inches(0.28),
        CONTENT_W + Inches(0.70),
        Inches(6.85),
        BG_READ,
    )

    # Paired vertical edges: gold/sage left ↔ rose right (content slides)
    _solid_rect(slide, Inches(0), Inches(0), Inches(0.14), SLIDE_H, ACCENT)
    _solid_rect(slide, Inches(0.14), Inches(0), Inches(0.09), SLIDE_H, ACCENT_SOFT)
    if (motif or "").lower() != "cover":
        _solid_rect(slide, Inches(13.10), Inches(0), Inches(0.10), SLIDE_H, ROSE)
        _solid_rect(slide, Inches(13.20), Inches(0), Inches(0.13), SLIDE_H, ROSE_DEEP)

    # Top / bottom gold hairlines framing the reading plane
    _hairline(
        slide,
        MARGIN_L - Inches(0.15),
        Inches(0.32),
        CONTENT_W + Inches(0.30),
        weight=1.1,
    )
    _hairline(
        slide,
        MARGIN_L - Inches(0.15),
        Inches(7.05),
        CONTENT_W + Inches(0.30),
        weight=1.1,
    )

    # Quiet footer band
    _solid_rect(slide, Inches(0.26), Inches(7.18), Inches(13.07), Inches(0.32), BG_FOOT)
    _pair_ornaments(slide, motif)
    _motif(slide, motif)


def _vline(slide, left, top, height, *, weight=1.1, color=ACCENT):
    line = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT,
        left,
        top,
        left,
        top + height,
    )
    line.line.color.rgb = color
    line.line.width = Pt(weight)
    return line


def _corner_bracket(slide, left, top, arm=Inches(0.35), *, weight=1.15):
    """Small L-shaped corner mark."""
    _hairline(slide, left, top, arm, weight=weight)
    _vline(slide, left, top, arm, weight=weight)


def _diamond(slide, cx, cy, half=Inches(0.09)):
    """Tiny diamond gem."""
    from pptx.enum.shapes import MSO_SHAPE

    size = half * 2
    shape = slide.shapes.add_shape(
        MSO_SHAPE.DIAMOND,
        cx - half,
        cy - half,
        size,
        size,
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = ACCENT
    shape.line.fill.background()
    return shape


def _soft_cross(slide, cx, cy, arm=Inches(0.22), *, weight=1.3):
    _hairline(slide, cx - arm, cy, arm * 2, weight=weight)
    _vline(slide, cx, cy - arm, arm * 2, weight=weight)


def _motif_for_prefix(prefix: str) -> str:
    """Map continuation-slide series → decorative motif name."""
    if "LYRICS" in (prefix or ""):
        return "verse"
    if prefix == "APOSTLES_CREED":
        return "creed"
    if prefix == "RESPONSIVE":
        return "dialogue"
    if (prefix or "").startswith("BIBLE"):
        return "word"
    return "default"


def _motif(slide, kind: str) -> None:
    """
    One quiet geometric accent per slide family — keeps projection from feeling flat
    without competing with the reading text.
    """
    kind = (kind or "default").lower()
    cx = MARGIN_L + CONTENT_W / 2

    if kind in {"cover", "default"}:
        # Soft top and bottom frame ticks
        _corner_bracket(slide, MARGIN_L, Inches(0.55))
        _corner_bracket(slide, MARGIN_R_EDGE - Inches(0.35), Inches(0.55))
        _hairline(slide, cx - Inches(0.55), Inches(6.85), Inches(1.1), weight=1.0)
        return

    if kind == "order":
        # Vertical step rail — nine quiet ticks for the nine-fold order
        rail_x = MARGIN_L - Inches(0.28)
        y0 = Inches(2.05)
        for i in range(9):
            y = y0 + Inches(0.45) * i
            _hairline(slide, rail_x, y, Inches(0.18), weight=1.35)
        return

    if kind == "verse":
        # Paired slim reading rails beside lyrics
        rail_h = Inches(H_BODY - 0.35)
        _vline(slide, MARGIN_L - Inches(0.18), Inches(Y_BODY), rail_h, weight=1.4)
        _vline(slide, MARGIN_R_EDGE + Inches(0.18), Inches(Y_BODY), rail_h, weight=1.4)
        _diamond(slide, MARGIN_L - Inches(0.18), Inches(Y_BODY) - Inches(0.12), half=Inches(0.055))
        _diamond(slide, MARGIN_R_EDGE + Inches(0.18), Inches(Y_BODY) - Inches(0.12), half=Inches(0.055))
        return

    if kind == "creed":
        # Paired soft crosses flanking the creed title band
        _soft_cross(slide, cx - Inches(1.55), Inches(1.78), arm=Inches(0.16), weight=1.2)
        _soft_cross(slide, cx + Inches(1.55), Inches(1.78), arm=Inches(0.16), weight=1.2)
        return

    if kind == "dialogue":
        # 교독문: paired red (인도자) + yellow (회중) legend marks
        _solid_rect(slide, cx - Inches(1.15), Inches(1.78), Inches(0.28), Inches(0.12), LEADER_RED)
        _solid_rect(
            slide,
            cx + Inches(0.87),
            Inches(1.78),
            Inches(0.28),
            Inches(0.12),
            CONG_YELLOW,
        )
        rail_h = Inches(H_BODY - 0.4)
        _vline(slide, MARGIN_L - Inches(0.18), Inches(Y_BODY), rail_h, weight=1.6)
        _vline(slide, MARGIN_R_EDGE + Inches(0.18), Inches(Y_BODY), rail_h, weight=1.6)
        return

    if kind == "pray":
        # Paired contemplative dots
        for dx in (-0.55, -0.28, 0.28, 0.55):
            _diamond(slide, cx + Inches(dx), Inches(1.78), half=Inches(0.045))
        return

    if kind == "word":
        # Paired corner brackets framing the scripture field
        y = Inches(Y_BODY) - Inches(0.12)
        _corner_bracket_mirrored(slide, MARGIN_L - Inches(0.08), y, arm=Inches(0.35), corner="tl")
        _corner_bracket_mirrored(slide, MARGIN_R_EDGE + Inches(0.08), y, arm=Inches(0.35), corner="tr")
        return

    if kind == "sermon":
        # Quiet paired frame — title sits in the middle
        _hairline(slide, cx - Inches(1.4), Inches(2.05), Inches(1.0), weight=1.1)
        _hairline(slide, cx + Inches(0.4), Inches(2.05), Inches(1.0), weight=1.1)
        _diamond(slide, cx - Inches(1.55), Inches(2.05), half=Inches(0.055))
        _diamond(slide, cx + Inches(1.55), Inches(2.05), half=Inches(0.055))
        return

    if kind == "give":
        _hairline(slide, cx - Inches(1.2), Inches(1.78), Inches(0.9), weight=1.2)
        _hairline(slide, cx + Inches(0.3), Inches(1.78), Inches(0.9), weight=1.2)
        _diamond(slide, cx - Inches(1.35), Inches(1.78), half=Inches(0.05))
        _diamond(slide, cx + Inches(1.35), Inches(1.78), half=Inches(0.05))
        return

    if kind == "bless":
        _soft_cross(slide, cx - Inches(1.4), Inches(1.78), arm=Inches(0.15), weight=1.15)
        _soft_cross(slide, cx + Inches(1.4), Inches(1.78), arm=Inches(0.15), weight=1.15)
        _hairline(slide, cx - Inches(0.9), Inches(6.7), Inches(1.8), weight=1.1)
        return

    if kind == "news":
        _solid_rect(slide, MARGIN_L, Inches(1.72), CONTENT_W, Inches(0.04), ACCENT)
        return

    if kind == "announce":
        _diamond(slide, cx - Inches(1.2), Inches(2.55), half=Inches(0.055))
        _diamond(slide, cx + Inches(1.2), Inches(2.55), half=Inches(0.055))
        return

    # Fallback: paired diamonds under eyebrow
    _diamond(slide, cx - Inches(0.55), Inches(1.78), half=Inches(0.05))
    _diamond(slide, cx + Inches(0.55), Inches(1.78), half=Inches(0.05))


def _hairline(slide, left, top, width, *, weight=1.25):
    line = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT,
        left,
        top,
        left + width,
        top,
    )
    line.line.color.rgb = ACCENT
    line.line.width = Pt(weight)
    return line


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
    align=PP_ALIGN.LEFT,
    v_anchor=MSO_ANCHOR.TOP,
    name: str | None = None,
    line_spacing=1.35,
    space_after=8,
):
    if left < MARGIN_L:
        left = MARGIN_L
    if left + width > MARGIN_R_EDGE:
        width = MARGIN_R_EDGE - left
    if top < Inches(0.22):
        top = Inches(0.22)
    if top + height > SLIDE_H - Inches(0.35):
        height = SLIDE_H - Inches(0.35) - top

    shape = slide.shapes.add_textbox(left, top, width, height)
    if name:
        shape.name = name
    tf = shape.text_frame
    tf.word_wrap = True
    try:
        tf.auto_size = None
    except Exception:
        pass
    try:
        tf.vertical_anchor = v_anchor
    except Exception:
        pass
    try:
        tf.margin_left = Inches(0.02)
        tf.margin_right = Inches(0.08)
        tf.margin_top = Inches(0.02)
        tf.margin_bottom = Inches(0.02)
    except Exception:
        pass
    p = tf.paragraphs[0]
    p.alignment = align
    try:
        p.line_spacing = line_spacing
        p.space_after = Pt(space_after)
    except Exception:
        pass
    run = p.add_run()
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return shape


def _eyebrow(slide, text: str):
    """Section step — small gold label, centered with the reading column."""
    if not (text or "").strip():
        return
    _box(
        slide,
        MARGIN_L,
        Inches(Y_EYEBROW),
        CONTENT_W,
        Inches(0.32),
        text,
        size=SIZE_EYEBROW,
        bold=False,
        color=ACCENT,
        align=PP_ALIGN.CENTER,
        v_anchor=MSO_ANCHOR.MIDDLE,
        line_spacing=1.0,
        space_after=0,
    )
    # Centered short rule under eyebrow
    rule_w = Inches(1.8)
    _hairline(slide, MARGIN_L + (CONTENT_W - rule_w) / 2, Inches(Y_RULE), rule_w, weight=1.35)


def _title_left(
    slide,
    token: str,
    *,
    top=Inches(Y_TITLE),
    height=Inches(H_TITLE),
    size=SIZE_TITLE,
    name: str | None = None,
    color=FG,
):
    """Title above body — centered in the reading column."""
    return _box(
        slide,
        MARGIN_L,
        top,
        CONTENT_W,
        height,
        token,
        size=size,
        bold=True,
        color=color,
        align=PP_ALIGN.CENTER,
        v_anchor=MSO_ANCHOR.MIDDLE,
        name=name,
        line_spacing=1.15,
        space_after=0,
    )


def _body_left(
    slide,
    token: str,
    *,
    top=Inches(Y_BODY),
    height=Inches(H_BODY),
    size=SIZE_BODY,
    name: str | None = None,
    align=PP_ALIGN.CENTER,
):
    """Lyrics / scripture / creed — usually centered; 교독문 may be left."""
    return _box(
        slide,
        MARGIN_L,
        top,
        CONTENT_W,
        height,
        token,
        size=size,
        bold=False,
        color=FG,
        align=align,
        v_anchor=MSO_ANCHOR.TOP,
        name=name,
        line_spacing=1.30,
        space_after=6,
    )


# Back-compat alias used by pptx_generator continuation slides
_section_label = _eyebrow


def _title_slide(prs, section: str, token: str, *, token_name: str | None = None, motif: str = "announce"):
    """Centered announcement beat — one section, one title, calm space."""
    slide = _blank(prs)
    _bg(slide, motif)
    _eyebrow(slide, section)
    _title_left(
        slide,
        token,
        top=Inches(2.85),
        height=Inches(1.5),
        size=SIZE_ANNOUNCE,
        name=token_name,
        color=FG,
    )
    rule_w = Inches(1.5)
    _hairline(slide, MARGIN_L + (CONTENT_W - rule_w) / 2, Inches(4.55), rule_w, weight=1.2)
    return slide


def _hymn_intro_slide(
    prs,
    section: str,
    token: str,
    *,
    token_name: str | None = None,
    motif: str = "announce",
):
    """
    Hymn cue only — number/title on one slide.
    Actual lyrics are played from a separate hymn PPT.
    """
    slide = _blank(prs)
    _bg(slide, motif)
    _eyebrow(slide, section)
    _title_left(
        slide,
        token,
        top=Inches(2.55),
        height=Inches(1.7),
        size=SIZE_ANNOUNCE,
        name=token_name,
        color=FG,
    )
    rule_w = Inches(1.5)
    _hairline(slide, MARGIN_L + (CONTENT_W - rule_w) / 2, Inches(4.55), rule_w, weight=1.2)
    return slide


def _reading_slide(
    prs,
    section: str,
    title_token: str,
    body_token: str,
    *,
    body_name: str | None = None,
    body_size=SIZE_BODY,
    motif: str = "default",
    body_align=None,
):
    slide = _blank(prs)
    _bg(slide, motif)
    _eyebrow(slide, section)
    _title_left(slide, title_token, color=FG, size=SIZE_TITLE)
    _body_left(
        slide,
        body_token,
        size=body_size,
        name=body_name,
        align=body_align if body_align is not None else PP_ALIGN.CENTER,
    )
    return slide


def build_master_pptx(path: Path) -> Path:
    """
    Professional 16:9 worship master.
    Centered reading column; one seed slide per series (extra pages auto-added).
    """
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    # ── Cover: brand centered, basic info centered (original rhythm) ─
    s = _blank(prs)
    _bg(s, "cover")

    cover_l, cover_w = MARGIN_L, CONTENT_W

    # English — higher + larger, centered
    _box(
        s,
        cover_l,
        Inches(0.70),
        cover_w,
        Inches(0.88),
        "{{CHURCH_EN}}",
        size=SIZE_COVER_EN,
        bold=False,
        color=ACCENT,
        align=PP_ALIGN.CENTER,
        v_anchor=MSO_ANCHOR.MIDDLE,
        line_spacing=1.1,
        space_after=0,
        name="CHURCH_EN",
    )
    _box(
        s,
        cover_l,
        Inches(1.90),
        cover_w,
        Inches(0.88),
        "{{CHURCH_KO}}",
        size=SIZE_COVER_BRAND,
        bold=True,
        color=FG,
        align=PP_ALIGN.CENTER,
        v_anchor=MSO_ANCHOR.MIDDLE,
        line_spacing=1.05,
        space_after=0,
        name="CHURCH_KO",
    )
    rule_w = Inches(2.2)
    _hairline(s, cover_l + (cover_w - rule_w) / 2, Inches(2.95), rule_w, weight=1.5)

    # Title + basic info under the rule — centered, even row spacing
    info_top = 3.18
    info_h = 0.50
    info_step = 0.58
    info_rows = (
        ("{{SERVICE_TITLE}}", "SERVICE_TITLE", SIZE_COVER_SUB, FG, True),
        ("{{DATE}}", "DATE", SIZE_META, MUTED, False),
        ("{{SERVICE_TIME}}", "SERVICE_TIME", SIZE_META, MUTED, False),
        ("{{WORSHIP_LEADER}}", "WORSHIP_LEADER", 28, FG, True),
    )
    for i, (token, name, size, color, bold) in enumerate(info_rows):
        _box(
            s,
            cover_l,
            Inches(info_top + i * info_step),
            cover_w,
            Inches(info_h),
            token,
            size=size,
            bold=bold,
            color=color,
            align=PP_ALIGN.CENTER,
            v_anchor=MSO_ANCHOR.MIDDLE,
            line_spacing=1.05,
            space_after=0,
            name=name,
        )

    # ── Order: left-aligned list in the centered column (10 numbered steps) ──
    s = _blank(prs)
    _bg(s, "order")
    _eyebrow(s, "예배 순서")
    _title_left(s, "주일 예배", color=FG, size=SIZE_TITLE)
    _box(
        s,
        MARGIN_L + Inches(0.25),
        Inches(1.95),
        CONTENT_W - Inches(0.5),
        Inches(5.0),
        "{{ORDER_TEXT}}",
        size=20,
        bold=False,
        color=FG,
        align=PP_ALIGN.LEFT,
        v_anchor=MSO_ANCHOR.TOP,
        name="ORDER_TEXT",
        line_spacing=1.22,
        space_after=4,
    )

    # ── 1. Preparation praise — up to five hymn intros ──
    for i in range(1, 6):
        _hymn_intro_slide(
            prs,
            "1. 예배 준비의 시간",
            f"{{{{HYMN_PREP_{i}}}}}",
            token_name=f"HYMN_PREP_{i}",
            motif="announce",
        )

    # ── 2. Praise — intro only (lyrics from separate hymn PPT) ──
    _hymn_intro_slide(prs, "2. 찬양과 기도", "{{HYMN_1}}", token_name="HYMN_1", motif="announce")

    # ── 3. Creed (seed; continues if long) ──────────────────
    _reading_slide(
        prs,
        "3. 사도신경",
        "{{APOSTLES_CREED_HEADING}}",
        "{{APOSTLES_CREED_1}}",
        body_name="APOSTLES_CREED_1",
        body_size=SIZE_BODY_DENSE,
        motif="creed",
    )

    # ── 3. Responsive (seed; continues if long) ─────────────
    _reading_slide(
        prs,
        "4. 교독문",
        "{{RESPONSIVE_TITLE}}",
        "{{RESPONSIVE_1}}",
        body_name="RESPONSIVE_1",
        body_size=SIZE_BODY,
        motif="dialogue",
        body_align=PP_ALIGN.LEFT,
    )

    # ── 5. Hymn — intro only ───────────────────────────────
    _hymn_intro_slide(prs, "5. 찬송가", "{{HYMN_2}}", token_name="HYMN_2", motif="announce")

    # ── 6. Prayer ──────────────────────────────────────────
    _reading_slide(
        prs, "6. 예배의 기도", "{{PRAYER_LEADER}}", "{{PRAYER_TEXT}}", body_size=SIZE_BODY, motif="pray"
    )

    # ── 7. Choir anthem — intro only ───────────────────────
    _hymn_intro_slide(prs, "7. 성가대 찬양", "{{CHOIR_ANTHEM}}", token_name="CHOIR_ANTHEM", motif="announce")

    # ── 8. Scripture (seed; continues automatically) ────────
    _reading_slide(
        prs,
        "8. 오늘의 말씀",
        "{{SCRIPTURE_REF}}",
        "{{BIBLE_TEXT_1}}",
        body_name="BIBLE_TEXT_1",
        body_size=SIZE_BODY_DENSE,
        motif="word",
    )

    # ── 9. Sermon — small "설교제목" label + centered title ──
    s = _blank(prs)
    _bg(s, "sermon")
    _eyebrow(s, "설교제목")
    _title_left(
        s,
        "{{SERMON_TITLE}}",
        top=Inches(2.45),
        height=Inches(2.2),
        size=SIZE_SERMON,
        name="SERMON_TITLE",
    )
    _box(
        s,
        MARGIN_L,
        Inches(5.0),
        CONTENT_W,
        Inches(0.4),
        "{{SERMON_SUBTITLE}}",
        size=SIZE_META,
        bold=False,
        color=MUTED,
        align=PP_ALIGN.CENTER,
        name="SERMON_SUBTITLE",
        line_spacing=1.15,
        space_after=0,
    )
    rule_w = Inches(1.6)
    _hairline(s, MARGIN_L + (CONTENT_W - rule_w) / 2, Inches(5.55), rule_w, weight=1.2)
    _box(
        s,
        MARGIN_L,
        Inches(5.8),
        CONTENT_W,
        Inches(0.4),
        "{{PREACHER}}",
        size=SIZE_META,
        bold=False,
        color=MUTED,
        align=PP_ALIGN.CENTER,
        name="PREACHER",
        line_spacing=1.1,
        space_after=0,
    )

    # ── 10. Offering — intro only ──────────────────────────
    _hymn_intro_slide(prs, "10. 감사와 봉헌", "{{HYMN_3}}", token_name="HYMN_3", motif="give")

    # ── 11. Benediction ────────────────────────────────────
    _reading_slide(
        prs,
        "11. 축도",
        "축도",
        "{{BENEDICTION_BODY}}",
        body_name="BENEDICTION_BODY",
        body_size=SIZE_BODY,
        motif="bless",
    )

    # ── Announcements ──────────────────────────────────────
    _reading_slide(
        prs,
        "12. 안내 및 광고",
        "안내 및 광고",
        "{{ANNOUNCEMENTS}}",
        body_name="ANNOUNCEMENTS",
        body_size=SIZE_BODY,
        motif="news",
    )

    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(path))
        return path
    except OSError:
        import tempfile
        tmp = Path(tempfile.gettempdir()) / "master_worship.pptx"
        prs.save(str(tmp))
        return tmp


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
            {"page": 1, "key": "SERMON_TITLE", "x": 330, "y": 530, "w": 240, "h": 50, "size": 10, "align": "left", "bold": True, "prefix": "7. ", "multiline": True},
            {"page": 1, "key": "OFFERING_HYMN", "x": 330, "y": 470, "w": 240, "h": 36, "size": 10, "align": "left", "bold": True, "prefix": "8. "},
            {"page": 1, "key": "BENEDICTION", "x": 330, "y": 100, "w": 240, "h": 60, "size": 10, "align": "left", "bold": False, "prefix": "9. ", "multiline": True},
            {"page": 2, "key": "SCRIPTURE_REF", "x": 40, "y": 720, "w": 530, "h": 18, "size": 12, "align": "left", "bold": True, "prefix": "6. "},
            {"page": 2, "key": "SCRIPTURE_TEXT", "x": 40, "y": 420, "w": 530, "h": 280, "size": 10, "align": "left", "bold": False, "multiline": True},
            {"page": 2, "key": "RESPONSIVE_TITLE", "x": 40, "y": 390, "w": 530, "h": 16, "size": 11, "align": "left", "bold": True, "prefix": "3. "},
            {"page": 2, "key": "RESPONSIVE_BODY", "x": 40, "y": 250, "w": 530, "h": 130, "size": 10, "align": "left", "bold": False, "multiline": True},
            {"page": 2, "key": "PRAYER_TEXT", "x": 40, "y": 150, "w": 260, "h": 80, "size": 9, "align": "left", "bold": False, "multiline": True},
            {"page": 2, "key": "APOSTLES_CREED", "x": 310, "y": 150, "w": 260, "h": 80, "size": 8, "align": "left", "bold": False, "multiline": True},
            {"page": 2, "key": "ANNOUNCEMENTS", "x": 40, "y": 40, "w": 530, "h": 95, "size": 10, "align": "left", "bold": False, "multiline": True},
        ],
    }
    (TEMPLATES / "master_bulletin_slots.json").write_text(json.dumps(slots, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    pptx = build_master_pptx(TEMPLATES / "master_worship.pptx")
    pdf = build_master_pdf(TEMPLATES / "master_bulletin.pdf")
    print("wrote", pptx)
    print("wrote", pdf)
    print("wrote", TEMPLATES / "master_bulletin_slots.json")
