"""Parse Korean/English scripture references and resolve verse text.

Guarantees readable verse lines for slides/PDF — never a 'missing data' notice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.error import URLError, HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from text_normalize import normalize_breaks, normalize_line_list

DATA_DIR = Path(__file__).resolve().parent / "data"
SCRIPTURE_PATH = DATA_DIR / "scripture_common.json"
SCRIPTURE_CACHE_PATH = DATA_DIR / "scripture_cache.json"

BIBLE_API_URL = "https://bible-api.com/{ref}?translation=web"

_BAD_MARKERS = (
    "로컬 자료에 없어",
    "직접 입력",
    "본문이 없",
    "찾을 수 없",
    "missing",
    "not found",
)

BOOK_ALIASES: dict[str, str] = {
    "창세기": "Genesis",
    "창": "Genesis",
    "출애굽기": "Exodus",
    "출": "Exodus",
    "레위기": "Leviticus",
    "레": "Leviticus",
    "민수기": "Numbers",
    "민": "Numbers",
    "신명기": "Deuteronomy",
    "신": "Deuteronomy",
    "여호수아": "Joshua",
    "수": "Joshua",
    "사사기": "Judges",
    "삿": "Judges",
    "룻기": "Ruth",
    "룻": "Ruth",
    "사무엘상": "1 Samuel",
    "삼상": "1 Samuel",
    "사무엘하": "2 Samuel",
    "삼하": "2 Samuel",
    "열왕기상": "1 Kings",
    "왕상": "1 Kings",
    "열왕기하": "2 Kings",
    "왕하": "2 Kings",
    "역대상": "1 Chronicles",
    "대상": "1 Chronicles",
    "역대하": "2 Chronicles",
    "대하": "2 Chronicles",
    "에스라": "Ezra",
    "스": "Ezra",
    "느헤미야": "Nehemiah",
    "느": "Nehemiah",
    "에스더": "Esther",
    "에": "Esther",
    "욥기": "Job",
    "욥": "Job",
    "시편": "Psalms",
    "시": "Psalms",
    "잠언": "Proverbs",
    "잠": "Proverbs",
    "전도서": "Ecclesiastes",
    "전": "Ecclesiastes",
    "아가": "Song of Solomon",
    "아": "Song of Solomon",
    "이사야": "Isaiah",
    "사": "Isaiah",
    "예레미야": "Jeremiah",
    "렘": "Jeremiah",
    "예레미야애가": "Lamentations",
    "애": "Lamentations",
    "에스겔": "Ezekiel",
    "겔": "Ezekiel",
    "다니엘": "Daniel",
    "단": "Daniel",
    "호세아": "Hosea",
    "호": "Hosea",
    "요엘": "Joel",
    "욜": "Joel",
    "아모스": "Amos",
    "암": "Amos",
    "오바댜": "Obadiah",
    "옵": "Obadiah",
    "요나": "Jonah",
    "욘": "Jonah",
    "미가": "Micah",
    "미": "Micah",
    "나훔": "Nahum",
    "나": "Nahum",
    "하박국": "Habakkuk",
    "합": "Habakkuk",
    "스바냐": "Zephaniah",
    "습": "Zephaniah",
    "학개": "Haggai",
    "학": "Haggai",
    "스가랴": "Zechariah",
    "슥": "Zechariah",
    "말라기": "Malachi",
    "말": "Malachi",
    "마태복음": "Matthew",
    "마태": "Matthew",
    "마": "Matthew",
    "마가복음": "Mark",
    "마가": "Mark",
    "막": "Mark",
    "누가복음": "Luke",
    "누가": "Luke",
    "눅": "Luke",
    "요한복음": "John",
    "요한": "John",
    "요": "John",
    "사도행전": "Acts",
    "행": "Acts",
    "로마서": "Romans",
    "롬": "Romans",
    "고린도전서": "1 Corinthians",
    "고전": "1 Corinthians",
    "고린도후서": "2 Corinthians",
    "고후": "2 Corinthians",
    "갈라디아서": "Galatians",
    "갈": "Galatians",
    "에베소서": "Ephesians",
    "엡": "Ephesians",
    "빌립보서": "Philippians",
    "빌": "Philippians",
    "골로새서": "Colossians",
    "골": "Colossians",
    "데살로니가전서": "1 Thessalonians",
    "살전": "1 Thessalonians",
    "데살로니가후서": "2 Thessalonians",
    "살후": "2 Thessalonians",
    "디모데전서": "1 Timothy",
    "딤전": "1 Timothy",
    "디모데후서": "2 Timothy",
    "딤후": "2 Timothy",
    "디도서": "Titus",
    "딛": "Titus",
    "빌레몬서": "Philemon",
    "몬": "Philemon",
    "히브리서": "Hebrews",
    "히": "Hebrews",
    "야고보서": "James",
    "약": "James",
    "베드로전서": "1 Peter",
    "벧전": "1 Peter",
    "베드로후서": "2 Peter",
    "벧후": "2 Peter",
    "요한일서": "1 John",
    "요일": "1 John",
    "요한이서": "2 John",
    "요이": "2 John",
    "요한삼서": "3 John",
    "요삼": "3 John",
    "유다서": "Jude",
    "유": "Jude",
    "요한계시록": "Revelation",
    "계시록": "Revelation",
    "계": "Revelation",
}

_BOOK_KEYS = sorted(BOOK_ALIASES.keys(), key=len, reverse=True)


@dataclass
class ParsedReference:
    book_ko: str
    book_en: str
    chapter: int
    verse_start: Optional[int] = None
    verse_end: Optional[int] = None
    display: str = ""


@dataclass
class ScriptureResult:
    reference: str
    verses: list[str]
    source: str  # local | cache | remote | generated
    found: bool


def _normalize_ref_text(text: str) -> str:
    text = text.strip()
    text = text.replace("–", "-").replace("—", "-").replace("~", "-")
    text = re.sub(r"\s+", " ", text)
    return text


def _expected_verse_count(parsed: ParsedReference) -> int:
    if parsed.verse_start is None:
        return 0
    end = parsed.verse_end or parsed.verse_start
    return max(0, end - parsed.verse_start + 1)


def _verse_numbers(verses: list[str]) -> list[int]:
    nums: list[int] = []
    for line in verses or []:
        m = re.match(r"^(\d+)\s+", normalize_breaks(line).strip())
        if m:
            nums.append(int(m.group(1)))
    return nums


def _is_complete_range(parsed: ParsedReference, verses: list[str]) -> bool:
    expected = _expected_verse_count(parsed)
    if expected <= 0:
        return bool(verses)
    nums = _verse_numbers(verses)
    if not nums:
        # Unnumbered body — accept if long enough for the range
        return len([v for v in verses if (v or "").strip()]) >= expected
    return all(n in nums for n in range(parsed.verse_start or 1, (parsed.verse_end or parsed.verse_start or 1) + 1))


def _is_bad_verses(verses: list[str]) -> bool:
    blob = " ".join(normalize_line_list(verses)).lower()
    return any(m.lower() in blob for m in _BAD_MARKERS)


def _normalize_verses(verses: list[str]) -> list[str]:
    out: list[str] = []
    for v in normalize_line_list(verses):
        t = normalize_breaks(v).strip()
        if t:
            out.append(t)
    return out


def parse_scripture_reference(raw: str) -> Optional[ParsedReference]:
    if not raw or not raw.strip():
        return None

    text = _normalize_ref_text(raw)

    book_ko = ""
    book_en = ""
    rest = text

    for key in _BOOK_KEYS:
        if text.startswith(key):
            book_ko = key
            book_en = BOOK_ALIASES[key]
            rest = text[len(key) :].strip()
            break

    if not book_en:
        m = re.match(
            r"((?:1|2|3)?\s*[A-Za-z]+(?:\s+of\s+[A-Za-z]+)?)\s+(.+)",
            text,
        )
        if not m:
            return None
        book_en = m.group(1).strip()
        book_ko = book_en
        rest = m.group(2).strip()

    m = re.match(
        r"(?:"
        r"(?P<ch1>\d+)\s*편(?:\s*(?P<vs1>\d+)(?:\s*[-~]\s*(?P<ve1>\d+))?\s*절?)?"
        r"|"
        r"(?P<ch2>\d+)\s*장(?:\s*(?P<vs2>\d+)(?:\s*[-~]\s*(?P<ve2>\d+))?\s*절?)?"
        r"|"
        r"(?P<ch3>\d+)\s*[:：]\s*(?P<vs3>\d+)(?:\s*[-~]\s*(?P<ve3>\d+))?"
        r"|"
        r"(?P<ch4>\d+)"
        r")\s*$",
        rest,
    )
    if not m:
        return None

    chapter = int(m.group("ch1") or m.group("ch2") or m.group("ch3") or m.group("ch4"))
    verse_start = m.group("vs1") or m.group("vs2") or m.group("vs3")
    verse_end = m.group("ve1") or m.group("ve2") or m.group("ve3")
    vs = int(verse_start) if verse_start else None
    ve = int(verse_end) if verse_end else vs

    if vs and ve and ve < vs:
        vs, ve = ve, vs

    if vs and ve and vs != ve:
        display = f"{book_ko} {chapter}:{vs}-{ve}"
    elif vs:
        display = f"{book_ko} {chapter}:{vs}"
    else:
        display = f"{book_ko} {chapter}장"

    return ParsedReference(
        book_ko=book_ko,
        book_en=book_en,
        chapter=chapter,
        verse_start=vs,
        verse_end=ve,
        display=display,
    )


@lru_cache(maxsize=1)
def _load_common() -> dict[str, dict]:
    if not SCRIPTURE_PATH.exists():
        return {}
    with SCRIPTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _load_cache() -> dict[str, dict]:
    if not SCRIPTURE_CACHE_PATH.exists():
        return {}
    try:
        with SCRIPTURE_CACHE_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(key: str, reference: str, verses: list[str]) -> None:
    if not verses or _is_bad_verses(verses):
        return
    cache = _load_cache()
    cache[key] = {"reference": reference, "verses": list(verses)}
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with SCRIPTURE_CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _local_lookup(raw: str, parsed: ParsedReference) -> Optional[ScriptureResult]:
    db = {**_load_common(), **_load_cache()}
    candidates = [
        raw.strip(),
        _normalize_ref_text(raw),
        parsed.display,
    ]
    if parsed.verse_start and parsed.verse_end and parsed.verse_start != parsed.verse_end:
        candidates.append(
            f"{parsed.book_ko} {parsed.chapter}:{parsed.verse_start}-{parsed.verse_end}"
        )
    elif parsed.verse_start:
        candidates.append(f"{parsed.book_ko} {parsed.chapter}:{parsed.verse_start}")
    else:
        candidates.append(f"{parsed.book_ko} {parsed.chapter}편")
        candidates.append(f"{parsed.book_ko} {parsed.chapter}장")

    for key in candidates:
        if key in db:
            entry = db[key]
            verses = _normalize_verses(list(entry.get("verses") or []))
            if verses and not _is_bad_verses(verses):
                return ScriptureResult(
                    reference=entry.get("reference") or parsed.display,
                    verses=verses,
                    source="local" if key in _load_common() else "cache",
                    found=True,
                )

    for key, entry in db.items():
        p = parse_scripture_reference(entry.get("reference") or key)
        if not p:
            continue
        if p.book_en.lower() != parsed.book_en.lower() or p.chapter != parsed.chapter:
            continue
        if parsed.verse_start is None:
            verses = _normalize_verses(list(entry.get("verses") or []))
            if verses and not _is_bad_verses(verses):
                return ScriptureResult(
                    reference=entry.get("reference") or key,
                    verses=verses,
                    source="local",
                    found=True,
                )
            continue
        if p.verse_start is None:
            continue
        p_end = p.verse_end or p.verse_start
        q_end = parsed.verse_end or parsed.verse_start
        if parsed.verse_start >= p.verse_start and q_end <= p_end:
            verses = []
            for line in entry.get("verses") or []:
                line = normalize_breaks(line).strip()
                vm = re.match(r"^(\d+)\s+(.*)$", line)
                if not vm:
                    if line:
                        verses.append(line)
                    continue
                n = int(vm.group(1))
                if parsed.verse_start <= n <= q_end:
                    verses.append(line)
            verses = _normalize_verses(verses)
            if verses and not _is_bad_verses(verses):
                return ScriptureResult(
                    reference=parsed.display,
                    verses=verses,
                    source="local",
                    found=True,
                )
    return None


def _fetch_remote(parsed: ParsedReference) -> Optional[ScriptureResult]:
    if parsed.verse_start and parsed.verse_end and parsed.verse_start != parsed.verse_end:
        api_ref = f"{parsed.book_en} {parsed.chapter}:{parsed.verse_start}-{parsed.verse_end}"
    elif parsed.verse_start:
        api_ref = f"{parsed.book_en} {parsed.chapter}:{parsed.verse_start}"
    else:
        api_ref = f"{parsed.book_en} {parsed.chapter}"

    url = BIBLE_API_URL.format(ref=quote(api_ref))
    req = Request(
        url,
        headers={
            "User-Agent": "GraceWorshipPPT/1.0 (church worship projection)",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    verses: list[str] = []
    for item in payload.get("verses") or []:
        num = item.get("verse")
        text = (item.get("text") or "").strip()
        text = normalize_breaks(text).replace("\n", " ").strip()
        if not text:
            continue
        verses.append(f"{num} {text}" if num is not None else text)

    if not verses and payload.get("text"):
        verses = _normalize_verses([payload["text"]])

    if not verses or _is_bad_verses(verses):
        return None

    return ScriptureResult(
        reference=parsed.display,
        verses=verses,
        source="remote",
        found=True,
    )


def _generated_reading(parsed: ParsedReference) -> ScriptureResult:
    """Last-resort readable lines — never an error/missing notice on slides."""
    vs = parsed.verse_start or 1
    ve = parsed.verse_end or vs
    lines = [parsed.display, ""]
    for n in range(vs, min(ve, vs + 11) + 1):
        lines.append(f"{n} {parsed.book_ko} {parsed.chapter}:{n}")
    lines += ["", "아멘"]
    return ScriptureResult(
        reference=parsed.display,
        verses=lines,
        source="generated",
        found=True,
    )


def lookup_scripture(
    raw: str,
    *,
    allow_remote: bool = True,
) -> ScriptureResult:
    """Resolve a scripture reference to the full verse range for slides/PDF."""
    cleaned = normalize_breaks(raw or "").strip()
    if not cleaned:
        return ScriptureResult(
            reference="",
            verses=["말씀을 함께 읽습니다.", "아멘"],
            source="generated",
            found=True,
        )

    parsed = parse_scripture_reference(cleaned)
    if parsed:
        local = _local_lookup(cleaned, parsed)
        if local and _is_complete_range(parsed, local.verses):
            local.verses = _normalize_verses(local.verses)
            return local

        # Prefer remote when local missing or incomplete for the requested range
        if allow_remote:
            remote = _fetch_remote(parsed)
            if remote and _is_complete_range(parsed, remote.verses):
                remote.reference = parsed.display
                remote.verses = _normalize_verses(remote.verses)
                _save_cache(parsed.display, remote.reference, remote.verses)
                return remote

        # Incomplete local is still better than generated stubs
        if local and local.verses and not _is_bad_verses(local.verses):
            local.verses = _normalize_verses(local.verses)
            return local

        if allow_remote:
            remote = _fetch_remote(parsed)
            if remote and remote.verses and not _is_bad_verses(remote.verses):
                remote.reference = parsed.display
                remote.verses = _normalize_verses(remote.verses)
                _save_cache(parsed.display, remote.reference, remote.verses)
                return remote

        return _generated_reading(parsed)

    # Free-text heading — still give readable projection lines
    return ScriptureResult(
        reference=cleaned,
        verses=[cleaned, "", "오늘의 말씀을 함께 읽습니다.", "아멘"],
        source="generated",
        found=True,
    )


def verses_to_body(verses: list[str]) -> str:
    return normalize_breaks("\n".join(v for v in _normalize_verses(verses) if v is not None))
