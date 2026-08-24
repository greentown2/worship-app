"""Professional typography helpers for worship PPT and printable PDF.

Provides:
- Korean-friendly keep-all line wrapping (never split Latin words mid-word)
- Responsive reading (인도자/회중) hierarchy parsing
- Scripture verse number formatting
- Slide pagination with optional slight font auto-scale (floor 30pt)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from text_normalize import normalize_breaks

# Senior readability floor (matches design.BODY_SIZE)
MIN_BODY_PT = 40
DEFAULT_BODY_PT = 40
DEFAULT_SLIDE_MAX_LINES = 7
DEFAULT_CONTENT_WIDTH_IN = 11.5


@dataclass
class TextSpan:
    text: str
    bold: bool = False
    superscript: bool = False
    relative_size: float = 1.0  # 1.0 = body size


@dataclass
class FormattedLine:
    role: str  # leader | congregation | verse | body | hymn | label
    spans: List[TextSpan] = field(default_factory=list)
    indent: int = 0  # 0=flush, 1=hanging/indented body, 2=deeper

    @property
    def plain(self) -> str:
        return "".join(s.text for s in self.spans)


# --- Smart keep-all wrapping -------------------------------------------------

_BREAK_AFTER = set(" \t，。、；：！？,.!?;:/)]}》」』")
_BREAK_BEFORE = set("([{《「『")


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x1100 <= code <= 0x11FF
        or 0x3130 <= code <= 0x318F
        or 0xAC00 <= code <= 0xD7A3
        or 0x4E00 <= code <= 0x9FFF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
    )


def _tokenize_keep_all(text: str) -> list[str]:
    """Tokenize so Latin words stay whole; CJK can break between syllables."""
    tokens: list[str] = []
    buf: list[str] = []
    mode: Optional[str] = None  # 'latin' | 'cjk' | 'space' | 'punct'

    def flush():
        nonlocal buf, mode
        if buf:
            tokens.append("".join(buf))
            buf = []
            mode = None

    for ch in text:
        if ch.isspace():
            if mode != "space":
                flush()
                mode = "space"
            buf.append(ch)
            continue

        if _is_cjk(ch) or ch in _BREAK_AFTER or ch in _BREAK_BEFORE:
            # Punctuation = hard break opportunity; Hangul = 2-syllable soft units
            # so compounds like "사랑하사" prefer staying together longer.
            if ch in _BREAK_AFTER or ch in _BREAK_BEFORE or not _is_cjk(ch):
                flush()
                tokens.append(ch)
                mode = None
                continue
            if mode != "cjk":
                flush()
                mode = "cjk"
            buf.append(ch)
            if len(buf) >= 2:
                flush()
            continue

        # Latin / digit / other — keep contiguous runs together
        if mode != "latin":
            flush()
            mode = "latin"
        buf.append(ch)

    flush()
    return tokens


def estimate_chars_per_line(
    font_pt: float,
    width_in: float = DEFAULT_CONTENT_WIDTH_IN,
    *,
    char_em: float = 0.92,
) -> int:
    """Rough Hangul-centric capacity for a line at the given point size."""
    char_w = max(0.12, (font_pt / 72.0) * char_em)
    return max(8, int(width_in / char_w))


def wrap_keep_all(text: str, max_chars: int) -> list[str]:
    """Wrap text like CSS word-break: keep-all / overflow-wrap: break-word."""
    text = normalize_breaks(text)
    if not text:
        return []
    if max_chars < 4:
        max_chars = 4

    # Preserve intentional newlines as hard breaks
    hard_parts = text.replace("\r\n", "\n").split("\n")
    lines: list[str] = []

    for part in hard_parts:
        part = part.strip()
        if not part:
            continue
        tokens = _tokenize_keep_all(part)
        current = ""
        for tok in tokens:
            if tok.isspace():
                # collapse leading spaces on a new line
                if not current:
                    continue
                candidate = current + tok
            else:
                candidate = current + tok

            if len(candidate.rstrip()) <= max_chars:
                current = candidate
                continue

            if current.strip():
                lines.append(current.rstrip())
                current = tok.lstrip() if tok.isspace() else tok
            else:
                # Single oversized Latin token — hard-split as last resort
                chunk = tok
                while len(chunk) > max_chars:
                    lines.append(chunk[:max_chars])
                    chunk = chunk[max_chars:]
                current = chunk

        if current.strip():
            lines.append(current.rstrip())

    return lines


def wrap_lines_keep_all(lines: Iterable[str], max_chars: int) -> list[str]:
    out: list[str] = []
    for line in lines:
        wrapped = wrap_keep_all(line, max_chars)
        out.extend(wrapped if wrapped else [])
    return out


# --- Responsive reading ------------------------------------------------------

_LEADER_RE = re.compile(
    r"^(?:[\(\[]?(?:인도자|인도|사회자|목사|리더|L|Leader)[\)\]]?[:：\.\)\]]\s*)",
    re.IGNORECASE,
)
_CONG_RE = re.compile(
    r"^(?:[\(\[]?(?:회중|다같이|모두|성도|회중함께|C|All|Congregation)[\)\]]?[:：\.\)\]]\s*)",
    re.IGNORECASE,
)
_TOGETHER_RE = re.compile(
    r"^(?:[\(\[]?(?:다함께|함께|합창)[\)\]]?[:：\.\)\]]\s*)",
    re.IGNORECASE,
)


def parse_responsive_reading(text: str) -> list[FormattedLine]:
    """Parse 교독문 into leader/congregation lines with hierarchy."""
    text = normalize_breaks(text)
    if not (text or "").strip():
        return []

    raw_lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    has_markers = any(
        _LEADER_RE.match(ln) or _CONG_RE.match(ln) or _TOGETHER_RE.match(ln)
        for ln in raw_lines
    )

    result: list[FormattedLine] = []
    if has_markers:
        for ln in raw_lines:
            if _LEADER_RE.match(ln):
                body = _LEADER_RE.sub("", ln).strip()
                result.append(
                    FormattedLine(
                        role="leader",
                        spans=[
                            TextSpan("인도자  ", bold=True, relative_size=0.85),
                            TextSpan(body, bold=False),
                        ],
                        indent=0,
                    )
                )
            elif _CONG_RE.match(ln) or _TOGETHER_RE.match(ln):
                body = _CONG_RE.sub("", ln)
                body = _TOGETHER_RE.sub("", body).strip()
                result.append(
                    FormattedLine(
                        role="congregation",
                        spans=[
                            TextSpan("회중  ", bold=True, relative_size=0.85),
                            TextSpan(body, bold=True),
                        ],
                        indent=1,
                    )
                )
            else:
                result.append(
                    FormattedLine(
                        role="body",
                        spans=[TextSpan(ln)],
                        indent=0,
                    )
                )
        return result

    # No markers: treat as plain paragraphs (still keep-all wrapped later)
    for ln in raw_lines:
        result.append(FormattedLine(role="body", spans=[TextSpan(ln)], indent=0))
    return result


def auto_tag_responsive_if_plain(text: str) -> str:
    """
    If the user pasted unmarked alternating lines, leave as-is.
    Helper kept for UI examples / future heuristics.
    """
    return text


# --- Scripture verses --------------------------------------------------------

_VERSE_RE = re.compile(r"^(\d{1,3})([\.\)\:：]?)\s+(.*)$")


def parse_scripture_verses(text: str) -> list[FormattedLine]:
    """Format scripture with bold/superscript-ready verse numbers + hanging indent."""
    text = normalize_breaks(text)
    if not (text or "").strip():
        return []

    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    result: list[FormattedLine] = []

    for ln in lines:
        m = _VERSE_RE.match(ln)
        if m:
            num, _sep, body = m.group(1), m.group(2), m.group(3).strip()
            result.append(
                FormattedLine(
                    role="verse",
                    spans=[
                        TextSpan(num, bold=True, superscript=True, relative_size=0.72),
                        TextSpan("  " + body, bold=False),
                    ],
                    indent=1,
                )
            )
        else:
            result.append(
                FormattedLine(role="body", spans=[TextSpan(ln)], indent=0)
            )
    return result


def parse_plain_paragraphs(text: str, role: str = "body") -> list[FormattedLine]:
    lines = [ln.strip() for ln in (text or "").replace("\r\n", "\n").split("\n") if ln.strip()]
    return [FormattedLine(role=role, spans=[TextSpan(ln)], indent=0) for ln in lines]


def parse_hymn_lyrics(lines: Sequence[str]) -> list[FormattedLine]:
    return [
        FormattedLine(role="hymn", spans=[TextSpan(ln.strip(), bold=True)], indent=0)
        for ln in lines
        if ln and ln.strip()
    ]


# --- Wrap formatted lines + paginate ----------------------------------------

def wrap_formatted_line(line: FormattedLine, max_chars: int) -> list[FormattedLine]:
    """Apply keep-all wrap while preserving role / first-span emphasis."""
    plain = line.plain
    # Reserve label width for leader/congregation prefixes
    prefix = ""
    body = plain
    prefix_spans: list[TextSpan] = []
    body_style = TextSpan("", bold=False)

    if line.role in ("leader", "congregation") and line.spans:
        # First span is the role label
        prefix = line.spans[0].text
        prefix_spans = [line.spans[0]]
        body = "".join(s.text for s in line.spans[1:])
        if line.spans[1:]:
            body_style = TextSpan(
                "",
                bold=line.spans[1].bold,
                relative_size=line.spans[1].relative_size,
            )
    elif line.role == "verse" and line.spans:
        # Keep verse number on first wrapped line only
        num_span = line.spans[0]
        body = "".join(s.text for s in line.spans[1:]).lstrip()
        wrapped_body = wrap_keep_all(body, max(6, max_chars - len(num_span.text) - 2))
        if not wrapped_body:
            return [line]
        out: list[FormattedLine] = []
        for i, w in enumerate(wrapped_body):
            if i == 0:
                out.append(
                    FormattedLine(
                        role="verse",
                        spans=[
                            TextSpan(
                                num_span.text,
                                bold=True,
                                superscript=True,
                                relative_size=num_span.relative_size,
                            ),
                            TextSpan("  " + w, bold=False),
                        ],
                        indent=1,
                    )
                )
            else:
                # hanging indent continuation
                out.append(
                    FormattedLine(
                        role="verse",
                        spans=[TextSpan("    " + w, bold=False)],
                        indent=2,
                    )
                )
        return out
    else:
        wrapped = wrap_keep_all(plain, max_chars)
        return [
            FormattedLine(
                role=line.role,
                spans=[
                    TextSpan(
                        w,
                        bold=any(s.bold for s in line.spans),
                        relative_size=line.spans[0].relative_size if line.spans else 1.0,
                    )
                ],
                indent=line.indent,
            )
            for w in wrapped
        ] or [line]

    # leader / congregation / generic with prefix
    budget = max(6, max_chars - len(prefix))
    wrapped_body = wrap_keep_all(body, budget)
    if not wrapped_body:
        return [line]

    out = []
    for i, w in enumerate(wrapped_body):
        if i == 0:
            spans = list(prefix_spans) + [
                TextSpan(w, bold=body_style.bold, relative_size=body_style.relative_size or 1.0)
            ]
            out.append(FormattedLine(role=line.role, spans=spans, indent=line.indent))
        else:
            pad = " " * min(len(prefix), 6)
            out.append(
                FormattedLine(
                    role=line.role,
                    spans=[
                        TextSpan(
                            pad + w,
                            bold=body_style.bold,
                            relative_size=body_style.relative_size or 1.0,
                        )
                    ],
                    indent=max(line.indent, 1),
                )
            )
    return out


def wrap_formatted_lines(lines: Sequence[FormattedLine], max_chars: int) -> list[FormattedLine]:
    out: list[FormattedLine] = []
    for line in lines:
        out.extend(wrap_formatted_line(line, max_chars))
    return out


@dataclass
class SlidePage:
    lines: list[FormattedLine]
    font_pt: float


def paginate_for_slides(
    lines: Sequence[FormattedLine],
    *,
    base_pt: float = DEFAULT_BODY_PT,
    min_pt: float = MIN_BODY_PT,
    max_lines: int = DEFAULT_SLIDE_MAX_LINES,
    width_in: float = DEFAULT_CONTENT_WIDTH_IN,
) -> list[SlidePage]:
    """
    Wrap + paginate content for senior slides.
    Slightly reduce font (down to min_pt) only when a page is barely over capacity;
    otherwise split into clean additional slides.
    """
    if not lines:
        return []

    def build_pages(font_pt: float) -> list[SlidePage]:
        max_chars = estimate_chars_per_line(font_pt, width_in)
        wrapped = wrap_formatted_lines(lines, max_chars)
        pages: list[SlidePage] = []
        for i in range(0, len(wrapped), max_lines):
            chunk = wrapped[i : i + max_lines]
            pages.append(SlidePage(lines=chunk, font_pt=font_pt))
        return pages or [SlidePage(lines=[], font_pt=font_pt)]

    pages = build_pages(base_pt)
    # If the last page is a tiny leftover of 1 line and we have many pages,
    # try one step smaller font to pull content up — only when it reduces page count.
    if len(pages) >= 2 and min_pt < base_pt:
        smaller = build_pages(min_pt)
        if len(smaller) < len(pages):
            return smaller
    return pages


def plain_lines_from_formatted(lines: Sequence[FormattedLine]) -> list[str]:
    return [ln.plain for ln in lines]
