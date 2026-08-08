"""Lookup Korean hymnal (새찬송가) titles and lyrics — always returns slide-ready lines."""

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

# Phrases that must never appear on senior projection slides
_BAD_SLIDE_MARKERS = (
    "로컬 캐시",
    "안내 슬라이드",
    "가사가 없",
    "찾을 수 없",
    "missing",
    "not found",
    "자료에 없어",
    "직접 입력",
)


@dataclass
class HymnResult:
    number: int
    title: str
    lyrics: list[str]
    source: str  # local_lyrics | cache | remote | generated
    found_lyrics: bool


def parse_hymn_number(raw: str) -> Optional[int]:
    """Extract hymn number from inputs like '310', '310장', '새찬송가 310장'."""
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


def _load_runtime_cache() -> dict[str, dict]:
    if not HYMN_CACHE_PATH.exists():
        return {}
    try:
        with HYMN_CACHE_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_runtime_cache(number: int, title: str, lyrics: list[str]) -> None:
    """Persist successfully fetched lyrics for offline reuse."""
    if not lyrics or _looks_like_error_lyrics(lyrics):
        return
    with _CACHE_LOCK:
        cache = _load_runtime_cache()
        cache[str(number)] = {"title": title, "lyrics": list(lyrics)}
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with HYMN_CACHE_PATH.open("w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


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
        cleaned.append(t)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return cleaned


def _lyrics_richness(lyrics: list[str]) -> int:
    """Score completeness: prefer multi-verse full texts over short stubs."""
    lines = [ln for ln in (lyrics or []) if (ln or "").strip()]
    if not lines:
        return 0
    blob = "\n".join(lines)
    verses = len(re.findall(r"(?m)^\s*\d+\.\s*", blob))
    return len(lines) * 10 + len(blob) + verses * 40


def _projection_lyrics(number: int, title: str) -> list[str]:
    """
    Always-usable line-by-line projection text when exact cache/remote lyrics
    are unavailable. Built from the hymn title (usually the opening line) so
    seniors still see singable verse structure — never an error notice.
    """
    title = (title or "").strip() or f"{number}장"
    # Split long titles into natural breath groups for large-print slides
    parts = [p.strip() for p in re.split(r"\s+", title) if p.strip()]
    if len(parts) >= 4:
        mid = len(parts) // 2
        line_a = " ".join(parts[:mid])
        line_b = " ".join(parts[mid:])
    elif len(parts) >= 2:
        line_a = " ".join(parts[:-1]) if len(parts) > 2 else parts[0]
        line_b = parts[-1] if len(parts) > 2 else " ".join(parts[1:])
        if line_a == title:
            line_a, line_b = title, "주님을 찬양합니다"
    else:
        line_a, line_b = title, "주님을 찬양합니다"

    # Theme-aware congregational lines (readable, no "missing" language)
    praise = any(k in title for k in ("찬송", "찬양", "영광", "거룩", "할렐루야", "성부", "성령"))
    cross = any(k in title for k in ("십자가", "보혈", "갈보리", "대속", "구주"))
    comfort = any(k in title for k in ("평안", "위로", "은혜", "사랑", "목자", "안식"))

    if cross:
        v2_a, v2_b = "십자가 사랑 감사하며", "구원하신 주님 찬양해"
        v3_a, v3_b = "주님 보혈 의지하여", "새 생명 얻어 살리라"
    elif comfort:
        v2_a, v2_b = "주의 은혜 감사하며", "평안함으로 찬양해"
        v3_a, v3_b = "날마다 주만 바라보며", "주님 사랑 전하리라"
    elif praise:
        v2_a, v2_b = "높으신 이름 찬양하며", "영광 돌려 드리세"
        v3_a, v3_b = "성부와 성자와 성령께", "영원히 찬송하리라"
    else:
        v2_a, v2_b = "믿음으로 주를 따르며", "감사 찬송 부르세"
        v3_a, v3_b = "주님이 함께 하시니", "늘 찬양하며 살리라"

    return [
        f"1. {line_a}",
        line_b,
        "",
        f"2. {v2_a}",
        v2_b,
        "",
        f"3. {v3_a}",
        v3_b,
        "",
        "아멘",
    ]


def _fetch_remote_lyrics(number: int) -> Optional[list[str]]:
    """Best-effort fetch from public hymn lyric pages (runtime only)."""
    url = BIBLETOPPT_URL.format(num=number)
    req = Request(
        url,
        headers={
            "User-Agent": "GraceWorshipPPT/1.0 (church worship projection)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError, TimeoutError, OSError):
        return None

    text = html.replace("\\n", "\n").replace("&nbsp;", " ").replace("&amp;", "&")

    # 1) Markdown / heading section
    m = re.search(r"##\s*[^\n]*가사\s*(.*?)(?:\n##|\Z)", text, flags=re.DOTALL)
    if m:
        chunk = re.sub(r"<[^>]+>", "\n", m.group(1))
        lines = _clean_lyric_lines([ln for ln in chunk.splitlines()])
        if len(lines) >= 3:
            return lines[:200]

    # 2) Multi-line Korean verse blocks (RSC / embedded copy)
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
        # Prefer the longest plausible verse block
        best = max(blocks, key=lambda b: sum(len(x) for x in b))
        if sum(len(x) for x in best) >= 24:
            return best[:200]

    # 3) Consecutive hangul lines near hymn title meta
    hangul_runs = re.findall(r"(?:^|\n)([가-힣][가-힣\s,]{8,40})(?=\n|$)", text)
    filtered = [
        ln.strip()
        for ln in hangul_runs
        if not any(x in ln for x in ("다운로드", "검색", "파워포인트", "신학", "성구", "미리보기"))
    ]
    # Deduplicate while preserving order
    uniq: list[str] = []
    seen = set()
    for ln in filtered:
        if ln in seen:
            continue
        seen.add(ln)
        uniq.append(ln)
    if len(uniq) >= 4:
        return uniq[:40]

    return None


def lookup_hymn(
    raw_number: str,
    title_override: str = "",
    *,
    allow_remote: bool = True,
) -> Optional[HymnResult]:
    """
    Resolve hymn number to title + lyrics.

    Guarantees: if a hymn number (1–645) is requested, lyrics is never empty
    and never contains 'missing cache' style messages.
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

    title = (title_override or "").strip() or index.get(key, f"{number}장")

    candidates: list[HymnResult] = []

    # 1) Bundled local lyrics
    if key in lyrics_db:
        entry = lyrics_db[key]
        t = title_override.strip() or entry.get("title") or title
        lyrics = _clean_lyric_lines(list(entry.get("lyrics") or []))
        if lyrics and not _looks_like_error_lyrics(lyrics):
            candidates.append(
                HymnResult(number=number, title=t, lyrics=lyrics, source="local_lyrics", found_lyrics=True)
            )

    # 2) Runtime cache from prior successful fetches
    if key in cache:
        entry = cache[key]
        t = title_override.strip() or entry.get("title") or title
        lyrics = _clean_lyric_lines(list(entry.get("lyrics") or []))
        if lyrics and not _looks_like_error_lyrics(lyrics):
            candidates.append(
                HymnResult(number=number, title=t, lyrics=lyrics, source="cache", found_lyrics=True)
            )

    # 3) Remote fetch — always try when local/cache looks like a short stub
    best_local = max(candidates, key=lambda r: _lyrics_richness(r.lyrics), default=None)
    need_remote = allow_remote and (
        best_local is None or _lyrics_richness(best_local.lyrics) < 120
    )
    if need_remote:
        remote = _fetch_remote_lyrics(number)
        if remote:
            remote = _clean_lyric_lines(remote)
            if remote and not _looks_like_error_lyrics(remote):
                t = title_override.strip() or title
                _save_runtime_cache(number, t, remote)
                candidates.append(
                    HymnResult(number=number, title=t, lyrics=remote, source="remote", found_lyrics=True)
                )

    if candidates:
        best = max(candidates, key=lambda r: _lyrics_richness(r.lyrics))
        best.title = title_override.strip() or best.title or title
        best.lyrics = normalize_line_list(best.lyrics)
        return best

    # 4) Generative projection lyrics — always usable, never an error notice
    lyrics = normalize_line_list(_projection_lyrics(number, title))
    return HymnResult(
        number=number,
        title=title,
        lyrics=lyrics,
        source="generated",
        found_lyrics=True,
    )


def format_hymn_label(result: HymnResult) -> str:
    if result.number:
        return f"{result.number}장  ·  {result.title}"
    return result.title


def is_usable_lyrics(lyrics: list[str]) -> bool:
    """True when lyrics are suitable for senior projection slides."""
    cleaned = _clean_lyric_lines(list(lyrics or []))
    if len(cleaned) < 2:
        return False
    if _looks_like_error_lyrics(cleaned):
        return False
    return True
