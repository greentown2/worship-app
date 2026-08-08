"""Master-template PowerPoint injection — text (and optional score image) substitution only."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Optional, Union

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from text_normalize import normalize_breaks
from models import WorshipData
from template_tokens import (
    apply_tokens,
    build_token_map,
    hymn_number_for_slot,
    list_placeholders_in_text,
)

MasterSource = Union[bytes, bytearray, BinaryIO, str, Path]

DATA_DIR = Path(__file__).resolve().parent / "data"
SCORE_DIR = DATA_DIR / "hymn_scores"

_PLACEHOLDER_ONLY_RE = re.compile(r"^\s*\{\{([A-Za-z0-9_]+)\}\}\s*$")


def clean_text(text: str | None) -> str:
    """Clean internal python-pptx soft breaks and literal _x000B_ tokens."""
    return normalize_breaks(text or "").strip()


def sanitize_token_map(tokens: dict[str, str]) -> dict[str, str]:
    """Normalize every token value so injection never carries soft-break codes."""
    return {k: clean_text(v if v is not None else "") for k, v in tokens.items()}


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


def _fill_textframe_multiline(tf, text: str) -> None:
    """
    Safely clear a text frame and apply real paragraph line breaks (Enter).
    Preserves the master template's first-run font (size/name/color).
    """
    text = clean_text(text)
    lines = text.split("\n") if text else [""]
    if not lines:
        lines = [""]

    sample = None
    for para in tf.paragraphs:
        if para.runs:
            sample = para.runs[0]
            break

    _clear_textframe(tf)

    for i, line in enumerate(lines):
        if i == 0:
            para = tf.paragraphs[0]
        else:
            para = tf.add_paragraph()
        if para.runs:
            for run in list(para.runs)[1:]:
                run.text = ""
            run = para.runs[0]
            run.text = line
        else:
            run = para.add_run()
            run.text = line
        if sample is not None:
            _copy_font(sample, run)
        try:
            para.line_spacing = 1.5
        except Exception:
            pass


def apply_text_to_shape(shape, text: str) -> None:
    """Proposal-compatible helper: clear shape text and write cleaned multiline body."""
    if not getattr(shape, "has_text_frame", False):
        return
    _fill_textframe_multiline(shape.text_frame, text)


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
    if key and key in tokens:
        _fill_textframe_multiline(tf, tokens.get(key, ""))
        return 1

    # Mixed text + placeholders in one frame: replace per paragraph when possible;
    # if any replacement becomes multiline, rebuild the whole frame from joined text.
    joined = "\n".join(
        "".join(run.text or "" for run in para.runs) or (para.text or "")
        for para in tf.paragraphs
    )
    if "{{" not in joined:
        # Still scrub any leftover soft-break codes in static master text
        cleaned = normalize_breaks(joined)
        if cleaned != joined and cleaned:
            _fill_textframe_multiline(tf, cleaned)
            return 1
        return 0

    replaced = normalize_breaks(apply_tokens(joined, tokens))
    if replaced == joined:
        return 0

    # Always rebuild with real paragraphs — never \\v / _x000B_
    _fill_textframe_multiline(tf, replaced)
    return 1


def _shape_name_token(name: str) -> Optional[str]:
    name = (name or "").strip()
    if name.startswith("{{") and name.endswith("}}"):
        return name[2:-2]
    # Exact token-style names only (avoid accidental AutoShape matches)
    if re.fullmatch(r"(HYMN_[1-4](_[A-Z0-9]+)*)", name):
        return name
    if re.fullmatch(
        r"(RESPONSIVE|BIBLE_TEXT|BIBLE|SERMON_TITLE|SCRIPTURE_TEXT|ORDER_TEXT|APOSTLES_CREED)",
        name,
    ):
        return name
    return None


def _replace_in_shape(shape, tokens: dict[str, str]) -> int:
    count = 0
    name = (getattr(shape, "name", None) or "").strip()
    token_from_name = _shape_name_token(name)

    if getattr(shape, "has_text_frame", False):
        tf = shape.text_frame
        text_key = _frame_placeholder_key(tf)

        # Prefer the placeholder written in the slide text (source of truth).
        # Shape name is only a fallback when text has no {{TOKEN}}, or names the same token.
        if text_key and text_key in tokens:
            _fill_textframe_multiline(tf, tokens[text_key])
            count += 1
        elif token_from_name and token_from_name in tokens and not text_key:
            # Named slot with no inline placeholder (or empty) — fill that slot only
            _fill_textframe_multiline(tf, tokens[token_from_name])
            count += 1
        elif token_from_name and text_key and token_from_name == text_key:
            _fill_textframe_multiline(tf, tokens[token_from_name])
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
                    _fill_textframe_multiline(shape.text_frame, label)
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
            if not getattr(shape, "has_text_frame", False):
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


def inject_pptx_tokens(prs: Presentation, tokens: dict[str, str]) -> int:
    """Replace all {{TOKEN}} placeholders. Returns # of text regions changed."""
    tokens = sanitize_token_map(tokens)
    changed = 0
    for slide in prs.slides:
        for shape in _iter_shapes(slide.shapes):
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


def generate_worship_pptx(
    data: WorshipData,
    *,
    master: Optional[MasterSource] = None,
    allow_remote: bool = True,
) -> BytesIO:
    """
    Open the user-provided master PPTX and inject weekly worship text only.

    Hymn numbers (e.g. 7장) are resolved to title + lyrics and written into
    {{HYMN_1}}, {{HYMN_1_LYRICS}}, {{HYMN_1_SCORE}}, etc.

    Line breaks are real paragraphs (Enter), never soft-break _x000B_ / \\v.
    Each shape is filled from its own {{TOKEN}} so hymn slots do not cross-contaminate.
    """
    if master is None:
        raise ValueError(
            "Master Worship PPT (.pptx)가 필요합니다. "
            "예배 PPT 마스터 파일을 먼저 업로드해 주세요."
        )

    tokens = sanitize_token_map(build_token_map(data, allow_remote=allow_remote))

    if not data.include_hymn_lyrics:
        for key in list(tokens):
            if "LYRICS" in key:
                if key.endswith("_LYRICS") or "_LYRICS_" in key:
                    tokens[key] = ""

    stream = _as_stream(master)
    prs = Presentation(stream)
    inject_pptx_tokens(prs, tokens)

    buffer = BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer
