"""Lookup Korean hymnal (찬송가) titles and lyrics — always returns slide-ready lines."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from text_normalize import normalize_breaks, normalize_line_list

DATA_DIR = Path(__file__).resolve().parent / "data"
HYMN_INDEX_PATH = DATA_DIR / "hymn_index.json"
HYMN_LYRICS_PATH = DATA_DIR / "hymns_lyrics.json"
HYMN_CACHE_PATH = DATA_DIR / "hymns_lyrics_cache.json"

BIBLETOPPT_URL = "https://bibletoppt.com/hymn/lyrics/{num:03d}"

_CACHE_LOCK = threading.Lock()
_REMOTE_MEMO: dict[int, list[str]] = {}
_REMOTE_MEMO_LOCK = threading.Lock()

# Phrases that must never appear on projection slides
_BAD_SLIDE_MARKERS = (
    "로컬 캐시",
    "안내 슬라이드",
    "가사가 없",
    "찾을 수 없",
    "missing",
    "not found",
    "자료에 없어",
    "직접 입력",
    "불러오지 못했",
)


@dataclass
class HymnResult:
    number: int
    title: str
    lyrics: list[str]
    source: str  # local_lyrics | cache | remote | generated
    found_lyrics: bool


def parse_hymn_number(raw: str) -> Optional[int]:
    """Extract hymn number from inputs like '310', '310장', '찬송가 310장'."""
    if not raw:
        return None
    text = raw.strip()
    m = re.search(r"(\d{1,3})", text)
    if not m:
        return None
    num = int(m.group(1))
    if 1 <= num <= 645:
        return num
    return None


@lru_cache(maxsize=1)
def _load_index() -> dict[str, str]:
    if not HYMN_INDEX_PATH.exists():
        return {}
    with HYMN_INDEX_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_lyrics() -> dict[str, dict]:
    if not HYMN_LYRICS_PATH.exists():
        return {}
    with HYMN_LYRICS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_runtime_cache() -> dict[str, dict]:
    if not HYMN_CACHE_PATH.exists():
        return {}
    try:
        with HYMN_CACHE_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_runtime_cache(number: int, title: str, lyrics: list[str]) -> None:
    """Persist successfully fetched lyrics for offline reuse."""
    if not lyrics or _looks_like_error_lyrics(lyrics):
        return
    if _looks_like_incomplete_stub(lyrics):
        return
    with _CACHE_LOCK:
        cache = dict(_load_runtime_cache())
        new_entry = {"title": title, "lyrics": list(lyrics)}
        prev = cache.get(str(number))
        if prev == new_entry:
            return
        cache[str(number)] = new_entry
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with HYMN_CACHE_PATH.open("w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            _load_runtime_cache.cache_clear()
        except OSError:
            pass


def _merge_into_local_lyrics(number: int, title: str, lyrics: list[str]) -> None:
    """Promote complete lyrics into the permanent offline hymns_lyrics.json."""
    if not lyrics or _looks_like_error_lyrics(lyrics) or _looks_like_incomplete_stub(lyrics):
        return
    body = [str(ln).rstrip() for ln in lyrics]
    hangul = len(re.findall(r"[가-힣]", "\n".join(body)))
    if hangul < 60:
        return
    with _CACHE_LOCK:
        db = {}
        if HYMN_LYRICS_PATH.exists():
            try:
                db = json.loads(HYMN_LYRICS_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                db = {}
        key = str(number)
        prev = db.get(key) if isinstance(db.get(key), dict) else None
        prev_lines = list((prev or {}).get("lyrics") or [])
        prev_ok = (
            prev_lines
            and not _looks_like_incomplete_stub(prev_lines)
            and not _looks_like_error_lyrics(prev_lines)
        )
        if prev_ok and _lyrics_richness(prev_lines) >= _lyrics_richness(body):
            return
        db[key] = {"title": (title or "").strip() or (prev or {}).get("title") or "", "lyrics": body}
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(db, ensure_ascii=False, indent=2) + "\n"
            tmp = HYMN_LYRICS_PATH.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(HYMN_LYRICS_PATH)
            _load_lyrics.cache_clear()
        except OSError:
            try:
                HYMN_LYRICS_PATH.write_text(
                    json.dumps(db, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                _load_lyrics.cache_clear()
            except OSError:
                pass


def _persist_good_lyrics(number: int, title: str, lyrics: list[str]) -> None:
    """Save complete lyrics to cache + permanent local DB."""
    finalized = _finalize_lyrics(list(lyrics or []))
    if not finalized or _looks_like_error_lyrics(finalized) or _looks_like_incomplete_stub(finalized):
        return
    _save_runtime_cache(number, title, finalized)
    _merge_into_local_lyrics(number, title, finalized)


def _looks_like_error_lyrics(lyrics: list[str]) -> bool:
    blob = " ".join(lyrics or []).lower()
    return any(m.lower() in blob for m in _BAD_SLIDE_MARKERS)


def _clean_lyric_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for ln in normalize_line_list(lines):
        t = normalize_breaks(ln).strip()
        if not t:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        if any(m in t for m in _BAD_SLIDE_MARKERS):
            continue
        if t.startswith("http") or "다운로드" in t or "파워포인트" in t:
            continue
        if "신학적" in t or "연관 성구" in t:
            continue
        # Drop edition branding lines that are not lyrics
        if re.fullmatch(r"(새)?찬송가\s*\d+\s*장", t):
            continue
        cleaned.append(t)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return cleaned


_VERSE_START_RE = re.compile(r"^\s*\d+\s*[\.．、)]\s*")
_REFRAIN_START_RE = re.compile(r"^(후렴|합창|코러스|Refrain|Chorus)\s*[:：]?\s*", re.I)
_AMEN_TAIL_RE = re.compile(r"\s*아멘\.?\s*$", re.I)


def _split_verse_groups(lines: list[str]) -> list[list[str]]:
    """Split lyric lines into verse/block groups."""
    groups: list[list[str]] = []
    buf: list[str] = []
    for ln in lines:
        if not str(ln).strip():
            if buf:
                groups.append(buf)
                buf = []
            continue
        text = str(ln).rstrip()
        if _VERSE_START_RE.match(text) and buf:
            groups.append(buf)
            buf = [text]
        else:
            buf.append(text)
    if buf:
        groups.append(buf)
    return groups


def _expand_refrain(lyrics: list[str]) -> list[str]:
    """
    If a hymn prints 후렴 only once (usually after verse 1), repeat it after
    every numbered verse for projection/singing.

    Idempotent: strips every 후렴 block first, then re-attaches once per verse
    so cached/already-expanded lyrics are not doubled.
    """
    lines = [str(ln).rstrip() for ln in (lyrics or [])]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return []

    groups = _split_verse_groups(lines)
    if len(groups) < 2:
        return lines

    refrain: list[str] | None = None
    for group in groups:
        for li, ln in enumerate(group):
            if not _REFRAIN_START_RE.match(ln):
                continue
            refrain = [x for x in group[li:] if str(x).strip()]
            break
        if refrain is not None:
            break

    if not refrain:
        return lines

    # 아멘 is often only on the final printed refrain — keep it at the very end
    has_amen = bool(lines and _AMEN_TAIL_RE.search(lines[-1].strip()))
    refrain_core: list[str] = []
    for ln in refrain:
        cleaned = _AMEN_TAIL_RE.sub("", ln).rstrip()
        if cleaned:
            refrain_core.append(cleaned)
    if not refrain_core:
        return lines

    # Strip every refrain occurrence so re-attach is safe to run repeatedly
    cleaned_groups: list[list[str]] = []
    for group in groups:
        cut = len(group)
        for li, ln in enumerate(group):
            if _REFRAIN_START_RE.match(ln):
                cut = li
                break
        head = [x for x in group[:cut] if str(x).strip()]
        if head:
            cleaned_groups.append(head)

    verse_groups = [g for g in cleaned_groups if _VERSE_START_RE.match(g[0])]
    if len(verse_groups) < 2:
        return lines

    out: list[str] = []
    for group in cleaned_groups:
        if out:
            out.append("")
        out.extend(group)
        if not _VERSE_START_RE.match(group[0]):
            continue
        out.append("")
        out.extend(refrain_core)

    if has_amen and out:
        if not _AMEN_TAIL_RE.search(out[-1]):
            out[-1] = (out[-1] + " 아멘").strip()
    return out


def _finalize_lyrics(lyrics: list[str]) -> list[str]:
    """Clean + expand refrain for projection-ready lyric lines."""
    cleaned = _clean_lyric_lines(list(lyrics or []))
    return normalize_line_list(_expand_refrain(cleaned))


def _lyrics_richness(lyrics: list[str]) -> int:
    """Score completeness: prefer multi-verse full texts over short stubs."""
    lines = [ln for ln in (lyrics or []) if (ln or "").strip()]
    if not lines:
        return 0
    blob = "\n".join(lines)
    verses = len(re.findall(r"(?m)^\s*\d+\s*[\.．、)]\s*", blob))
    hangul = len(re.findall(r"[가-힣]", blob))
    if verses == 0 and len(lines) < 6:
        return len(lines) * 3 + hangul
    return len(lines) * 10 + hangul + verses * 40


def _looks_like_incomplete_stub(lyrics: list[str]) -> bool:
    """True when lyrics look truncated / stubby and should be replaced by a fuller source."""
    lines = [ln.strip() for ln in (lyrics or []) if (ln or "").strip()]
    if not lines:
        return True
    blob = "\n".join(lines)
    hangul = len(re.findall(r"[가-힣]", blob))
    verses = len(re.findall(r"(?m)^\s*\d+\s*[\.．、)]\s*", blob))
    last = lines[-1] if lines else ""
    amen = bool(_AMEN_TAIL_RE.search(last))
    # Compact amen-doxologies (e.g. 1장) are complete
    if verses == 0 and 4 <= len(lines) <= 5 and amen:
        return False
    if hangul < 30:
        return True
    if len(lines) <= 3 and hangul < 90:
        return True
    # Unnumbered 4–6 lines without 아멘 — verse 1 of a longer hymn (e.g. 8장)
    if verses == 0 and 4 <= len(lines) <= 6 and not amen:
        return True
    # Numbered verse groups that are almost empty (e.g. "1. 이 몸의" alone)
    for group in _split_verse_groups(list(lyrics or [])):
        if not group or not _VERSE_START_RE.match(group[0]):
            continue
        m = re.match(r"^\s*\d+\s*[\.．、)]\s*(.*)$", group[0])
        head_h = len(re.findall(r"[가-힣]", (m.group(1) if m else "")))
        body_h = len(re.findall(r"[가-힣]", "\n".join(group[1:])))
        if head_h < 8 and body_h < 25:
            return True
    if verses == 1 and len(lines) <= 6:
        return True
    if verses >= 2 and hangul / max(verses, 1) < 22:
        return True
    if verses >= 2 and len(lines) < verses * 2:
        return True
    return False


def _should_try_remote(lyrics: list[str] | None) -> bool:
    """Whether a fuller remote copy is worth attempting."""
    if not lyrics:
        return True
    if _looks_like_error_lyrics(lyrics) or _looks_like_incomplete_stub(lyrics):
        return True
    lines = [ln.strip() for ln in lyrics if (ln or "").strip()]
    hangul = len(re.findall(r"[가-힣]", "\n".join(lines)))
    verses = len(re.findall(r"(?m)^\s*\d+\s*[\.．、)]\s*", "\n".join(lines)))
    # Title-only / one-liner placeholders
    if len(lines) <= 2 and hangul < 40:
        return True
    # Numbered but clearly first-verse-only
    if verses == 1 and hangul < 120:
        return True
    last = lines[-1] if lines else ""
    amen = bool(_AMEN_TAIL_RE.search(last))
    # Unnumbered 4–6 lines without 아멘 — often verse 1 of a longer hymn (e.g. 8장)
    if verses == 0 and 4 <= len(lines) <= 6 and hangul >= 48 and not amen:
        return True
    # Longer unnumbered body that still looks truncated (no doxology close)
    if verses == 0 and len(lines) >= 7 and hangul < 160 and not amen:
        return True
    return False


def _looks_like_real_hymn(lyrics: list[str]) -> bool:
    """Reject title-filler and scrape junk; require real hymn structure."""
    lines = [ln.strip() for ln in (lyrics or []) if (ln or "").strip()]
    if len(lines) < 4:
        return False
    if _looks_like_error_lyrics(lines):
        return False
    blob = "\n".join(lines)
    verses = len(re.findall(r"(?m)^\s*\d+\s*[\.．、)]\s*", blob))
    hangul = len(re.findall(r"[가-힣]", blob))
    if hangul < 20:
        return False
    if _looks_like_incomplete_stub(lines) and hangul < 100:
        # Still accept as "real enough" for candidate list, but ranking will prefer fuller text
        pass
    if verses >= 2 and hangul >= 60:
        return True
    if len(lines) >= 8 and hangul >= 40:
        return True
    if verses >= 1 and len(lines) >= 6 and hangul >= 50:
        return True
    # Single-verse hymns (e.g. doxology) with solid hangul density
    if verses == 0 and len(lines) >= 4 and hangul >= 30:
        return True
    return False


def _projection_lyrics(number: int, title: str) -> list[str]:
    """Placeholder only — never invent fake hymn verses for projection."""
    title = (title or "").strip() or f"{number}장"
    return [
        f"찬송가 {number}장" if number else "찬송가",
        title,
        "",
        "(찬송가 가사를 불러오지 못했습니다.",
        "번호 확인 후 다시 불러오거나 가사를 직접 입력해 주세요.)",
    ]


def _fetch_remote_lyrics_once(number: int) -> Optional[list[str]]:
    """Single attempt to scrape public hymn lyric pages."""
    import html as html_lib

    url = BIBLETOPPT_URL.format(num=number)
    req = Request(
        url,
        headers={
            "User-Agent": "GraceWorshipPPT/1.0 (church worship projection)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(req, timeout=6) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError, TimeoutError, OSError):
        return None

    text = raw_html.replace("&nbsp;", " ").replace("&amp;", "&")

    # 1) bibletoppt structured verses: "1절" + whitespace-pre-line body
    structured = re.findall(
        r"<p[^>]*font-medium[^>]*>\s*(\d+)\s*(?:<!--\s*-->)?\s*절\s*</p>\s*"
        r"<p[^>]*whitespace-pre-line[^>]*>(.*?)</p>",
        text,
        flags=re.DOTALL | re.I,
    )
    if structured:
        assembled: list[str] = []
        for verse_no, body in structured:
            chunk = re.sub(r"<[^>]+>", "\n", body)
            chunk = html_lib.unescape(chunk)
            lines = _clean_lyric_lines(chunk.splitlines())
            if not lines:
                continue
            if assembled and assembled[-1] != "":
                assembled.append("")
            first = lines[0]
            if not re.match(rf"^\s*{re.escape(verse_no)}\s*[\.．、)]", first):
                lines[0] = f"{verse_no}. {first}"
            assembled.extend(lines)
        if assembled and (
            _looks_like_real_hymn(assembled) or len([ln for ln in assembled if ln.strip()]) >= 4
        ):
            return assembled[:240]

    # 1b) Doxology / short hymns: lone whitespace-pre-line blocks (no "N절" headers)
    pre_blocks = re.findall(
        r"<p[^>]*whitespace-pre-line[^>]*>(.*?)</p>",
        text,
        flags=re.DOTALL | re.I,
    )
    if pre_blocks:
        assembled = []
        for body in pre_blocks:
            chunk = re.sub(r"<[^>]+>", "\n", body)
            chunk = html_lib.unescape(chunk)
            lines = _clean_lyric_lines(chunk.splitlines())
            if not lines:
                continue
            # Skip UI chrome that sneaks into pre-line
            blob = "\n".join(lines)
            if any(x in blob for x in ("다운로드", "파워포인트", "신학적", "연관 성구")):
                continue
            if assembled and assembled[-1] != "":
                assembled.append("")
            assembled.extend(lines)
        if assembled and (
            _looks_like_real_hymn(assembled) or len([ln for ln in assembled if ln.strip()]) >= 4
        ):
            return assembled[:240]

    # 2) Markdown / heading section
    m = re.search(r"##\s*[^\n]*가사\s*(.*?)(?:\n##|\Z)", text, flags=re.DOTALL)
    if m:
        chunk = re.sub(r"<[^>]+>", "\n", m.group(1))
        chunk = html_lib.unescape(chunk)
        lines = _clean_lyric_lines([ln for ln in chunk.splitlines()])
        if len(lines) >= 3 and not _looks_like_incomplete_stub(lines):
            return lines[:240]

    # 3) Multi-line Korean verse blocks
    blocks: list[list[str]] = []
    for m in re.finditer(
        r"([가-힣][가-힣\s,\.]{6,}(?:\n[가-힣][가-힣\s,\.]{4,}){2,8})",
        text,
    ):
        chunk = m.group(1)
        if any(x in chunk for x in ("다운로드", "신학적", "연관 성구", "번역이다", "파워포인트", "예배 준비")):
            continue
        lines = _clean_lyric_lines(chunk.splitlines())
        if len(lines) >= 3:
            blocks.append(lines)

    if blocks:
        ranked = sorted(blocks, key=lambda b: _lyrics_richness(b), reverse=True)
        for best in ranked:
            if _looks_like_real_hymn(best) and not _looks_like_incomplete_stub(best):
                return best[:240]

    # 4) Numbered verse extracts
    numbered = re.findall(
        r"((?:^|\n)\s*\d+\s*[\.．]\s*[가-힣][^\n]*(?:\n(?!\s*\d+\s*[\.．])[^\n]+){0,8})",
        text,
    )
    if numbered:
        assembled = []
        for chunk in numbered:
            lines = _clean_lyric_lines(chunk.splitlines())
            if not lines:
                continue
            if assembled and assembled[-1] != "":
                assembled.append("")
            assembled.extend(lines)
        if _looks_like_real_hymn(assembled) and not _looks_like_incomplete_stub(assembled):
            return assembled[:240]

    return None


def _fetch_remote_lyrics(number: int, *, retries: int = 1) -> Optional[list[str]]:
    """Best-effort fetch with retries — network flakes should not drop Sunday lyrics."""
    import time

    memo: Optional[list[str]] = None
    with _REMOTE_MEMO_LOCK:
        memo = _REMOTE_MEMO.get(number)
        if memo and not _should_try_remote(memo):
            return list(memo)

    best: Optional[list[str]] = list(memo) if memo else None
    for attempt in range(max(1, retries)):
        got = _fetch_remote_lyrics_once(number)
        if got:
            if best is None or _lyrics_richness(got) > _lyrics_richness(best):
                best = got
            # Only stop early when the copy looks complete enough
            if (
                _looks_like_real_hymn(got)
                and not _looks_like_incomplete_stub(got)
                and not _should_try_remote(got)
            ):
                with _REMOTE_MEMO_LOCK:
                    _REMOTE_MEMO[number] = list(got)
                return got
        if attempt + 1 < retries:
            time.sleep(0.6 * (attempt + 1))
    if best:
        with _REMOTE_MEMO_LOCK:
            prev = _REMOTE_MEMO.get(number)
            if prev is None or _lyrics_richness(best) >= _lyrics_richness(prev):
                _REMOTE_MEMO[number] = list(best)
    return best


def lookup_hymn(
    raw_number: str,
    title_override: str = "",
    *,
    allow_remote: bool = True,
    force_remote: bool = False,
) -> Optional[HymnResult]:
    """
    Resolve hymn number to title + full lyrics.

    Prefers the richest complete lyric text (remote full song over short local stubs).
    Labels use 「찬송가」 (not 「새찬송가」).
    When force_remote=True, always compare against a remote fetch (HTML / Sunday path).
    """
    number = parse_hymn_number(raw_number)
    if number is None and not title_override.strip():
        return None

    if number is None:
        title = title_override.strip()
        lyrics = normalize_line_list(_projection_lyrics(0, title))
        return HymnResult(
            number=0,
            title=normalize_breaks(title).strip(),
            lyrics=lyrics,
            source="generated",
            found_lyrics=True,
        )

    index = _load_index()
    lyrics_db = _load_lyrics()
    cache = _load_runtime_cache()
    key = str(number)

    # Catalog title wins for numbered hymns. title_override only fills gaps
    # (never keep a previous hymn's title when the number changed).
    index_title = (index.get(key) or "").strip()
    override = (title_override or "").strip()
    title = index_title or override or f"{number}장"

    candidates: list[HymnResult] = []

    # 1) Bundled local lyrics
    if key in lyrics_db:
        entry = lyrics_db[key]
        t = index_title or entry.get("title") or override or title
        lyrics = _clean_lyric_lines(list(entry.get("lyrics") or []))
        if lyrics and not _looks_like_error_lyrics(lyrics) and len(lyrics) >= 4:
            candidates.append(
                HymnResult(number=number, title=t, lyrics=lyrics, source="local_lyrics", found_lyrics=True)
            )

    # 2) Runtime cache
    if key in cache:
        entry = cache[key]
        t = index_title or entry.get("title") or override or title
        lyrics = _clean_lyric_lines(list(entry.get("lyrics") or []))
        if lyrics and _looks_like_real_hymn(lyrics):
            candidates.append(
                HymnResult(number=number, title=t, lyrics=lyrics, source="cache", found_lyrics=True)
            )

    # 3) Remote — always when forced, or when local/cache looks thin/incomplete
    best_so_far = max(candidates, key=lambda r: _lyrics_richness(r.lyrics), default=None)
    need_remote = allow_remote and (
        force_remote
        or best_so_far is None
        or _should_try_remote(best_so_far.lyrics)
    )
    if need_remote:
        remote = _fetch_remote_lyrics(number)
        if remote:
            remote = _clean_lyric_lines(remote)
            if remote and (
                _looks_like_real_hymn(remote) or len([ln for ln in remote if ln.strip()]) >= 6
            ):
                t = index_title or override or title
                expanded = _finalize_lyrics(remote)
                candidates.append(
                    HymnResult(number=number, title=t, lyrics=expanded, source="remote", found_lyrics=True)
                )

    if candidates:
        # Prefer fullest complete lyrics — never keep a stub over a full song
        def _rank(r: HymnResult) -> tuple:
            body = [ln for ln in (r.lyrics or []) if (ln or "").strip()]
            hangul = len(re.findall(r"[가-힣]", "\n".join(body)))
            stub = 1 if _looks_like_incomplete_stub(r.lyrics) else 0
            thin = 1 if _should_try_remote(r.lyrics) else 0
            err = 1 if _looks_like_error_lyrics(r.lyrics) else 0
            verses = len(re.findall(r"(?m)^\s*\d+\s*[\.．、)]\s*", "\n".join(body)))
            return (
                -err,
                -stub,
                -thin,
                verses,
                hangul,
                len(body),
                _lyrics_richness(r.lyrics),
                1 if r.source == "remote" else 0,
            )

        best = max(candidates, key=_rank)
        best.title = index_title or best.title or override or title
        best.lyrics = _finalize_lyrics(best.lyrics)
        # Persist only newly fetched remote text. Rewriting the local DB on every
        # keystroke (OneDrive) is what made the worship-order form feel frozen.
        if (
            best.source == "remote"
            and best.found_lyrics
            and not _looks_like_error_lyrics(best.lyrics)
            and not _looks_like_incomplete_stub(best.lyrics)
        ):
            _persist_good_lyrics(number, best.title, best.lyrics)
        return best

    lyrics = _finalize_lyrics(_projection_lyrics(number, title))
    return HymnResult(
        number=number,
        title=title,
        lyrics=lyrics,
        source="generated",
        found_lyrics=False,
    )


def format_hymn_label(result: HymnResult) -> str:
    if result.number:
        return f"찬송가 {result.number}장  ·  {result.title}"
    return result.title


def is_usable_lyrics(lyrics: list[str]) -> bool:
    """True when lyrics are suitable for projection slides."""
    cleaned = _clean_lyric_lines(list(lyrics or []))
    if len(cleaned) < 2:
        return False
    if _looks_like_error_lyrics(cleaned):
        return False
    return True


def resolve_hymn_lyrics(
    raw_number: str,
    title_override: str = "",
    *,
    allow_remote: bool = True,
) -> HymnResult:
    """
    Projection-safe resolve. Prefers permanent local DB.
    Remote is only used when local/cache is missing or clearly truncated.
    """
    hit = lookup_hymn(
        raw_number,
        title_override,
        allow_remote=allow_remote,
        force_remote=False,
    )
    if hit is None:
        num = parse_hymn_number(raw_number) or 0
        title = (title_override or "").strip() or (f"{num}장" if num else "찬송가")
        return HymnResult(
            number=num,
            title=title,
            lyrics=_finalize_lyrics(_projection_lyrics(num, title)),
            source="generated",
            found_lyrics=False,
        )
    return hit


def warm_hymn_numbers(numbers: list[int] | list[str], *, allow_remote: bool = True) -> dict[str, HymnResult]:
    """Ensure given hymn numbers are resolved and persisted locally."""
    out: dict[str, HymnResult] = {}
    for raw in numbers:
        num = parse_hymn_number(str(raw))
        if not num:
            continue
        hit = resolve_hymn_lyrics(str(num), allow_remote=allow_remote)
        out[str(num)] = hit
    return out
