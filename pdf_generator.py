"""Printable folded Sunday bulletin — Letter 11×8.5 landscape, duplex booklet."""

from __future__ import annotations

_PDF_VERSION = "2026-08-24-creed-word-no-hymns-v8"

from io import BytesIO
from pathlib import Path
from typing import List, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    FrameBreak,
    HRFlowable,
    Image as RLImage,
    KeepInFrame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.utils import ImageReader

from data_enrich import enrich_worship_data, hymn_label
from models import HymnEntry, WorshipData
from text_normalize import normalize_breaks

# Letter landscape — one sheet, fold in half → 4 faces
PAGE_W, PAGE_H = landscape(letter)  # 11" × 8.5"

# Refined liturgical palette (cool linen + deep teal + soft brass)
PAPER = colors.HexColor("#F4F7F5")
INK = colors.HexColor("#1A2E28")
MUTED = colors.HexColor("#5A6F66")
ACCENT = colors.HexColor("#1F5C4B")
ACCENT_SOFT = colors.HexColor("#3D7A68")
GOLD = colors.HexColor("#9A7B4F")
BAND = colors.HexColor("#E3EEE8")
BAND_DEEP = colors.HexColor("#D2E3DB")
RULE = colors.HexColor("#B9CBC2")
FOLD = colors.HexColor("#C8D6CF")
WHITE = colors.white

_FONT_READY = False
FONT = "BulletinBody"
FONT_BOLD = "BulletinBody-Bold"
FONT_DISPLAY = "BulletinDisplay"
FONT_EN = "BulletinEn"

# Panel geometry (half sheet)
MARGIN = 0.38 * inch
GUTTER = 0.22 * inch  # space around center fold
PANEL_W = PAGE_W / 2 - MARGIN - GUTTER / 2
PANEL_H = PAGE_H - 2 * MARGIN


def clean_text(text: str | None) -> str:
    """Clean _x000B_ / soft breaks into real newlines."""
    return normalize_breaks(text or "").replace("\xa0", " ").strip()


def _clean(text: str | None) -> str:
    return clean_text(text)


def _ensure_fonts() -> None:
    global _FONT_READY, FONT, FONT_BOLD, FONT_DISPLAY, FONT_EN
    if _FONT_READY:
        return
    fonts = Path(r"C:\Windows\Fonts")
    regular = fonts / "malgun.ttf"
    bold = fonts / "malgunbd.ttf"
    # Korean serif for titles (HANBatang → batang fallback)
    display_candidates = [
        fonts / "HANBatang.ttf",
        fonts / "batang.ttc",
        fonts / "malgunbd.ttf",
    ]
    en_candidates = [
        fonts / "georgia.ttf",
        fonts / "times.ttf",
        fonts / "GOTHIC.TTF",
    ]

    if regular.exists():
        pdfmetrics.registerFont(TTFont(FONT, str(regular)))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold if bold.exists() else regular)))
    else:
        FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"

    display_path = next((p for p in display_candidates if p.exists()), None)
    if display_path and display_path.suffix.lower() == ".ttf":
        try:
            pdfmetrics.registerFont(TTFont(FONT_DISPLAY, str(display_path)))
        except Exception:
            FONT_DISPLAY = FONT_BOLD
    else:
        FONT_DISPLAY = FONT_BOLD

    en_path = next((p for p in en_candidates if p.exists()), None)
    if en_path:
        try:
            pdfmetrics.registerFont(TTFont(FONT_EN, str(en_path)))
        except Exception:
            FONT_EN = FONT
    else:
        FONT_EN = FONT

    _FONT_READY = True


def _hymn_line(h: HymnEntry) -> str:
    return _clean(hymn_label(h) if h else "")


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    cleaned = _clean(text)
    html = escape(cleaned).replace("\n", "<br/>")
    return Paragraph(html or " ", style)


class _OrnamentRule(Flowable):
    """Centered double rule with a small diamond/brass accent."""

    def __init__(self, width: float = 120, space_before: float = 6, space_after: float = 8):
        super().__init__()
        self._w = float(width)
        self.width = self._w
        self.height = 10
        self.spaceBefore = space_before
        self.spaceAfter = space_after
        self.hAlign = "CENTER"

    def wrap(self, availWidth, availHeight):
        # Keep intrinsic width; hAlign=CENTER places the diamond on the panel midline.
        self.width = min(self._w, max(availWidth, 1))
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        y = self.height / 2
        mid = self.width / 2.0
        # Dual hairlines
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.7)
        c.line(0, y + 1.2, mid - 8, y + 1.2)
        c.line(mid + 8, y + 1.2, self.width, y + 1.2)
        c.setStrokeColor(ACCENT)
        c.setLineWidth(0.45)
        c.line(0, y - 1.0, mid - 8, y - 1.0)
        c.line(mid + 8, y - 1.0, self.width, y - 1.0)
        # Center diamond
        c.setFillColor(GOLD)
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.6)
        s = 2.8
        path = c.beginPath()
        path.moveTo(mid, y + s)
        path.lineTo(mid + s, y)
        path.lineTo(mid, y - s)
        path.lineTo(mid - s, y)
        path.close()
        c.drawPath(path, fill=1, stroke=1)


def _rule(width: str = "55%") -> HRFlowable:
    return HRFlowable(width=width, thickness=0.9, color=ACCENT, spaceBefore=5, spaceAfter=5, hAlign="CENTER")


def _ornament(width: float = 130) -> _OrnamentRule:
    return _OrnamentRule(width=width)


class _ChurchCrossLogo(Flowable):
    """Church mark: Latin cross in dual rings (teal + brass)."""

    def __init__(self, size: float = 42):
        super().__init__()
        self.size = float(size)
        self.width = self.size
        self.height = self.size

    def draw(self) -> None:
        c = self.canv
        s = self.size
        cx, cy = s / 2.0, s / 2.0
        # Soft filled disc
        c.setStrokeColor(ACCENT)
        c.setFillColor(WHITE)
        c.setLineWidth(1.5)
        c.circle(cx, cy, s * 0.44, stroke=1, fill=1)
        # Brass outer ring
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.85)
        c.circle(cx, cy, s * 0.44, stroke=1, fill=0)
        # Inner teal ring
        c.setStrokeColor(ACCENT_SOFT)
        c.setLineWidth(0.55)
        c.circle(cx, cy, s * 0.355, stroke=1, fill=0)
        # Latin cross
        c.setFillColor(ACCENT)
        c.setStrokeColor(ACCENT)
        arm = s * 0.105
        vert_h = s * 0.52
        horiz_w = s * 0.36
        horiz_h = s * 0.105
        cross_cy = cy + s * 0.02
        c.rect(cx - arm / 2, cross_cy - vert_h * 0.45, arm, vert_h, stroke=0, fill=1)
        c.rect(cx - horiz_w / 2, cross_cy + vert_h * 0.05, horiz_w, horiz_h, stroke=0, fill=1)


def _church_logo(size: float = 42) -> _ChurchCrossLogo:
    return _ChurchCrossLogo(size=size)


def _cover_crucifix(max_width: float = 1.85 * inch, max_height: float = 2.55 * inch) -> Flowable | None:
    """Refined crucifix art centered on the bulletin front cover."""
    path = Path(__file__).resolve().parent / "assets" / "crucifix_cover.png"
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        # Probe pixel size without relying on filesystem path (OneDrive/Unicode-safe)
        from PIL import Image as PILImage

        with PILImage.open(BytesIO(raw)) as pil:
            iw, ih = pil.size
        if iw <= 0 or ih <= 0:
            return None
        scale = min(max_width / float(iw), max_height / float(ih))
        draw_w = float(iw) * scale
        draw_h = float(ih) * scale
    except Exception:
        return None

    class _CrucifixImage(Flowable):
        def __init__(self, data: bytes, width: float, height: float):
            Flowable.__init__(self)
            self._data = data
            self.drawWidth = width
            self.drawHeight = height
            self.hAlign = "CENTER"

        def wrap(self, availWidth, availHeight):
            return self.drawWidth, self.drawHeight

        def draw(self):
            ir = ImageReader(BytesIO(self._data))
            self.canv.drawImage(
                ir,
                0,
                0,
                width=self.drawWidth,
                height=self.drawHeight,
                preserveAspectRatio=True,
                mask="auto",
            )

    return _CrucifixImage(raw, draw_w, draw_h)


def _styles() -> dict[str, ParagraphStyle]:
    _ensure_fonts()
    return {
        "face_tag": ParagraphStyle(
            "FaceTag",
            fontName=FONT_EN,
            fontSize=7,
            leading=9,
            alignment=1,
            textColor=GOLD,
            spaceAfter=6,
        ),
        "church_en": ParagraphStyle(
            "ChurchEn",
            fontName=FONT_EN,
            fontSize=14.25,
            leading=18,
            alignment=1,
            textColor=MUTED,
            spaceAfter=2,
        ),
        "church_ko": ParagraphStyle(
            "ChurchKo",
            fontName=FONT_DISPLAY,
            fontSize=14.25,
            leading=18,
            alignment=1,
            textColor=ACCENT,
            spaceAfter=0,
        ),
        "cover_leader": ParagraphStyle(
            "CoverLeader",
            fontName=FONT_BOLD,
            fontSize=17,
            leading=22,
            alignment=1,
            textColor=INK,
            spaceBefore=2,
            spaceAfter=0,
        ),
        "order_heading": ParagraphStyle(
            "OrderHeading",
            fontName=FONT_DISPLAY,
            fontSize=20,
            leading=26,
            alignment=1,
            textColor=ACCENT,
            spaceBefore=2,
            spaceAfter=2,
        ),
        "ads_heading": ParagraphStyle(
            "AdsHeading",
            fontName=FONT_DISPLAY,
            fontSize=17,
            leading=22,
            alignment=1,
            textColor=ACCENT,
            spaceBefore=4,
            spaceAfter=2,
        ),
        "ads_body": ParagraphStyle(
            "AdsBody",
            fontName=FONT,
            fontSize=11.5,
            leading=17,
            textColor=INK,
            spaceBefore=4,
            spaceAfter=4,
            leftIndent=4,
        ),
        "service": ParagraphStyle(
            "ServiceTitle",
            fontName=FONT_BOLD,
            fontSize=28.5,
            leading=34,
            alignment=1,
            textColor=ACCENT,
            spaceBefore=0,
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "Meta",
            fontName=FONT_BOLD,
            fontSize=9.5,
            leading=12,
            alignment=1,
            textColor=MUTED,
            spaceAfter=2,
        ),
        "cover_note": ParagraphStyle(
            "CoverNote",
            fontName=FONT_EN,
            fontSize=8,
            leading=11,
            alignment=1,
            textColor=MUTED,
            spaceBefore=8,
        ),
        "section": ParagraphStyle(
            "Section",
            fontName=FONT_DISPLAY,
            fontSize=11,
            leading=14,
            textColor=ACCENT,
            spaceBefore=6,
            spaceAfter=3,
        ),
        "order_left": ParagraphStyle(
            "OrderLeft",
            fontName=FONT_BOLD,
            fontSize=8.5,
            leading=20,
            textColor=INK,
        ),
        "order_right": ParagraphStyle(
            "OrderRight",
            fontName=FONT,
            fontSize=8,
            leading=20,
            textColor=MUTED,
            alignment=2,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName=FONT,
            fontSize=8.5,
            leading=12,
            textColor=INK,
            spaceAfter=3,
        ),
        "body_sm": ParagraphStyle(
            "BodySm",
            fontName=FONT,
            fontSize=7.5,
            leading=10.5,
            textColor=INK,
            spaceAfter=2,
        ),
        "body_xs": ParagraphStyle(
            "BodyXs",
            fontName=FONT,
            fontSize=6.6,
            leading=9.2,
            textColor=INK,
            spaceAfter=1.5,
        ),
        "creed_sm": ParagraphStyle(
            "CreedSm",
            fontName=FONT,
            fontSize=7.0,
            leading=9.6,
            textColor=INK,
            spaceAfter=1.5,
        ),
        "body_bold": ParagraphStyle(
            "BodyBold",
            fontName=FONT_BOLD,
            fontSize=9,
            leading=12,
            textColor=INK,
            spaceAfter=2,
        ),
        "footer": ParagraphStyle(
            "Footer",
            fontName=FONT,
            fontSize=8,
            leading=11,
            alignment=1,
            textColor=MUTED,
            spaceBefore=8,
        ),
        "empty_hint": ParagraphStyle(
            "EmptyHint",
            fontName=FONT,
            fontSize=8,
            leading=11,
            alignment=1,
            textColor=MUTED,
            spaceBefore=10,
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
        (
            "7",
            "생명의 말씀",
            _clean(data.sermon_title)
            or (_clean(data.sermon_subtitle) and f"({_clean(data.sermon_subtitle)})")
            or "",
        ),
        ("8", "감사와 봉헌", _hymn_line(data.offering_hymn)),
        ("9", "축도", _clean(data.benediction)[:48] if data.benediction else ""),
    ]


def _lyrics_block(h: HymnEntry, *, max_lines: int | None = None) -> str:
    label = _hymn_line(h)
    lines = [ln for ln in (h.lyrics or []) if str(ln).strip() or ln == ""]
    if max_lines is not None and max_lines > 0:
        lines = lines[:max_lines]
    body = _clean("\n".join(str(ln) for ln in lines))
    if not label and not body:
        return ""
    if label and body:
        return f"{label}\n{body}"
    return label or body


def _order_table(data: WorshipData, styles: dict) -> Table:
    table_data = []
    for num, title, detail in _order_items(data):
        table_data.append(
            [
                _para(f"{num}.  {title}", styles["order_left"]),
                _para(detail or " ", styles["order_right"]),
            ]
        )
    left_w = PANEL_W * 0.42
    right_w = PANEL_W * 0.55
    t = Table(table_data, colWidths=[left_w, right_w])
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, ACCENT),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, GOLD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(len(table_data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), BAND))
    t.setStyle(TableStyle(style_cmds))
    return t


def _flow_cover(data: WorshipData, styles: dict) -> list:
    """Front cover: balanced vertical rhythm — title, art, leader, church names."""
    story: list = [
        _para("COVER", styles["face_tag"]),
        Spacer(1, 5 * mm),
        _para(data.service_title or "주일 예배", styles["service"]),
    ]
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
        story.append(Spacer(1, 1.5 * mm))
        story.append(_para("  ·  ".join(meta_bits), styles["meta"]))

    story.append(Spacer(1, 4 * mm))
    story.append(_ornament(96))
    story.append(Spacer(1, 5 * mm))

    crucifix = _cover_crucifix(max_width=1.7 * inch, max_height=2.35 * inch)
    if crucifix is not None:
        story.append(
            KeepInFrame(
                PANEL_W - 8,
                2.4 * inch,
                [crucifix],
                mode="shrink",
                hAlign="CENTER",
            )
        )
    else:
        logo = _church_logo(44)
        logo.hAlign = "CENTER"
        story.append(logo)

    leader = _clean(getattr(data, "worship_leader", "") or "")
    if leader:
        label = leader if leader.startswith("인도자") else f"인도자 {leader}"
        story.append(Spacer(1, 4 * mm))
        story.append(_para(label, styles["cover_leader"]))

    # Bottom brand block — quieter weight, more air above
    story.append(Spacer(1, 11 * mm))
    story.append(_ornament(72))
    story.append(Spacer(1, 3.5 * mm))
    if _clean(data.church_name_en):
        story.append(_para(data.church_name_en, styles["church_en"]))
    story.append(_para(data.church_name_ko or "플러톤 빌라 교회", styles["church_ko"]))
    return story


def _announcement_items(text: str) -> list[str]:
    """Split announcements into bullet items (one per line / bullet)."""
    import re

    raw = _clean(text)
    if not raw:
        return []
    items: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        s = re.sub(r"^[•●▪·＊*\-–—]\s*", "", s).strip()
        if s:
            items.append(s)
    return items


def _flow_announcements(data: WorshipData, styles: dict) -> list:
    """Back cover: large centered title + senior-readable bulleted ads."""
    story: list = [
        _para("ANNOUNCEMENTS", styles["face_tag"]),
        Spacer(1, 2 * mm),
        _para("소식 · 광고", styles["ads_heading"]),
        _ornament(100),
        Spacer(1, 3 * mm),
    ]
    items = _announcement_items(data.announcements or "")
    if items:
        for item in items:
            story.append(_para(f"◆  {item}", styles["ads_body"]))
    else:
        story.append(_para("이번 주 소식이 있으면 여기에 표시됩니다.", styles["empty_hint"]))
    if _clean(data.closing_note):
        story.append(Spacer(1, 6 * mm))
        story.append(_para(data.closing_note, styles["footer"]))
    elif _clean(data.benediction):
        story.append(Spacer(1, 6 * mm))
        story.append(_para(f"축도  ·  {_clean(data.benediction)}", styles["footer"]))
    return story


def _flow_order(data: WorshipData, styles: dict) -> list:
    """Inside left panel — order of worship."""
    return [
        _para("ORDER OF WORSHIP", styles["face_tag"]),
        _para("예배 순서", styles["order_heading"]),
        _ornament(110),
        Spacer(1, 3 * mm),
        _order_table(data, styles),
        Spacer(1, 4),
        _para("사도신경 · 교독문 · 기도는 인도에 따라 함께합니다.", styles["empty_hint"]),
    ]


def _section_rule() -> HRFlowable:
    return HRFlowable(width="100%", thickness=0.55, color=GOLD, spaceBefore=1, spaceAfter=4)


def _flow_scripture_hymns(data: WorshipData, styles: dict, *, lyric_lines: int = 0) -> list:
    """Inside right panel — scripture, sermon, responsive, creed (no hymn list)."""
    del lyric_lines
    story: list = [
        _para("WORD & HYMN", styles["face_tag"]),
    ]
    ref = _clean(data.scripture_reference)
    body = _clean(data.scripture_text)
    if ref or body:
        story.append(_para("오늘의 말씀", styles["section"]))
        story.append(_section_rule())
        if ref:
            story.append(_para(ref, styles["body_bold"]))
        if body:
            style = styles["body_xs"] if len(body) > 280 else styles["body_sm"]
            story.append(_para(body, style))

    if _clean(data.sermon_title) or _clean(data.sermon_subtitle):
        story.append(_para("생명의 말씀", styles["section"]))
        story.append(_section_rule())
        if _clean(data.sermon_title):
            story.append(_para(data.sermon_title, styles["body_bold"]))
        if _clean(data.sermon_subtitle):
            story.append(_para(data.sermon_subtitle, styles["body_sm"]))

    resp_title = _clean(data.responsive_reading_title) or "교독문"
    resp_body = _clean(data.responsive_reading)
    if resp_body:
        story.append(
            _para(
                f"교독문 · {resp_title}" if resp_title != "교독문" else "교독문",
                styles["section"],
            )
        )
        story.append(_section_rule())
        style = styles["body_xs"] if len(resp_body) > 320 else styles["body_sm"]
        story.append(_para(resp_body, style))

    creed = _clean(data.apostles_creed)
    if creed:
        story.append(_para("사도신경", styles["section"]))
        story.append(_section_rule())
        story.append(_para(creed, styles["creed_sm"]))

    if len(story) <= 1:
        story.append(_para("성경 본문 · 교독문 · 사도신경을 입력하면 이 면에 표시됩니다.", styles["empty_hint"]))
    return story


def _draw_sheet_chrome(canvas, doc, *, face: str) -> None:
    """Paper wash, dual border, fold guide for Letter landscape booklet."""
    _ensure_fonts()
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # Outer teal frame
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1.15)
    canvas.rect(0.20 * inch, 0.20 * inch, PAGE_W - 0.40 * inch, PAGE_H - 0.40 * inch)
    # Inner brass hairline
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.45)
    canvas.rect(0.28 * inch, 0.28 * inch, PAGE_W - 0.56 * inch, PAGE_H - 0.56 * inch)
    # Soft header bands — more visible teal wash
    canvas.setFillColor(BAND_DEEP)
    band_h = 0.22 * inch
    y_top = PAGE_H - 0.28 * inch - band_h
    half = PAGE_W / 2 - 0.28 * inch - GUTTER / 4
    canvas.rect(0.28 * inch, y_top, half, band_h, stroke=0, fill=1)
    canvas.rect(PAGE_W / 2 + GUTTER / 4, y_top, half, band_h, stroke=0, fill=1)
    # Gold accent line under band
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.1)
    canvas.line(0.28 * inch, y_top, 0.28 * inch + half, y_top)
    canvas.line(PAGE_W / 2 + GUTTER / 4, y_top, PAGE_W / 2 + GUTTER / 4 + half, y_top)
    # Center fold
    canvas.setStrokeColor(FOLD)
    canvas.setDash(1.2, 2.2)
    canvas.setLineWidth(0.55)
    canvas.line(PAGE_W / 2, 0.30 * inch, PAGE_W / 2, PAGE_H - 0.30 * inch)
    canvas.setDash()
    canvas.setFillColor(MUTED)
    try:
        canvas.setFont(FONT_EN, 6.5)
    except Exception:
        canvas.setFont("Helvetica", 6.5)
    label = (
        "Outside  ·  Ads  |  Cover"
        if face == "outside"
        else "Inside  ·  Order of Worship  |  Scripture"
    )
    canvas.drawCentredString(PAGE_W / 2, 0.11 * inch, label)
    canvas.restoreState()


def _on_outside(canvas, doc):
    _draw_sheet_chrome(canvas, doc, face="outside")


def _on_inside(canvas, doc):
    _draw_sheet_chrome(canvas, doc, face="inside")


def _make_frames() -> tuple[Frame, Frame]:
    left = Frame(
        MARGIN,
        MARGIN,
        PANEL_W,
        PANEL_H,
        id="left",
        leftPadding=4,
        rightPadding=6,
        topPadding=2,
        bottomPadding=2,
    )
    right = Frame(
        PAGE_W / 2 + GUTTER / 2,
        MARGIN,
        PANEL_W,
        PANEL_H,
        id="right",
        leftPadding=6,
        rightPadding=4,
        topPadding=2,
        bottomPadding=2,
    )
    return left, right


def _build_story(data: WorshipData, styles: dict, *, lyric_lines: int = 0) -> list:
    """
    Booklet imposition on one Letter landscape sheet (duplex):
      Sheet 1 (outside):  [광고 | 커버]
      Sheet 2 (inside):   [예배순서 | 성경·교독·사도신경]
    Fold center → cover front, ads back; open → order left, scripture right.
    """
    del lyric_lines
    story: list = []
    # Outside left → announcements (back cover) — must not spill into cover frame
    ads = _flow_announcements(data, styles)
    story.append(
        KeepInFrame(PANEL_W - 4, PANEL_H - 4, ads, mode="shrink", hAlign="CENTER")
    )
    story.append(FrameBreak())
    # Outside right → cover (front) — keep crucifix visible
    cover = _flow_cover(data, styles)
    story.append(
        KeepInFrame(PANEL_W - 4, PANEL_H - 4, cover, mode="shrink", hAlign="CENTER")
    )
    story.append(NextPageTemplate("inside"))
    story.append(PageBreak())
    # Inside left → order
    story.append(
        KeepInFrame(
            PANEL_W - 4,
            PANEL_H - 4,
            _flow_order(data, styles),
            mode="shrink",
            hAlign="CENTER",
        )
    )
    story.append(FrameBreak())
    # Inside right → scripture / hymn titles / responsive / creed (no truncation)
    story.append(
        KeepInFrame(
            PANEL_W - 4,
            PANEL_H - 4,
            _flow_scripture_hymns(data, styles),
            mode="shrink",
            hAlign="LEFT",
        )
    )
    return story


def draw_bulletin(data: WorshipData) -> BytesIO:
    """
    Folded Letter (11×8.5) bulletin — 2 PDF pages for duplex print:
      outside [광고 | 커버], inside [예배순서 | 성경·교독·사도신경].
    """
    data = enrich_worship_data(data, allow_remote=True, force_hymn_lyrics=True)
    styles = _styles()

    buf = BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=(PAGE_W, PAGE_H),
        title=_clean(data.service_title) or "주일 예배 주보",
    )
    left, right = _make_frames()
    doc.addPageTemplates(
        [
            PageTemplate(id="outside", frames=[left, right], onPage=_on_outside),
            PageTemplate(id="inside", frames=[left, right], onPage=_on_inside),
        ]
    )
    doc.build(_build_story(data, styles))
    buf.seek(0)
    raw = buf.getvalue()
    if b"_x000B_" in raw or b"_x000b_" in raw:
        raise RuntimeError("Bulletin PDF still contains soft-break escape codes")
    buf.seek(0)
    return buf


def bulletin_preview_text(data: WorshipData) -> str:
    """Plain-text preview of the folded Letter bulletin panels."""
    data = enrich_worship_data(data, allow_remote=False, force_hymn_lyrics=True)
    lines: List[str] = [
        "【 Letter 11×8.5 접는 주보 · 양면 인쇄 】",
        "",
        "======== 겉면 (인쇄면 1) ========",
        "[왼쪽 · 뒷면] 소식 · 광고",
    ]
    if _clean(data.announcements):
        lines.extend(_clean(data.announcements).splitlines()[:10])
    else:
        lines.append("(광고 없음)")
    leader = _clean(getattr(data, "worship_leader", "") or "")
    leader_line = leader if not leader or leader.startswith("인도자") else f"인도자 {leader}"
    lines += [
        "",
        "[오른쪽 · 앞면] 커버",
        _clean(data.church_name_en),
        _clean(data.church_name_ko),
        _clean(data.service_title or "주일 예배"),
    ]
    meta = [b for b in (_clean(data.date), _clean(data.service_time), _clean(data.preacher)) if b]
    if meta:
        lines.append("  ·  ".join(meta))
    if leader_line:
        lines += ["", f"(중앙) {leader_line}"]

    lines += ["", "======== 안면 (인쇄면 2) ========", "[왼쪽] 예배 순서"]
    for num, title, detail in _order_items(data):
        row = f"{num}. {title}"
        if detail:
            row += f"  —  {detail}"
        lines.append(row)

    lines += ["", "[오른쪽] 오늘의 말씀 · 교독 · 사도신경"]
    ref = _clean(data.scripture_reference)
    body = _clean(data.scripture_text)
    if ref:
        lines.append(ref)
    if body:
        lines.extend(body.splitlines())
    lines += ["", f"생명의 말씀  ·  {_clean(data.sermon_title) or '(제목 미입력)'}"]
    resp = _clean(data.responsive_reading)
    if resp:
        lines += ["", f"교독문 · {_clean(data.responsive_reading_title) or '교독문'}", *resp.splitlines()]
    creed = _clean(data.apostles_creed)
    if creed:
        lines += ["", "사도신경", *creed.splitlines()]

    lines += ["", "※ 양면 인쇄 후 가운데를 접으면 커버가 앞, 광고가 뒤, 안쪽에 순서·성경이 나옵니다."]
    return clean_text("\n".join(lines))


def generate_worship_pdf(data: WorshipData, *, allow_remote: bool = True) -> BytesIO:
    """Build folded Letter bulletin PDF (BytesIO for Streamlit download)."""
    _ = allow_remote
    return draw_bulletin(data)


def generate_bulletin_pdf(output_path: str | Path, data: WorshipData | dict) -> str:
    """Convenience wrapper — writes a file path."""
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
