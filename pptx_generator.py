"""Master-template PowerPoint injection — text (and optional score image) substitution only."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Optional, Union

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from text_normalize import normalize_breaks
from models import WorshipData
from template_tokens import (
    apply_tokens,
    build_token_map,
    hymn_number_for_slot,
    list_placeholders_in_text,
)

MasterSource = Union[bytes, bytearray, BinaryIO, str, Path]

# Reload marker for Streamlit — bump when injection logic changes
_INJECT_VERSION = "2026-08-23-this-week-hymn-pptx-insert"

_PLACEHOLDER_ONLY_RE = re.compile(r"^\s*\{\{([A-Za-z0-9_]+)\}\}\s*$")

# Title-like tokens → center; everything else with body content → left
_TITLE_TOKEN_RE = re.compile(
    r"^(CHURCH_|SERVICE_TITLE|META_LINE|DATE|SERVICE_TIME|HYMN_[1-4]$|HYMN_[1-4]_TITLE|HYMN_[1-4]_NUM|"
    r"HYMN_[1-4]_NUMBER|HYMN_[1-4]_SCORE|SERMON_TITLE|SERMON_SUBTITLE|PREACHER|"
    r"SCRIPTURE_REF|SCRIPTURE_REFERENCE|RESPONSIVE_TITLE|APOSTLES_CREED_HEADING|"
    r"PRAISE_HYMN|HYMN$|HYMN_NUM|"
    r"HYMN_TITLE|RESPONSE_HYMN|OFFERING_HYMN|PRAISE_NUM|PRAISE_TITLE|PRAYER_LEADER|"
    r"BENEDICTION)$"
)
_BODY_TOKEN_RE = re.compile(
    r"(LYRICS|BIBLE|SCRIPTURE_TEXT|RESPONSIVE(_\d+|_BODY|_READING|_FULL)?$|"
    r"APOSTLES_CREED|ORDER_TEXT|PRAYER_TEXT|ANNOUNCEMENTS|CLOSING_NOTE|"
    r"BENEDICTION_BODY|READING)",
    re.I,
)
_RESPONSIVE_TOKEN_RE = re.compile(
    r"^RESPONSIVE(_\d+|_BODY|_READING|_FULL)?$", re.I
)
_LEADER_LINE_RE = re.compile(r"^(인도자|인도|Leader)\s*[:：]", re.I)
_CONG_LINE_RE = re.compile(r"^(회중|성도|All|People)\s*[:：]", re.I)

# Responsive reading roles — high contrast on dark field (senior-readable)
_COLOR_LEADER = RGBColor(0xFF, 0xE0, 0x66)  # 인도자 — yellow
_COLOR_CONG = RGBColor(0xFF, 0x5C, 0x5C)  # 회중 — red
_COLOR_BODY = RGBColor(0xFF, 0xFC, 0xF5)  # cream

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
SAFE_LEFT = Inches(1.75)
SAFE_RIGHT = Inches(11.55)
SAFE_TOP = Inches(0.28)
SAFE_BOTTOM = Inches(7.15)

# Match master type scale so injection never fights the template
_BODY_FONT_PT = 26
_TITLE_FONT_PT = 36
_ANNOUNCE_FONT_PT = 44
_SERMON_FONT_PT = 52  # readable hero title (was briefly 156)
_COVER_LEADER_FONT_PT = 34
_COVER_EN_FONT_PT = 34
_FONT_NAME = "Malgun Gothic"
# Hard cap — hymn / scripture / creed: exactly 4 visual lines per slide
_STRICT_LINES_PER_SLIDE = 4
# Wide enough for normal hymnal lines; only wrap truly long lines at phrase breaks
_STRICT_BODY_CHARS = 28
_STRICT_BODY_FONT_PT = 28


def clean_text(text: str | None) -> str:
    """Clean soft breaks and leftover unresolved {{TOKEN}} placeholders."""
    t = normalize_breaks(text or "").strip()
    if not t:
        return ""
    t = re.sub(r"\{\{[A-Za-z0-9_]+\}\}", "", t)
    return t.strip()


def _clean_scripture_projection(text: str | None) -> str:
    """Bible slides only — strip BSK footnote chips like '5)', keep (셀라)."""
    t = clean_text(text)
    if not t:
        return ""
    t = re.sub(r"\s*\d{1,2}\)\s*", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return t.strip()


def _set_run_font(
    run,
    *,
    name: str,
    size_pt: float,
    bold: bool | None = None,
    color: RGBColor | None = None,
) -> None:
    """Set Latin + East-Asian typeface so Korean uses Malgun Gothic at the intended size."""
    try:
        run.font.name = name
        run.font.size = Pt(size_pt)
        if bold is not None:
            run.font.bold = bold
        if color is not None:
            run.font.color.rgb = color
    except Exception:
        pass
    try:
        rPr = run._r.get_or_add_rPr()  # noqa: SLF001
        for tag in ("latin", "ea", "cs"):
            el = rPr.find(qn(f"a:{tag}"))
            if el is None:
                el = OxmlElement(f"a:{tag}")
                rPr.append(el)
            el.set("typeface", name)
    except Exception:
        pass


def _wrap_phrase_line(line: str, max_chars: int) -> list[str]:
    """
    Wrap only when needed. Prefer spaces / punctuation — never mid-phrase syllable chops
    for normal hymnal / 교독문 lines.
    """
    line = (line or "").strip()
    if not line:
        return []
    if max_chars < 10:
        max_chars = 10
    if len(line) <= max_chars:
        return [line]

    # Break candidates: whitespace and common Korean/Western punctuation
    parts = re.split(r"(\s+|[,，、·;；:：])", line)
    out: list[str] = []
    cur = ""
    for part in parts:
        if not part:
            continue
        candidate = cur + part
        if len(candidate.rstrip()) <= max_chars:
            cur = candidate
            continue
        if cur.strip():
            out.append(cur.rstrip())
            cur = part.lstrip() if part.isspace() else part
        else:
            # Oversized token — keep-all only as last resort
            from text_format import wrap_keep_all

            out.extend(wrap_keep_all(part.strip(), max_chars) or [part.strip()[:max_chars]])
            cur = ""
    if cur.strip():
        out.append(cur.rstrip())
    return out if out else [line[:max_chars]]


def _strict_visual_lines(text: str) -> list[str]:
    """Up to 4 projection lines — preserve original breaks; wrap only long lines."""
    wrapped: list[str] = []
    cleaned = clean_text(text)
    for raw in cleaned.split("\n") if cleaned else []:
        raw = raw.strip()
        if not raw:
            continue
        pieces = _wrap_phrase_line(raw, _STRICT_BODY_CHARS)
        wrapped.extend(pieces)
    return wrapped[:_STRICT_LINES_PER_SLIDE]


def _pages_keep_lines(full_text: str, *, lines_per_page: int = 4) -> list[str]:
    """Page by original lines (phrase-wrap only when a single line is too long)."""
    lines: list[str] = []
    cleaned = clean_text(full_text)
    for raw in cleaned.split("\n") if cleaned else []:
        raw = raw.strip()
        if not raw:
            continue
        lines.extend(_wrap_phrase_line(raw, _STRICT_BODY_CHARS))
    if not lines:
        return [""]
    n = max(1, lines_per_page)
    return ["\n".join(lines[i : i + n]) for i in range(0, len(lines), n)]


def _write_strict_line_slots(slide, shape, text: str, *, token_key: str) -> None:
    """
    Replace one body textbox with 4 fixed-height single-line boxes.
    Prevents PowerPoint from wrapping a paragraph into extra visual lines
    that spill past the slide frame.
    """
    try:
        left, top, width, height = int(shape.left), int(shape.top), int(shape.width), int(shape.height)
    except Exception:
        return
    try:
        shape._element.getparent().remove(shape._element)  # noqa: SLF001
    except Exception:
        return

    lines = _strict_visual_lines(text)
    slots = _STRICT_LINES_PER_SLIDE
    slot_h = max(int(Inches(0.70)), height // slots)
    gap = int(Inches(0.06))
    is_responsive = _is_responsive_token(token_key)
    for i in range(slots):
        line = lines[i] if i < len(lines) else ""
        box_top = top + i * slot_h
        box_h = max(int(Inches(0.55)), slot_h - gap)
        if box_top + box_h > int(SAFE_BOTTOM):
            box_h = max(int(Inches(0.45)), int(SAFE_BOTTOM) - box_top)
        if box_h < int(Inches(0.4)):
            break
        box = slide.shapes.add_textbox(left, box_top, width, box_h)
        box.name = token_key if i == 0 else f"{token_key}__L{i + 1}"
        tf = box.text_frame
        try:
            tf.word_wrap = False  # one line only — never grow vertically
            tf.auto_size = None
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf.margin_left = Inches(0.08)
            tf.margin_right = Inches(0.08)
            tf.margin_top = Inches(0.02)
            tf.margin_bottom = Inches(0.02)
        except Exception:
            pass
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT if is_responsive else PP_ALIGN.CENTER
        try:
            p.line_spacing = 1.0
            p.space_after = Pt(0)
            p.space_before = Pt(0)
        except Exception:
            pass

        role = _responsive_role(line) if is_responsive else None
        if role and (":" in line or "：" in line):
            m = re.match(r"^([^:：]+)([:：]\s*)(.*)$", line)
            if m:
                label, colon, rest = m.group(1), m.group(2), m.group(3)
                color = _COLOR_LEADER if role == "leader" else _COLOR_CONG
                run0 = p.add_run()
                run0.text = label + colon
                _set_run_font(run0, name=_FONT_NAME, size_pt=_STRICT_BODY_FONT_PT, bold=True, color=color)
                run1 = p.add_run()
                run1.text = rest
                _set_run_font(run1, name=_FONT_NAME, size_pt=_STRICT_BODY_FONT_PT, bold=False, color=color)
                continue

        run = p.add_run()
        run.text = line
        color = _COLOR_BODY
        bold = False
        if role == "leader":
            color, bold = _COLOR_LEADER, True
        elif role == "cong":
            color, bold = _COLOR_CONG, True
        _set_run_font(
            run,
            name=_FONT_NAME,
            size_pt=_STRICT_BODY_FONT_PT,
            bold=bold,
            color=color,
        )


def sanitize_token_map(tokens: dict[str, str]) -> dict[str, str]:
    """Normalize every token value so injection never carries soft-break codes."""
    out: dict[str, str] = {}
    for k, v in tokens.items():
        raw = v if v is not None else ""
        key = str(k)
        if key.startswith("BIBLE") or key.startswith("SCRIPTURE"):
            out[key] = _clean_scripture_projection(raw)
        elif key.startswith("RESPONSIVE"):
            try:
                from responsive_lookup import sanitize_responsive_body

                if key in {"RESPONSIVE_TITLE"} or key.endswith("_TITLE"):
                    out[key] = clean_text(raw)
                else:
                    out[key] = clean_text(sanitize_responsive_body(raw) or raw)
            except Exception:
                out[key] = clean_text(raw)
        else:
            out[key] = clean_text(raw)
    return out


def _as_stream(master: MasterSource) -> BytesIO:
    if isinstance(master, (bytes, bytearray)):
        return BytesIO(master)
    if isinstance(master, (str, Path)):
        path = Path(master)
        if not path.exists():
            raise FileNotFoundError(f"Master PPTX not found: {path}")
        return BytesIO(path.read_bytes())
    data = master.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    return BytesIO(data)


def _iter_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            try:
                yield from _iter_shapes(shape.shapes)
            except Exception:
                continue


def _copy_font(src_run, dst_run) -> None:
    try:
        dst_run.font.name = src_run.font.name
        dst_run.font.size = src_run.font.size
        dst_run.font.bold = src_run.font.bold
        dst_run.font.italic = src_run.font.italic
        if src_run.font.color and src_run.font.color.rgb:
            dst_run.font.color.rgb = src_run.font.color.rgb
    except Exception:
        pass


def _clear_textframe(tf) -> None:
    """Keep one empty paragraph; remove extra paragraphs so lines don't pile up."""
    txBody = tf._txBody  # noqa: SLF001
    paragraphs = [c for c in list(txBody) if c.tag.endswith("}p")]
    if not paragraphs:
        return
    first = paragraphs[0]
    ns_t = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
    for r in first.findall(f".//{ns_t}"):
        r.text = ""
    for extra in paragraphs[1:]:
        txBody.remove(extra)


def _alignment_for_token(key: str | None, sample_align=None) -> object:
    """Most congregational text is centered; order + 교독문 stay left for clarity."""
    if key in {"ORDER_TEXT"} or (key and key.startswith("ORDER_")):
        return PP_ALIGN.LEFT
    if key and _RESPONSIVE_TOKEN_RE.match(key):
        return PP_ALIGN.LEFT
    return PP_ALIGN.CENTER


def _is_responsive_token(key: str | None) -> bool:
    return bool(key and _RESPONSIVE_TOKEN_RE.match(key))


def _responsive_role(line: str) -> str | None:
    """Return 'leader' | 'cong' | None for a 교독문 line."""
    s = (line or "").strip()
    if not s:
        return None
    if _LEADER_LINE_RE.match(s):
        return "leader"
    if _CONG_LINE_RE.match(s):
        return "cong"
    return None


def _is_title_token(key: str | None) -> bool:
    return bool(key and _TITLE_TOKEN_RE.match(key))


def _is_announce_token(key: str | None) -> bool:
    """Full-slide announcement titles (hymn intro / sermon)."""
    if not key:
        return False
    return bool(
        re.fullmatch(r"HYMN_[1-4]", key)
        or key in {"SERMON_TITLE", "CHURCH_KO", "SERVICE_TITLE"}
    )


def _font_pt_for_token(token_key: str | None, sample) -> int:
    """Prefer master sample sizes so the design system stays even."""
    sample_pt = None
    if sample is not None:
        try:
            if sample.font.size:
                sample_pt = int(round(sample.font.size.pt))
        except Exception:
            sample_pt = None

    if token_key == "SERMON_TITLE":
        return _SERMON_FONT_PT
    if token_key == "WORSHIP_LEADER":
        return sample_pt if sample_pt and 20 <= sample_pt <= 44 else 28
    if token_key == "CHURCH_EN":
        return sample_pt if sample_pt and 22 <= sample_pt <= 40 else _COVER_EN_FONT_PT
    if sample_pt and 14 <= sample_pt <= 72:
        return sample_pt
    if _is_announce_token(token_key):
        return _ANNOUNCE_FONT_PT
    if _is_title_token(token_key):
        return _TITLE_FONT_PT
    if token_key and _BODY_TOKEN_RE.search(token_key):
        return _BODY_FONT_PT
    return sample_pt or _BODY_FONT_PT


def _wrap_line(line: str, max_chars: int) -> list[str]:
    """
    Phrase-aware wrap for projection:
    1) Prefer spaces / punctuation (keep compounds like 사랑하사 together)
    2) Fall back to keep-all syllable groups — never mid-Latin-word cuts.
    """
    from text_format import wrap_keep_all

    line = (line or "").rstrip()
    if not line:
        return [""]
    if max_chars < 8:
        max_chars = 8
    if len(line) <= max_chars:
        return [line]

    # First pass: break only on whitespace when possible
    parts = re.split(r"(\s+)", line)
    out: list[str] = []
    cur = ""
    for part in parts:
        if not part:
            continue
        candidate = cur + part
        if len(candidate.rstrip()) <= max_chars:
            cur = candidate
            continue
        if cur.strip():
            out.append(cur.rstrip())
            cur = part.lstrip() if part.isspace() else part
        else:
            # Oversized token with no spaces — keep-all fallback
            chunk = part.strip()
            if chunk:
                out.extend(wrap_keep_all(chunk, max_chars) or [chunk])
            cur = ""
    if cur.strip():
        out.append(cur.rstrip())
    return out if out else [line]


def _fit_lines(text: str, *, max_lines: int, max_chars: int, clip: bool = False) -> list[str]:
    """Wrap lines to frame width. Only clip when clip=True (titles); body uses pre-paged tokens."""
    text = clean_text(text)
    wrapped: list[str] = []
    for raw in (text.split("\n") if text else [""]):
        wrapped.extend(_wrap_line(raw, max_chars))
    if not wrapped:
        return [""]
    if not clip or len(wrapped) <= max(1, max_lines):
        return wrapped
    clipped = wrapped[: max(1, max_lines)]
    last = clipped[-1].rstrip()
    if not last.endswith("…"):
        clipped[-1] = (last[: max(0, max_chars - 1)] + "…") if last else "…"
    return clipped


def _reflow_pages(full_text: str, *, max_lines: int, max_chars: int) -> list[str]:
    """Split full text into slide pages that fit the body frame — no content lost."""
    wrapped: list[str] = []
    for raw in clean_text(full_text).split("\n") if clean_text(full_text) else []:
        wrapped.extend(_wrap_line(raw, max_chars))
    if not wrapped:
        return [""]
    max_lines = max(1, max_lines)
    pages: list[str] = []
    for i in range(0, len(wrapped), max_lines):
        pages.append("\n".join(wrapped[i : i + max_lines]))
    return pages


def _is_strict_paged_body(token_key: str | None) -> bool:
    """Hymn / scripture / creed / 교독문 — hard 4-line slot pages."""
    if not token_key:
        return False
    if "LYRICS" in token_key:
        return True
    if token_key.startswith("APOSTLES_CREED") and token_key != "APOSTLES_CREED_HEADING":
        return True
    if token_key.startswith("BIBLE_TEXT") or token_key in {"BIBLE", "SCRIPTURE_TEXT"}:
        return True
    if _is_responsive_token(token_key) and "TITLE" not in token_key:
        return True
    return False


def _frame_limits(tf) -> tuple[int, int]:
    """Estimate max lines and chars from text-frame geometry + font size."""
    try:
        shape = tf._parent  # noqa: SLF001
        width = float(shape.width)
        height = float(shape.height)
    except Exception:
        width, height = float(Inches(11)), float(Inches(5))

    font_pt = 30
    sample = None
    for para in tf.paragraphs:
        if para.runs and para.runs[0].font.size:
            sample = para.runs[0]
            break
    if sample and sample.font.size:
        font_pt = int(sample.font.size.pt)

    # Conservative for Korean projection — prefer fewer lines over overflow
    line_h = font_pt * 1.45 * 12700  # pt → EMU approx
    max_lines = max(1, int((height * 0.82) / max(line_h, 1)))
    char_w = font_pt * 1.12 * 12700  # CJK glyphs are nearly square
    max_chars = max(12, int((width * 0.86) / max(char_w, 1)))
    return max_lines, max_chars


def _strict_page_text(full_text: str, *, max_lines: int = 4, max_chars: int | None = None) -> list[str]:
    """Phrase-wrap then emit exactly ≤max_lines per page."""
    chars = _STRICT_BODY_CHARS if max_chars is None else max(10, min(int(max_chars), _STRICT_BODY_CHARS))
    n = max(1, int(max_lines or _STRICT_LINES_PER_SLIDE))
    wrapped: list[str] = []
    cleaned = clean_text(full_text)
    for raw in cleaned.split("\n") if cleaned else []:
        wrapped.extend(_wrap_phrase_line(raw, chars))
    if not wrapped:
        return [""]
    return ["\n".join(wrapped[i : i + n]) for i in range(0, len(wrapped), n)]


def _clamp_shape_to_slide(shape) -> None:
    """Keep text boxes inside the 16:9 safe margins."""
    try:
        left, top, width, height = shape.left, shape.top, shape.width, shape.height
    except Exception:
        return
    changed = False
    if left < SAFE_LEFT:
        width = width - (SAFE_LEFT - left)
        left = SAFE_LEFT
        changed = True
    if left + width > SAFE_RIGHT:
        width = SAFE_RIGHT - left
        changed = True
    if top < SAFE_TOP:
        height = height - (SAFE_TOP - top)
        top = SAFE_TOP
        changed = True
    if top + height > SAFE_BOTTOM:
        height = SAFE_BOTTOM - top
        changed = True
    if width < Inches(0.5) or height < Inches(0.3):
        return
    if changed:
        try:
            shape.left = int(left)
            shape.top = int(top)
            shape.width = int(width)
            shape.height = int(height)
        except Exception:
            pass


def _fill_textframe_multiline(tf, text: str, *, align=None, token_key: str | None = None) -> None:
    """
    Write logical paragraphs into the frame. Prefer PowerPoint word-wrap so
    glyphs stay inside the shape — avoid hard character-splitting that causes
    mid-phrase breaks and vertical overflow.
    """
    text = clean_text(text)
    sample = None
    for para in tf.paragraphs:
        if para.runs:
            sample = para.runs[0]
            break

    alignment = align if align is not None else _alignment_for_token(token_key)
    max_lines, max_chars = _frame_limits(tf)
    is_body = bool(token_key and _BODY_TOKEN_RE.search(token_key))
    is_strict = _is_strict_paged_body(token_key)
    font_pt = _font_pt_for_token(token_key, sample)
    if is_strict:
        # Ignore master sample size — fixed projection size for 4-line pages
        font_pt = _STRICT_BODY_FONT_PT
        max_chars = _STRICT_BODY_CHARS

    logical = text.split("\n") if text else [""]
    if not logical:
        logical = [""]

    # Body / order / sermon: keep logical lines; PPT wraps within the box.
    # Other titles: soft-wrap, but never ellipsis-clip sermon / benediction.
    no_clip = bool(
        token_key
        and (
            token_key
            in {
                "SERMON_TITLE",
                "SERMON_SUBTITLE",
                "BENEDICTION",
                "BENEDICTION_BODY",
                "PREACHER",
                "SCRIPTURE_REF",
                "SCRIPTURE_REFERENCE",
                "RESPONSIVE_TITLE",
                "CHURCH_EN",
                "CHURCH_KO",
                "META_LINE",
                "DATE",
                "SERVICE_TIME",
                "SERVICE_TITLE",
                "WORSHIP_LEADER",
            }
            or _is_announce_token(token_key)
        )
    )
    if is_strict:
        # Pre-wrap to visual lines and hard-cap — PPT must not reflow past the frame
        soft: list[str] = []
        for raw in logical:
            soft.extend(_wrap_line(raw, _STRICT_BODY_CHARS))
        lines = soft[:_STRICT_LINES_PER_SLIDE] or [""]
    elif is_body or token_key == "ORDER_TEXT" or no_clip:
        lines = logical
        if no_clip and token_key not in {"ORDER_TEXT"}:
            # Soft-wrap long announce/sermon lines without cutting meaning
            soft: list[str] = []
            for raw in logical:
                soft.extend(_wrap_line(raw, max(max_chars, 16)))
            lines = soft or [""]
    else:
        lines = []
        for raw in logical:
            lines.extend(_wrap_line(raw, max_chars))
        if len(lines) > max(1, max_lines):
            lines = _fit_lines("\n".join(lines), max_lines=max_lines, max_chars=max_chars, clip=True)

    # Order list: shrink until soft-wrapped visual lines fit the frame
    if token_key == "ORDER_TEXT":
        font_pt = min(font_pt, 22)
        try:
            shape = tf._parent  # noqa: SLF001
            height = float(shape.height)
            width = float(shape.width)
        except Exception:
            height = float(Inches(5.0))
            width = float(Inches(9.0))

        def _order_capacity(pt: float) -> tuple[int, int]:
            line_h = pt * 1.22 * 12700
            cap = max(1, int((height * 0.94) / max(line_h, 1)))
            char_w = pt * 1.0 * 12700
            chars = max(10, int((width * 0.90) / max(char_w, 1)))
            return cap, chars

        cap, chars = _order_capacity(font_pt)
        visual = sum(len(_wrap_line(ln, chars)) for ln in lines) or 1
        while font_pt > 16 and visual > cap:
            font_pt -= 1
            cap, chars = _order_capacity(font_pt)
            visual = sum(len(_wrap_line(ln, chars)) for ln in lines) or 1
        max_lines = cap

    try:
        tf.word_wrap = True
        tf.auto_size = None
        # Sermon / announce titles sit in a centered hero box — keep middle anchor
        if token_key == "SERMON_TITLE" or _is_announce_token(token_key):
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        else:
            tf.vertical_anchor = MSO_ANCHOR.TOP
        tf.margin_left = Inches(0.08)
        tf.margin_right = Inches(0.08)
        tf.margin_top = Inches(0.06)
        tf.margin_bottom = Inches(0.08)
    except Exception:
        pass

    _clear_textframe(tf)

    if token_key == "ORDER_TEXT":
        line_spacing, space_after = 1.22, 4
    elif is_strict:
        # 4 × 28pt with tight rhythm — must stay inside H_BODY
        line_spacing, space_after = 1.22, 2
    elif _is_responsive_token(token_key):
        line_spacing, space_after = 1.35, 8
    elif _is_title_token(token_key):
        line_spacing, space_after = 1.15, 0
    else:
        line_spacing, space_after = 1.42, 8

    colorize_responsive = _is_responsive_token(token_key)

    for i, line in enumerate(lines):
        if i == 0:
            para = tf.paragraphs[0]
        else:
            para = tf.add_paragraph()
        para.alignment = alignment
        try:
            para.line_spacing = line_spacing
            para.space_after = Pt(space_after)
        except Exception:
            pass

        # Clear any leftover runs on first para
        if para.runs:
            for run in list(para.runs)[1:]:
                run.text = ""
            run0 = para.runs[0]
            run0.text = ""
        else:
            run0 = None

        role = _responsive_role(line) if colorize_responsive else None
        if role and (":" in line or "：" in line):
            # Split "인도자: …" / "회중: …" into bold colored label + body
            m = re.match(r"^([^:：]+)([:：]\s*)(.*)$", line)
            if m:
                label, colon, rest = m.group(1), m.group(2), m.group(3)
                color = _COLOR_LEADER if role == "leader" else _COLOR_CONG
                if run0 is None:
                    run0 = para.add_run()
                run0.text = f"{label}{colon}"
                if sample is not None:
                    _copy_font(sample, run0)
                try:
                    run0.font.name = _FONT_NAME
                    run0.font.size = Pt(font_pt)
                    run0.font.bold = True
                    run0.font.color.rgb = color
                except Exception:
                    pass
                if rest:
                    run1 = para.add_run()
                    run1.text = rest
                    if sample is not None:
                        _copy_font(sample, run1)
                    try:
                        run1.font.name = _FONT_NAME
                        run1.font.size = Pt(font_pt)
                        run1.font.bold = False
                        run1.font.color.rgb = color
                    except Exception:
                        pass
                continue

        if run0 is None:
            run0 = para.add_run()
        run0.text = line
        bold = bool(_is_title_token(token_key) or _is_announce_token(token_key))
        color = _COLOR_BODY
        if role == "leader":
            color = _COLOR_LEADER
            bold = True
        elif role == "cong":
            color = _COLOR_CONG
            bold = True
        _set_run_font(run0, name=_FONT_NAME, size_pt=font_pt, bold=bold, color=color)


def apply_text_to_shape(shape, text: str, *, token_key: str | None = None) -> None:
    """Clear shape text and write cleaned multiline body with orderly alignment."""
    if not getattr(shape, "has_text_frame", False):
        return
    _clamp_shape_to_slide(shape)
    _fill_textframe_multiline(shape.text_frame, text, token_key=token_key)


def _frame_placeholder_key(tf) -> Optional[str]:
    """If the whole text frame is exactly one {{TOKEN}}, return that key."""
    parts: list[str] = []
    for para in tf.paragraphs:
        parts.append("".join(run.text or "" for run in para.runs))
    frame_text = "\n".join(parts).strip()
    # Soft breaks inside a lone placeholder are still a lone placeholder
    frame_text = normalize_breaks(frame_text).strip()
    m = _PLACEHOLDER_ONLY_RE.match(frame_text)
    return m.group(1) if m else None


def _replace_in_textframe(tf, tokens: dict[str, str]) -> int:
    if tf is None:
        return 0

    # Whole-frame single placeholder → fill only that token (prevents cross-token bleed)
    key = _frame_placeholder_key(tf)
    if key:
        _fill_textframe_multiline(tf, tokens.get(key, ""), token_key=key)
        return 1

    # Mixed text + placeholders in one frame: replace then rebuild
    joined = "\n".join(
        "".join(run.text or "" for run in para.runs) or (para.text or "")
        for para in tf.paragraphs
    )
    if "{{" not in joined:
        cleaned = normalize_breaks(joined)
        if cleaned != joined and cleaned:
            _fill_textframe_multiline(tf, cleaned, token_key=None)
            return 1
        return 0

    replaced = normalize_breaks(apply_tokens(joined, tokens))
    if replaced == joined:
        return 0

    # Infer alignment from dominant token in the original frame
    keys = list_placeholders_in_text(joined)
    dominant = keys[0] if keys else None
    _fill_textframe_multiline(tf, replaced, token_key=dominant)
    return 1


def _shape_name_token(name: str) -> Optional[str]:
    name = (name or "").strip()
    if name.startswith("{{") and name.endswith("}}"):
        return name[2:-2]
    if re.fullmatch(r"(HYMN_[1-4](_[A-Z0-9]+)*)", name):
        return name
    if re.fullmatch(
        r"(RESPONSIVE|RESPONSIVE_\d+|BIBLE_TEXT|BIBLE_TEXT_\d+|BIBLE|SERMON_TITLE|"
        r"SERMON_SUBTITLE|PREACHER|WORSHIP_LEADER|CHURCH_KO|CHURCH_EN|SCRIPTURE_TEXT|ORDER_TEXT|"
        r"APOSTLES_CREED|APOSTLES_CREED_\d+|APOSTLES_CREED_HEADING|BENEDICTION|BENEDICTION_BODY|"
        r"CLOSING_NOTE|ANNOUNCEMENTS|PRAYER_TEXT|PRAYER_LEADER|SERVICE_TITLE|META_LINE)",
        name,
    ):
        return name
    return None


def _is_content_textbox(shape) -> bool:
    """True for editable text boxes / placeholders — not decorative side panels."""
    if not getattr(shape, "has_text_frame", False):
        return False
    try:
        st = shape.shape_type
        if st == MSO_SHAPE_TYPE.TEXT_BOX:
            return True
        if st == MSO_SHAPE_TYPE.PLACEHOLDER:
            return True
    except Exception:
        pass
    # AutoShape rectangles used as side rails also report has_text_frame
    text = (shape.text_frame.text or "").strip()
    name = (getattr(shape, "name", None) or "")
    if "{{" in text or _shape_name_token(name):
        return True
    return bool(text)


def _replace_in_shape(shape, tokens: dict[str, str]) -> int:
    count = 0
    name = (getattr(shape, "name", None) or "").strip()
    token_from_name = _shape_name_token(name)

    if _is_content_textbox(shape):
        _clamp_shape_to_slide(shape)
        tf = shape.text_frame
        text_key = _frame_placeholder_key(tf)

        if text_key:
            _fill_textframe_multiline(tf, tokens.get(text_key, ""), token_key=text_key)
            count += 1
        elif token_from_name:
            _fill_textframe_multiline(tf, tokens.get(token_from_name, ""), token_key=token_from_name)
            count += 1
        else:
            count += _replace_in_textframe(tf, tokens)

    if getattr(shape, "has_table", False):
        try:
            for row in shape.table.rows:
                for cell in row.cells:
                    count += _replace_in_textframe(cell.text_frame, tokens)
        except Exception:
            pass
    return count


def _score_image_path(number: int) -> Optional[Path]:
    if not number:
        return None
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = SCORE_DIR / f"{number}{ext}"
        if path.exists():
            return path
        path = SCORE_DIR / f"{number:03d}{ext}"
        if path.exists():
            return path
    return None


def _inject_score_images(prs: Presentation, tokens: dict[str, str]) -> int:
    """
    Replace shapes whose name/text is {{HYMN_n_SCORE_IMAGE}} with a local score image
    from data/hymn_scores/{n}.png|jpg when available. Layout position/size preserved.
    """
    replaced = 0
    for slide in prs.slides:
        for shape in list(_iter_shapes(slide.shapes)):
            name = (getattr(shape, "name", None) or "").strip()
            text = ""
            if getattr(shape, "has_text_frame", False):
                text = (shape.text_frame.text or "").strip()
            blob = f"{name}\n{text}"
            m = re.search(r"HYMN_([1-4])_SCORE_IMAGE", blob.replace("{", "").replace("}", ""))
            if not m:
                continue
            slot = m.group(1)
            num = hymn_number_for_slot(tokens, slot)
            img = _score_image_path(num)
            if not img:
                if getattr(shape, "has_text_frame", False):
                    label = tokens.get(f"HYMN_{slot}_SCORE", "") or tokens.get(f"HYMN_{slot}", "")
                    _fill_textframe_multiline(shape.text_frame, label, token_key=f"HYMN_{slot}_SCORE")
                    replaced += 1
                continue
            left, top, width, height = shape.left, shape.top, shape.width, shape.height
            sp = shape._element  # noqa: SLF001
            sp.getparent().remove(sp)
            slide.shapes.add_picture(str(img), left, top, width=width, height=height)
            replaced += 1
    return replaced


def _scrub_soft_breaks_in_prs(prs: Presentation) -> int:
    """Final pass: convert any leftover _x000B_ / \\v in slide text to real paragraphs."""
    changed = 0
    for slide in prs.slides:
        for shape in _iter_shapes(slide.shapes):
            if not _is_content_textbox(shape):
                continue
            tf = shape.text_frame
            raw = "\n".join(p.text or "" for p in tf.paragraphs)
            if "_x000B_" in raw or "_x000b_" in raw or "\v" in raw or "\x0b" in raw:
                _fill_textframe_multiline(tf, normalize_breaks(raw))
                changed += 1
            if getattr(shape, "has_table", False):
                try:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            ctf = cell.text_frame
                            craw = "\n".join(p.text or "" for p in ctf.paragraphs)
                            if "_x000B_" in craw or "\v" in craw or "\x0b" in craw:
                                _fill_textframe_multiline(ctf, normalize_breaks(craw))
                                changed += 1
                except Exception:
                    pass
    return changed


# Paged body series: prefix → full-text key
_PAGED_SERIES = (
    ("HYMN_1_LYRICS", "HYMN_1_LYRICS_FULL"),
    ("HYMN_2_LYRICS", "HYMN_2_LYRICS_FULL"),
    ("HYMN_3_LYRICS", "HYMN_3_LYRICS_FULL"),
    ("BIBLE_TEXT", "BIBLE_TEXT_FULL"),
    ("APOSTLES_CREED", "APOSTLES_CREED_FULL"),
    ("RESPONSIVE", "RESPONSIVE_FULL"),
)

# prefix → (section base label, title token, is_lyrics)
_SERIES_META = {
    "HYMN_1_LYRICS": ("1. 찬양과 기도", "HYMN_1", True),
    "HYMN_2_LYRICS": ("4. 찬송가", "HYMN_2", True),
    "HYMN_3_LYRICS": ("8. 감사와 봉헌", "HYMN_3", True),
    "BIBLE_TEXT": ("6. 오늘의 말씀", "SCRIPTURE_REF", False),
    "APOSTLES_CREED": ("2. 사도신경", "APOSTLES_CREED_HEADING", False),
    "RESPONSIVE": ("3. 교독문", "RESPONSIVE_TITLE", False),
}


def _slide_text_blob(slide) -> str:
    parts: list[str] = []
    for shape in _iter_shapes(slide.shapes):
        name = (getattr(shape, "name", None) or "").strip()
        if name:
            parts.append(name)
        if getattr(shape, "has_text_frame", False):
            parts.append(shape.text_frame.text or "")
    return "\n".join(parts)


def _find_series_slides(prs: Presentation, prefix: str) -> list[tuple[int, int]]:
    """Return [(slide_index, page_num), ...] for PREFIX_N placeholders, sorted by page."""
    numbered = re.compile(r"(?:\{\{)?" + re.escape(prefix) + r"_(\d+)(?:\}\})?")
    bare = "{{" + prefix + "}}"
    found: dict[int, int] = {}
    for i, slide in enumerate(prs.slides):
        blob = _slide_text_blob(slide)
        nums = [int(m) for m in numbered.findall(blob)]
        if nums:
            found[i] = min(nums)
        elif bare in blob:
            found[i] = 1
    return sorted(((idx, page) for idx, page in found.items()), key=lambda t: (t[1], t[0]))


def _body_shape_for_prefix(slide, prefix: str):
    """Find the content textbox that holds PREFIX or PREFIX_N."""
    pat = re.compile(rf"{re.escape(prefix)}(?:_\d+)?$")
    for shape in _iter_shapes(slide.shapes):
        if not _is_content_textbox(shape):
            continue
        name = (getattr(shape, "name", None) or "").strip()
        key = _frame_placeholder_key(shape.text_frame)
        if (key and (key == prefix or key.startswith(prefix + "_"))) or pat.match(name or ""):
            return shape
    best = None
    best_area = 0
    for shape in _iter_shapes(slide.shapes):
        if not _is_content_textbox(shape):
            continue
        try:
            area = int(shape.width) * int(shape.height)
        except Exception:
            continue
        if area > best_area and shape.top > Inches(1.2):
            best = shape
            best_area = area
    return best


def _move_slide(prs: Presentation, from_index: int, to_index: int) -> None:
    """Reorder slide in the presentation (sldIdLst only)."""
    sld_id_lst = prs.slides._sldIdLst  # noqa: SLF001
    entries = list(sld_id_lst)
    if from_index < 0 or from_index >= len(entries):
        return
    entry = entries[from_index]
    sld_id_lst.remove(entry)
    to_index = max(0, min(to_index, len(list(sld_id_lst))))
    sld_id_lst.insert(to_index, entry)


def _delete_slide(prs: Presentation, index: int) -> None:
    """Remove a slide by index (relationship drop — safe for continuation prune)."""
    sld_id_lst = prs.slides._sldIdLst  # noqa: SLF001
    entries = list(sld_id_lst)
    if index < 0 or index >= len(entries):
        return
    sld_id = entries[index]
    try:
        r_id = sld_id.rId
    except Exception:
        r_id = sld_id.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    sld_id_lst.remove(sld_id)
    if r_id:
        try:
            prs.part.drop_rel(r_id)
        except Exception:
            pass


def _prune_extra_series_slides(prs: Presentation, prefix: str, keep: int) -> None:
    """
    Keep the first `keep` series slides (document order); delete the rest.
    Never deletes below 1 seed when keep>=1.
    """
    keep = max(1, int(keep or 1))
    series = sorted(_find_series_slides(prs, prefix), key=lambda t: t[0])
    if len(series) <= keep:
        return
    # Delete from the end so earlier indices stay stable
    for idx, _page in reversed(series[keep:]):
        _delete_slide(prs, idx)


def _remap_paged_token(slide, prefix: str, to_page: int) -> None:
    """Rewrite PREFIX_N placeholders / names to PREFIX_{to_page}."""
    new_token = f"{prefix}_{to_page}"
    token_re = re.compile(re.escape(prefix) + r"_\d+")
    label_re = re.compile(r"(가사|계속)\s*\d+")

    for shape in _iter_shapes(slide.shapes):
        name = (getattr(shape, "name", None) or "").strip()
        key = None
        if getattr(shape, "has_text_frame", False):
            key = _frame_placeholder_key(shape.text_frame)
        should_name = bool(
            (name and (token_re.search(name) or name == prefix))
            or (key and (token_re.match(key) or key == prefix))
        )
        if should_name:
            try:
                shape.name = new_token
            except Exception:
                pass
        if not getattr(shape, "has_text_frame", False):
            continue
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                text = run.text or ""
                if not text:
                    continue
                updated = token_re.sub(new_token, text)
                updated = updated.replace("{{" + prefix + "}}", "{{" + new_token + "}}")
                if "LYRICS" in prefix:
                    updated = label_re.sub(rf"\1 {to_page}", updated)
                if updated != text:
                    run.text = updated


def _motif_for_prefix(prefix: str) -> str:
    """Prefer shared mapping from the master builder (survives Streamlit reloads)."""
    try:
        import build_master_templates as bmt

        fn = getattr(bmt, "_motif_for_prefix", None)
        if callable(fn):
            return fn(prefix)
    except Exception:
        pass
    if "LYRICS" in (prefix or ""):
        return "verse"
    if prefix == "APOSTLES_CREED":
        return "creed"
    if prefix == "RESPONSIVE":
        return "dialogue"
    if (prefix or "").startswith("BIBLE"):
        return "word"
    return "default"


def _insert_continuation_slide(prs: Presentation, after_index: int, prefix: str, page: int) -> None:
    """Create a fresh lyric/scripture slide and place it after after_index."""
    import importlib

    import build_master_templates as bmt

    importlib.reload(bmt)

    section_base, title_key, is_lyrics = _SERIES_META[prefix]
    title_token = "{{" + title_key + "}}"
    body_token = "{{" + f"{prefix}_{page}" + "}}"
    body_name = f"{prefix}_{page}"

    ref_layout = prs.slides[after_index].slide_layout
    slide = prs.slides.add_slide(ref_layout)
    for shape in list(slide.shapes):
        try:
            shape._element.getparent().remove(shape._element)  # noqa: SLF001
        except Exception:
            pass

    motif = getattr(bmt, "_motif_for_prefix", lambda p: "default")(prefix)
    bmt._bg(slide, motif)
    bmt._section_label(slide, section_base)
    title_fn = getattr(bmt, "_title_left", None)
    body_top = Inches(getattr(bmt, "Y_BODY", 2.05))
    body_h = Inches(getattr(bmt, "H_BODY", 4.85))
    title_size = getattr(bmt, "SIZE_TITLE", 36)
    body_size = getattr(bmt, "SIZE_BODY", 30)
    if title_fn is None:
        bmt._box(
            slide,
            bmt.MARGIN_L,
            Inches(getattr(bmt, "Y_TITLE", 0.98)),
            bmt.CONTENT_W,
            Inches(getattr(bmt, "H_TITLE", 0.78)),
            title_token,
            size=title_size,
            bold=True,
            color=bmt.MUTED if is_lyrics else bmt.FG,
            align=PP_ALIGN.LEFT,
            v_anchor=MSO_ANCHOR.MIDDLE,
        )
    else:
        title_fn(
            slide,
            title_token,
            size=title_size,
            color=bmt.MUTED if is_lyrics else bmt.FG,
        )
    bmt._body_left(
        slide,
        body_token,
        top=body_top,
        height=body_h,
        size=body_size if is_lyrics else getattr(bmt, "SIZE_BODY_DENSE", 26),
        name=body_name,
        align=PP_ALIGN.LEFT if prefix == "RESPONSIVE" else PP_ALIGN.CENTER,
    )

    last_index = len(prs.slides) - 1
    _move_slide(prs, last_index, after_index + 1)


def _apply_paged_tokens(tokens: dict[str, str], prefix: str, pages: list[str]) -> None:
    pages = [clean_text(p) for p in (pages or [""])] or [""]
    tokens[prefix] = pages[0]
    tokens[f"{prefix}_FULL"] = "\n".join(p for p in pages if p)
    tokens[f"{prefix}_COUNT"] = str(len(pages))
    # Keep 1..12 always present (empty when unused) for master placeholders
    for i in range(1, 13):
        tokens[f"{prefix}_{i}"] = pages[i - 1] if i <= len(pages) else ""
    for i in range(13, 80):
        key = f"{prefix}_{i}"
        if key in tokens:
            del tokens[key]
    # Extra pages beyond the reserved 12 slots
    for i, page in enumerate(pages, start=1):
        if i > 12:
            tokens[f"{prefix}_{i}"] = page


def _sync_legacy_lyric_aliases(tokens: dict[str, str]) -> None:
    tokens["PRAISE_LYRICS"] = tokens.get("HYMN_1_LYRICS_1", "")
    tokens["PRAISE_LYRICS_1"] = tokens.get("HYMN_1_LYRICS_1", "")
    tokens["PRAISE_LYRICS_2"] = tokens.get("HYMN_1_LYRICS_2", "")
    tokens["HYMN_LYRICS"] = tokens.get("HYMN_2_LYRICS_1", "")
    tokens["HYMN_LYRICS_1"] = tokens.get("HYMN_2_LYRICS_1", "")
    tokens["HYMN_LYRICS_2"] = tokens.get("HYMN_2_LYRICS_2", "")
    tokens["RESPONSE_LYRICS"] = ""
    tokens["RESPONSE_LYRICS_1"] = ""
    tokens["OFFERING_LYRICS"] = tokens.get("HYMN_3_LYRICS_1", "")
    tokens["OFFERING_LYRICS_1"] = tokens.get("HYMN_3_LYRICS_1", "")
    tokens["SCRIPTURE_TEXT"] = tokens.get("BIBLE_TEXT_1", "") or tokens.get("BIBLE_TEXT", "")
    tokens["BIBLE"] = tokens.get("BIBLE_TEXT_FULL", "") or tokens.get("BIBLE_TEXT", "")
    tokens["APOSTLES_CREED"] = tokens.get("APOSTLES_CREED_1", "") or tokens.get("APOSTLES_CREED", "")
    tokens["RESPONSIVE"] = tokens.get("RESPONSIVE_1", "") or tokens.get("RESPONSIVE", "")
    tokens["RESPONSIVE_BODY"] = tokens.get("RESPONSIVE_FULL", "") or tokens.get("RESPONSIVE", "")
    tokens["RESPONSIVE_READING"] = tokens.get("RESPONSIVE_FULL", "") or tokens.get("RESPONSIVE", "")
    tokens.setdefault("APOSTLES_CREED_HEADING", "사도신경")


def ensure_continuation_slides(prs: Presentation, tokens: dict[str, str]) -> dict[str, str]:
    """
    Reflow full hymn/scripture to the body frame, then add continuation slides
    so every line appears in order — matching the bulletin. Unused master
    placeholders are left empty (no slide deletion — avoids corrupt pptx packages).
    """
    tokens = dict(tokens)

    for prefix, full_key in _PAGED_SERIES:
        full = clean_text(tokens.get(full_key) or tokens.get(f"{prefix}_FULL") or "")
        series = _find_series_slides(prs, prefix)
        if not series:
            continue

        if not full:
            _apply_paged_tokens(tokens, prefix, [""])
            for i in range(2, 40):
                tokens[f"{prefix}_{i}"] = ""
            # Drop leftover blank continuation slides (common on polluted masters)
            _prune_extra_series_slides(prs, prefix, keep=1)
            continue

        first_idx, _ = series[0]
        body = _body_shape_for_prefix(prs.slides[first_idx], prefix)
        if body is not None:
            max_lines, max_chars = _frame_limits(body.text_frame)
        else:
            max_lines, max_chars = 10, 28
        max_lines = max(1, max_lines - 1)

        # Hymns keep hymnal line breaks; others phrase-wrap — always 4 lines/slide
        if "LYRICS" in prefix:
            from template_tokens import _hymn_pages

            # Prefer verse groups, then hard-cap each page to 4 original lines
            verse_pages = _hymn_pages(full.splitlines(), lines_per_page=_STRICT_LINES_PER_SLIDE)
            pages = []
            for vp in verse_pages:
                pages.extend(_pages_keep_lines(vp, lines_per_page=_STRICT_LINES_PER_SLIDE))
            pages = [v for v in pages if (v or "").strip()] or [""]
        elif prefix == "RESPONSIVE":
            # Up to 2 pairs (= 4 lines) per slide; preserve 인도자/회중 lines
            from template_tokens import _responsive_pages

            pages = _responsive_pages(full, max_pairs=2) or [""]
            pages = [v for v in pages if (v or "").strip()] or [""]
        elif prefix == "APOSTLES_CREED" or prefix.startswith("BIBLE"):
            pages = _pages_keep_lines(full, lines_per_page=_STRICT_LINES_PER_SLIDE)
            pages = [v for v in pages if (v or "").strip()] or [""]
        else:
            pages = _reflow_pages(full, max_lines=max_lines, max_chars=max_chars)
        pages = [p for p in pages if (p or "").strip()] or [""]
        _apply_paged_tokens(tokens, prefix, pages)
        tokens[f"{prefix}_FULL"] = full
        if full_key != f"{prefix}_FULL":
            tokens[full_key] = full

        # Expand until every content page has a slide
        safety = 0
        while True:
            series = _find_series_slides(prs, prefix)
            if len(series) >= len(pages):
                break
            last_idx, last_page = max(series, key=lambda t: t[1])
            next_page = last_page + 1
            _insert_continuation_slide(prs, last_idx, prefix, next_page)
            safety += 1
            if safety > 60:
                break

        # Remove blank leftover continuation slides (creed / hymns / bible)
        _prune_extra_series_slides(prs, prefix, keep=len(pages))

        # Clear tokens for deleted page slots
        for i in range(len(pages) + 1, 40):
            tokens[f"{prefix}_{i}"] = ""

        # Normalize placeholder numbers: first N slides → pages 1..N
        series = sorted(_find_series_slides(prs, prefix), key=lambda t: t[0])
        for page_num, (idx, _old) in enumerate(series, start=1):
            if page_num <= len(pages):
                _remap_paged_token(prs.slides[idx], prefix, page_num)

    _sync_legacy_lyric_aliases(tokens)
    return tokens


def _ensure_placeholder_defaults(prs: Presentation, tokens: dict[str, str]) -> dict[str, str]:
    """Guarantee every {{TOKEN}} / named shape in the deck has a string value (empty if unused)."""
    tokens = dict(tokens)
    for prefix, _full_key in _PAGED_SERIES:
        tokens.setdefault(prefix, "")
        tokens.setdefault(f"{prefix}_FULL", tokens.get(prefix, ""))
        for i in range(1, 40):
            tokens.setdefault(f"{prefix}_{i}", "")

    for slide in prs.slides:
        for shape in _iter_shapes(slide.shapes):
            name = (getattr(shape, "name", None) or "").strip()
            token = _shape_name_token(name)
            if token:
                tokens.setdefault(token, "")
            if getattr(shape, "has_text_frame", False):
                for key in list_placeholders_in_text(shape.text_frame.text or ""):
                    tokens.setdefault(key, "")
                frame_key = _frame_placeholder_key(shape.text_frame)
                if frame_key:
                    tokens.setdefault(frame_key, "")
            if getattr(shape, "has_table", False):
                try:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            for key in list_placeholders_in_text(cell.text_frame.text or ""):
                                tokens.setdefault(key, "")
                except Exception:
                    pass
    return tokens


def inject_pptx_tokens(prs: Presentation, tokens: dict[str, str]) -> int:
    """Replace all {{TOKEN}} placeholders. Returns # of text regions changed."""
    tokens = sanitize_token_map(_ensure_placeholder_defaults(prs, tokens))
    changed = 0
    for slide in prs.slides:
        # Snapshot shapes first — strict bodies replace the original textbox
        shapes = list(_iter_shapes(slide.shapes))
        for shape in shapes:
            if not getattr(shape, "has_text_frame", False):
                changed += _replace_in_shape(shape, tokens)
                continue
            text_key = _frame_placeholder_key(shape.text_frame)
            name_key = _shape_name_token((getattr(shape, "name", None) or "").strip())
            key = text_key or name_key
            if key and _is_strict_paged_body(key):
                _write_strict_line_slots(slide, shape, tokens.get(key, ""), token_key=key)
                changed += 1
            else:
                changed += _replace_in_shape(shape, tokens)
        try:
            if slide.has_notes_slide:
                changed += _replace_in_textframe(slide.notes_slide.notes_text_frame, tokens)
        except Exception:
            pass
    changed += _inject_score_images(prs, tokens)
    changed += _scrub_soft_breaks_in_prs(prs)
    return changed


def scan_placeholders(master: MasterSource) -> list[str]:
    """List unique {{TOKEN}} names found in a master PPTX."""
    prs = Presentation(_as_stream(master))
    found: set[str] = set()
    for slide in prs.slides:
        for shape in _iter_shapes(slide.shapes):
            name = (getattr(shape, "name", None) or "").strip()
            token = _shape_name_token(name)
            if token:
                found.add(token)
            if getattr(shape, "has_text_frame", False):
                found.update(list_placeholders_in_text(shape.text_frame.text or ""))
            if getattr(shape, "has_table", False):
                try:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            found.update(list_placeholders_in_text(cell.text_frame.text or ""))
                except Exception:
                    pass
    return sorted(found)


def pptx_slide_previews(pptx: MasterSource, *, max_chars: int = 420) -> list[str]:
    """Extract readable text per slide for in-browser preview."""
    prs = Presentation(_as_stream(pptx))
    slides: list[str] = []
    for slide in prs.slides:
        chunks: list[str] = []
        seen: set[str] = set()
        for shape in _iter_shapes(slide.shapes):
            if not getattr(shape, "has_text_frame", False):
                continue
            text = (shape.text_frame.text or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            chunks.append(text)
        body = "\n".join(chunks).strip() or "(빈 슬라이드)"
        if len(body) > max_chars:
            body = body[: max_chars - 1].rstrip() + "…"
        slides.append(body)
    return slides


# Hymn intro tokens in master order → this_week PPT index 0, 1, 2
_HYMN_SLOT_TOKENS = ("HYMN_1", "HYMN_2", "HYMN_3")


def _this_week_hymn_paths() -> list[Path]:
    """Ordered list of this-week PPT files (up to 3 hymn slots)."""
    try:
        import ppt_library

        return list(ppt_library.list_this_week())
    except Exception:
        return []


def insert_this_week_hymn_decks(prs: Presentation, paths: list[Path] | None = None) -> list[str]:
    """
    After each hymn intro (HYMN_1 / HYMN_2 / HYMN_3), insert that week's
    matching hymn PPT slides as-is (score images included).

    Mapping: this_week order 1→찬양, 2→찬송, 3→봉헌.
    Returns human-readable notes for the UI.
    """
    import pptx_slide_copy as psc

    paths = list(paths if paths is not None else _this_week_hymn_paths())
    notes: list[str] = []
    if not paths:
        return notes

    # Process later slots first so earlier insertion indices stay valid.
    pairs: list[tuple[int, str, Path]] = []
    for i, token in enumerate(_HYMN_SLOT_TOKENS):
        if i >= len(paths):
            break
        pairs.append((i, token, paths[i]))

    for _i, token, path in reversed(pairs):
        if not path.is_file():
            notes.append(f"{token}: 파일 없음 ({path.name})")
            continue
        after = psc.find_named_token_slide(prs, token)
        if after is None:
            notes.append(f"{token}: 마스터에 인트로 슬라이드 없음 — {path.name} 건너뜀")
            continue
        try:
            n = psc.insert_pptx_after(prs, after, path)
        except Exception as exc:
            notes.append(f"{token}: 삽입 실패 ({path.name}) — {exc}")
            continue
        notes.append(f"{token}: {path.name} → {n}장 삽입")
    return notes


def generate_worship_pptx(
    data: WorshipData,
    *,
    master: Optional[MasterSource] = None,
    allow_remote: bool = True,
    this_week_hymns: Optional[list[Path]] = None,
    insert_this_week: bool = True,
) -> BytesIO:
    """
    Open the user-provided master PPTX and inject weekly worship text only.

    Hymn numbers (e.g. 7장) are resolved to title + lyrics and written into
    {{HYMN_1}}, {{HYMN_1_LYRICS}}, {{HYMN_1_SCORE}}, etc.

    When this_week PPT files exist, their slides are copied as-is after each
    hymn intro (HYMN_1 / HYMN_2 / HYMN_3) — score images included, no rewrite.

    Line breaks are real paragraphs (Enter), never soft-break _x000B_ / \\v.
    Each shape is filled from its own {{TOKEN}} so hymn slots do not cross-contaminate.
    """
    if master is None:
        raise ValueError(
            "Master Worship PPT (.pptx)가 필요합니다. "
            "예배 PPT 마스터 파일을 먼저 업로드해 주세요."
        )

    tokens = sanitize_token_map(build_token_map(data, allow_remote=allow_remote))

    # Master decks often reserve HYMN_n_LYRICS_1..3 even when a hymn is short
    for prefix, _full in _PAGED_SERIES:
        for i in range(1, 13):
            tokens.setdefault(f"{prefix}_{i}", "")
        tokens.setdefault(prefix, "")

    if not data.include_hymn_lyrics:
        for key in list(tokens):
            if "LYRICS" in key:
                if key.endswith("_LYRICS") or "_LYRICS_" in key:
                    tokens[key] = ""

    stream = _as_stream(master)
    prs = Presentation(stream)
    tokens = ensure_continuation_slides(prs, tokens)
    inject_pptx_tokens(prs, tokens)

    insert_notes: list[str] = []
    if insert_this_week:
        insert_notes = insert_this_week_hymn_decks(prs, this_week_hymns)
    # Stash for callers / Streamlit toast (non-serialized side channel)
    generate_worship_pptx.last_insert_notes = insert_notes  # type: ignore[attr-defined]

    buffer = BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer
