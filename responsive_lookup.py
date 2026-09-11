"""Lookup 새찬송가 교독문 by number — auto-fill title + clean 인도자/회중 body."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app_paths import load_bundled_json
from text_normalize import normalize_breaks

_JUNK_MARKERS = (
    "728x90",
    "게시글 관리",
    "카테고리의 다른 글",
    "카테고리",
    "태그",
    "이전글",
    "다음글",
    "댓글",
    "공감",
    "스크랩",
    "신고",
    "블로그",
    "티스토리",
    "copyright",
    "http://",
    "https://",
    "www.",
)


@dataclass
class ResponsiveResult:
    number: int
    title: str
    body: str
    source: str  # local | generated | missing
    found: bool


def parse_responsive_number(raw: str) -> Optional[int]:
    """
    Extract 교독문 number only from explicit forms:
      '13', '13번', '교독문 13', '교독문 13번'
    Never treat '시편 23편' as 교독문 23.
    """
    if not raw:
        return None
    text = normalize_breaks(raw).strip()

    m = re.search(r"교독문\s*(\d{1,3})\s*번?", text)
    if m:
        num = int(m.group(1))
        if 1 <= num <= 137:
            return num

    # '13번' (not '23편')
    m = re.search(r"(?<![가-힣0-9])(\d{1,3})\s*번(?![가-힣])", text)
    if m:
        num = int(m.group(1))
        if 1 <= num <= 137:
            return num

    # Bare digits only
    m = re.fullmatch(r"\s*(\d{1,3})\s*", text)
    if m:
        num = int(m.group(1))
        if 1 <= num <= 137:
            return num
    return None


def _match_index_title(raw: str) -> Optional[int]:
    """Match '시편 23편' style title to 교독문 number via index (not digit scrape)."""
    text = normalize_breaks(raw or "").strip()
    if not text:
        return None
    # Strip leading 교독문 N번 if present — handled by parse
    text = re.sub(r"^교독문\s*\d{1,3}\s*번?\s*[·.\-]?\s*", "", text).strip()
    # Bare digits / empty after strip must not fuzzy-match every title
    if not text or re.fullmatch(r"\d{1,3}", text):
        return None
    index = _load_index()
    # Exact match first
    for k, title in index.items():
        title = (title or "").strip()
        if title and text == title:
            return int(k)
    # Containment (longer side wins to reduce false positives)
    for k, title in index.items():
        title = (title or "").strip()
        if not title:
            continue
        if text in title or title in text:
            return int(k)
    # Normalize spaces: 시편23편 ↔ 시편 23편
    compact = re.sub(r"\s+", "", text)
    for k, title in index.items():
        if compact and compact == re.sub(r"\s+", "", title or ""):
            return int(k)
    return None


def _load_readings() -> dict[str, dict]:
    raw = load_bundled_json("responsive_readings.json")
    return {
        str(k): v
        for k, v in (raw or {}).items()
        if not str(k).startswith("_") and isinstance(v, dict)
    }


def _load_index() -> dict[str, str]:
    raw = load_bundled_json("responsive_index.json")
    return {
        str(k): str(v or "")
        for k, v in (raw or {}).items()
        if not str(k).startswith("_")
    }


def _is_junk_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return True
    low = s.lower()
    if any(m.lower() in low for m in _JUNK_MARKERS):
        return True
    if re.fullmatch(r"[\d\W_]+", s):
        return True
    if len(s) <= 2 and not re.search(r"[가-힣]", s):
        return True
    return False


# Biblical / liturgical clause endings (며/고 are valid poetic half-verse ends)
_COMPLETE_END_RE = re.compile(
    r"(다|라|요|까|나이다|도다|로다|소서|리이다|리로다|니이다|니이까|"
    r"시니이다|하시나이다|하시니이다|이니이다|이니이까|"
    r"시니|하시니|이시니|이니|리니|으니|하니|나니|인가|시냐|냐|"
    r"지어다|할지어다|돌릴지어다|"
    r"며|고|고도다|이로다|하리로다|살리로다|하오리니|하리니)\s*$"
)
_VERSE_CHIP_RE = re.compile(r"\s*\([^)]*\d+[^)]*\)\s*$")  # (1-4상), (시138:1-2)
# Only obvious mid-wrap scraps — do NOT treat poetic 며/고 as broken
_BROKEN_TAIL_RE = re.compile(
    r"(거짓|여호와의|주의|나의|그의|영광의|하나님의|그|및|"
    r"하심이|심이|말씀이|것을|입의)\s*$"
)
def _strip_verse_chip(body: str) -> str:
    return _VERSE_CHIP_RE.sub("", (body or "").strip()).strip()


def _clause_complete(body: str) -> bool:
    s = _strip_verse_chip(body)
    if len(s) < 4:
        return False
    if _BROKEN_TAIL_RE.search(s):
        return False
    return bool(_COMPLETE_END_RE.search(s))


def _needs_fragment_merge(body: str) -> bool:
    """True only for clearly broken wrap scraps (e.g. ends with 거짓)."""
    s = _strip_verse_chip(body)
    if not s or len(s) < 3:
        return True
    return bool(_BROKEN_TAIL_RE.search(s))


def _parse_role_lines(text: str) -> list[tuple[str, str]]:
    leader_re = re.compile(r"^(인도자|인도|Leader)\s*[:：]\s*(.*)$", re.I)
    cong_re = re.compile(r"^(회중|성도|All|People|다같이|다\s*같이)\s*[:：]\s*(.*)$", re.I)
    rows: list[tuple[str, str]] = []
    for ln in normalize_breaks(text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if _is_junk_line(s):
            if any(m in s for m in ("728x90", "게시글", "카테고리", "태그", "이전글")):
                break
            continue
        m = leader_re.match(s)
        if m:
            rows.append(("인도자", _strip_verse_chip(m.group(2) or "")))
            continue
        m = cong_re.match(s)
        if m:
            rows.append(("회중", _strip_verse_chip(m.group(2) or "")))
            continue
        # Unmarked fragment — attach later via repair if possible
        rows.append(("", _strip_verse_chip(s)))
    return [(r, b) for r, b in rows if b]


def _repair_role_lines(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    Fix scrape wrap errors: incomplete clauses absorb the next line
    (even if that next line was mis-tagged 인도자/회중), then enforce
    strict 인도자↔회중 alternation for projection.
    """
    if not rows:
        return []

    merged: list[tuple[str, str]] = []
    i = 0
    while i < len(rows):
        role, body = rows[i]
        if not role and merged:
            prev_role, prev_body = merged[-1]
            merged[-1] = (prev_role, f"{prev_body} {body}".strip())
            i += 1
            continue
        if not role:
            role = "인도자" if not merged else ("회중" if merged[-1][0] == "인도자" else "인도자")

        # Absorb wrap scraps: broken tails, or incomplete + short next fragment
        while i + 1 < len(rows):
            n_role, nxt = rows[i + 1]
            nxt = (nxt or "").strip()
            if not nxt:
                i += 1
                continue
            # '...하심이' + '라 사랑은…' → attach only a 1-syllable scrap
            soft = re.match(r"^([라요다까니])\s+(.{8,})$", nxt)
            if soft and not _clause_complete(body):
                body = f"{body}{soft.group(1)}".strip()
                rows[i + 1] = (n_role or role, soft.group(2).strip())
                if _clause_complete(body):
                    break
                continue
            absorb = False
            if _needs_fragment_merge(body):
                absorb = True
            elif not _clause_complete(body) and len(nxt) <= 18:
                absorb = True
            if not absorb:
                break
            body = f"{body} {nxt}".strip()
            i += 1
        merged.append((role, body))
        i += 1

    # Collapse same-role doubles only when previous clause still incomplete
    out: list[tuple[str, str]] = []
    for role, body in merged:
        if out and out[-1][0] == role and not _clause_complete(out[-1][1]):
            out[-1] = (role, f"{out[-1][1]} {body}".strip())
        else:
            out.append((role, body))
    return _enforce_alternating(out)


def _enforce_alternating(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    새찬송가 교독문은 거의 항상 인도자 → 회중 → 인도자 … 교대.
    줄바꿈 복구 후에도 같은 역할이 연속되면 내용을 유지한 채 역할만 교정한다.
    """
    if not rows:
        return []
    expect = "인도자"
    fixed: list[tuple[str, str]] = []
    for _role, body in rows:
        body = (body or "").strip()
        if not body:
            continue
        fixed.append((expect, body))
        expect = "회중" if expect == "인도자" else "인도자"
    return fixed


def sanitize_responsive_body(text: str) -> str:
    """
    Clean 교독문 for projection: repair broken wraps, drop verse chips,
    keep strict 인도자 / 회중 dialogue lines only (alternating).
    """
    rows = _repair_role_lines(_parse_role_lines(text))
    if not rows:
        return ""
    return "\n".join(f"{role}: {body}" for role, body in rows if body)


def lookup_responsive(raw: str, *, allow_remote: bool = True) -> ResponsiveResult:
    """
    Resolve 교독문 number → title + cleaned body.
    Accepts '13', '교독문 13번', or title '시편 23편' (via index match).
    """
    del allow_remote  # reserved; do not invent from scripture (causes mess)
    num = parse_responsive_number(raw)
    index = _load_index()
    readings = _load_readings()

    if num is None:
        num = _match_index_title(raw)
        if num is None:
            text = (raw or "").strip()
            return ResponsiveResult(0, text or "교독문", "", "missing", False)

    key = str(num)
    entry = readings.get(key) or {}
    title = (entry.get("title") or index.get(key) or f"교독문 {num}").strip()
    raw_body = normalize_breaks(entry.get("body") or "").strip()
    body = sanitize_responsive_body(raw_body)

    if body:
        return ResponsiveResult(num, title, body, "local", True)

    return ResponsiveResult(num, title, "", "missing", False)


def format_responsive_label(number: int, title: str) -> str:
    """Clear projection label: number + scripture reference title."""
    title = (title or "").strip()
    title = re.sub(r"^교독문\s*\d{1,3}\s*번?\s*[·.\-]?\s*", "", title).strip()
    if number and title:
        return f"교독문 {number}번  ·  {title}"
    if number:
        return f"교독문 {number}번"
    return title or "교독문"
