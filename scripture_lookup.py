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
from urllib.request import Request, urlopen

from text_normalize import normalize_breaks, normalize_line_list

DATA_DIR = Path(__file__).resolve().parent / "data"
SCRIPTURE_PATH = DATA_DIR / "scripture_common.json"
SCRIPTURE_CACHE_PATH = DATA_DIR / "scripture_cache.json"

# Use 개역개정 (GAE). Do not use 새번역 / English WEB.
TRANSLATION_LABEL = "개역개정"
# BSK reader expects book slug + chap (numeric bookcode is ignored / defaults to Genesis)
BSKOREA_URL = (
    "https://www.bskorea.or.kr/bible/korbibReadpage.php"
    "?version=GAE&book={book}&chap={chapter}"
)

# bskorea book slugs (Protestant canon)
_BOOK_SLUGS: dict[str, str] = {
    "Genesis": "gen",
    "Exodus": "exo",
    "Leviticus": "lev",
    "Numbers": "num",
    "Deuteronomy": "deu",
    "Joshua": "jos",
    "Judges": "jdg",
    "Ruth": "rut",
    "1 Samuel": "1sa",
    "2 Samuel": "2sa",
    "1 Kings": "1ki",
    "2 Kings": "2ki",
    "1 Chronicles": "1ch",
    "2 Chronicles": "2ch",
    "Ezra": "ezr",
    "Nehemiah": "neh",
    "Esther": "est",
    "Job": "job",
    "Psalms": "psa",
    "Proverbs": "pro",
    "Ecclesiastes": "ecc",
    "Song of Solomon": "sng",
    "Isaiah": "isa",
    "Jeremiah": "jer",
    "Lamentations": "lam",
    "Ezekiel": "ezk",
    "Daniel": "dan",
    "Hosea": "hos",
    "Joel": "jol",
    "Amos": "amo",
    "Obadiah": "oba",
    "Jonah": "jon",
    "Micah": "mic",
    "Nahum": "nam",
    "Habakkuk": "hab",
    "Zephaniah": "zep",
    "Haggai": "hag",
    "Zechariah": "zec",
    "Malachi": "mal",
    "Matthew": "mat",
    "Mark": "mrk",
    "Luke": "luk",
    "John": "jhn",
    "Acts": "act",
    "Romans": "rom",
    "1 Corinthians": "1co",
    "2 Corinthians": "2co",
    "Galatians": "gal",
    "Ephesians": "eph",
    "Philippians": "php",
    "Colossians": "col",
    "1 Thessalonians": "1th",
    "2 Thessalonians": "2th",
    "1 Timothy": "1ti",
    "2 Timothy": "2ti",
    "Titus": "tit",
    "Philemon": "phm",
    "Hebrews": "heb",
    "James": "jas",
    "1 Peter": "1pe",
    "2 Peter": "2pe",
    "1 John": "1jn",
    "2 John": "2jn",
    "3 John": "3jn",
    "Jude": "jud",
    "Revelation": "rev",
}

# Opening phrases unique enough to catch cross-book cache/scrape mixups
_BOOK_FINGERPRINTS: dict[str, tuple[str, ...]] = {
    "Genesis": ("태초에 하나님이 천지를",),
    "John": ("태초에 말씀이 계시니라", "태초에 말씀이"),
    "Psalms": ("복 있는 사람은", "여호와는 나의 목자시니"),
}

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
    message: str = ""


def _normalize_ref_text(text: str) -> str:
    text = text.strip()
    text = text.replace("–", "-").replace("—", "-").replace("~", "-")
    # Strip translation labels so "히브리서 4:1-11 (개역개정)" still parses
    text = re.sub(
        r"\s*[\(\[]\s*(개역개정|새번역|개역한글|공동번역|NIV|ESV|KJV|GAE|RNKSV)\s*[\)\]]\s*$",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_verse_text(text: str) -> str:
    """Remove BSK scrape noise (footnote chips like '5)') — keep biblical (셀라)."""
    t = normalize_breaks(text or "").strip()
    if not t:
        return ""
    # Footnote markers inserted mid-verse: "세상을 5) 심판하려"
    t = re.sub(r"\s*\d{1,2}\)\s*", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([,.;:?!…])", r"\1", t)
    return t.strip()


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


def _is_stub_verse_line(line: str) -> bool:
    """Detect fake lines like '16 요 3:16' (ref repeated, no real text)."""
    s = normalize_breaks(line or "").strip()
    if not s:
        return False
    if re.match(r"^\d+\s+\S+\s+\d+:\d+\s*$", s):
        return True
    if re.match(r"^\d+\s+[가-힣A-Za-z]+\s+\d+\s*:\s*\d+\s*$", s):
        return True
    return False


def _is_bad_verses(verses: list[str]) -> bool:
    lines = normalize_line_list(verses)
    blob = " ".join(lines).lower()
    if any(m.lower() in blob for m in _BAD_MARKERS):
        return True
    content = [ln for ln in lines if ln.strip() and ln.strip() not in {"아멘", "Amen"}]
    if content and sum(1 for ln in content if _is_stub_verse_line(ln)) >= max(1, len(content) // 2):
        return True
    return False


def _normalize_verses(verses: list[str]) -> list[str]:
    out: list[str] = []
    for v in normalize_line_list(verses):
        t = clean_verse_text(v)
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


def _looks_like_rnksv(verses: list[str] | str) -> bool:
    """Detect 새번역 phrasing — used only to avoid mixing it in when we want 개역개정."""
    if isinstance(verses, str):
        blob = verses
    else:
        blob = " ".join(verses or [])
    blob = normalize_breaks(blob)
    hits = 0
    for marker in (
        "외아들",
        "사랑하셔서",
        "주님은 나의 목자시니",
        "부족함이 없습니다",
        "하려는 것이다",
        "구원하시려는 것이다",
    ):
        if marker in blob:
            hits += 1
    return hits >= 2


@lru_cache(maxsize=1)
def _load_common() -> dict[str, dict]:
    """Load 개역개정 local stubs (scripture_common.json)."""
    if not SCRIPTURE_PATH.exists():
        return {}
    try:
        with SCRIPTURE_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: v
        for k, v in data.items()
        if not str(k).startswith("_") and isinstance(v, dict)
    }


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


def _verse_map_for_chapter(db: dict, parsed: ParsedReference) -> dict[int, str]:
    """Merge all local/cache lines for this book+chapter into {verse_num: line}."""
    by_num: dict[int, str] = {}
    for key, entry in db.items():
        p = parse_scripture_reference(entry.get("reference") or key)
        if not p:
            continue
        if p.book_en.lower() != parsed.book_en.lower() or p.chapter != parsed.chapter:
            continue
        for line in entry.get("verses") or []:
            line = normalize_breaks(str(line)).strip()
            if not line or _is_stub_verse_line(line):
                continue
            vm = re.match(r"^(\d+)\s+(.*)$", line)
            if not vm:
                continue
            n = int(vm.group(1))
            body = vm.group(2).strip()
            # Prefer real prose over short stubs
            prev = by_num.get(n, "")
            if n not in by_num or len(body) > len(re.sub(r"^\d+\s+", "", prev)):
                by_num[n] = line
    return by_num


def _local_lookup(raw: str, parsed: ParsedReference) -> Optional[ScriptureResult]:
    common = _load_common()
    # Prefer 개역개정 cache — skip leftover 새번역 / cross-book polluted entries
    cache_raw = _load_cache()
    cache = {}
    for k, v in cache_raw.items():
        if not isinstance(v, dict):
            continue
        verses = list(v.get("verses") or [])
        if _looks_like_rnksv(verses):
            continue
        # Drop cache rows whose stored text belongs to a different book
        p_key = parse_scripture_reference(v.get("reference") or k)
        if p_key and not _verses_match_book(p_key, verses):
            continue
        if not _verses_match_book(parsed, verses) and (
            (v.get("reference") or k).startswith(parsed.book_ko)
            or parsed.display in (v.get("reference") or k)
        ):
            continue
        cache[k] = v
    db = {**common, **cache}
    candidates = [
        raw.strip(),
        _normalize_ref_text(raw),
        parsed.display,
    ]
    if parsed.verse_start and parsed.verse_end and parsed.verse_start != parsed.verse_end:
        candidates.append(
            f"{parsed.book_ko} {parsed.chapter}:{parsed.verse_start}-{parsed.verse_end}"
        )
        # Full book name form (요 → 요한복음)
        if parsed.book_ko != "요한복음" and parsed.book_en.lower() == "john":
            candidates.append(
                f"요한복음 {parsed.chapter}:{parsed.verse_start}-{parsed.verse_end}"
            )
    elif parsed.verse_start:
        candidates.append(f"{parsed.book_ko} {parsed.chapter}:{parsed.verse_start}")
        if parsed.book_en.lower() == "john":
            candidates.append(f"요한복음 {parsed.chapter}:{parsed.verse_start}")
    else:
        candidates.append(f"{parsed.book_ko} {parsed.chapter}편")
        candidates.append(f"{parsed.book_ko} {parsed.chapter}장")

    for key in candidates:
        if key in db:
            entry = db[key]
            verses = _normalize_verses(list(entry.get("verses") or []))
            if verses and not _is_bad_verses(verses) and not _looks_like_rnksv(verses):
                ref = entry.get("reference") or parsed.display
                if TRANSLATION_LABEL not in ref:
                    ref = f"{ref} ({TRANSLATION_LABEL})"
                return ScriptureResult(
                    reference=ref,
                    verses=verses,
                    source="local" if key in common else "cache",
                    found=True,
                )

    # Assemble a contiguous range by merging every local entry for this chapter
    if parsed.verse_start is not None:
        by_num = _verse_map_for_chapter(db, parsed)
        q_end = parsed.verse_end or parsed.verse_start
        verses = [by_num[n] for n in range(parsed.verse_start, q_end + 1) if n in by_num]
        verses = _normalize_verses(verses)
        if verses and not _is_bad_verses(verses) and not _looks_like_rnksv(verses):
            return ScriptureResult(
                reference=f"{parsed.display} ({TRANSLATION_LABEL})",
                verses=verses,
                source="local",
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
                    if line and not _is_stub_verse_line(line):
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


def _verses_match_book(parsed: ParsedReference, verses: list[str]) -> bool:
    """Reject obvious cross-book mixups (e.g. Genesis text cached under Psalms)."""
    blob = " ".join(verses or [])
    if not blob.strip():
        return False
    if "태초에 하나님이 천지를" in blob and parsed.book_en.lower() != "genesis":
        return False
    if "태초에 말씀이" in blob and parsed.book_en.lower() != "john":
        return False
    return True


def _fetch_remote(parsed: ParsedReference) -> Optional[ScriptureResult]:
    """Fetch 개역개정 (GAE) from Korean Bible Society reader — never English WEB."""
    book = _BOOK_SLUGS.get(parsed.book_en)
    if not book:
        return None
    url = BSKOREA_URL.format(book=book, chapter=parsed.chapter)
    req = Request(
        url,
        headers={
            "User-Agent": "GraceWorshipPPT/1.0 (church worship projection)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError, TimeoutError, OSError):
        return None

    html_probe = re.sub(r"<[^>]+>", " ", html)
    # Wrong default page guard (old bookcode URL always returned Genesis 1)
    if parsed.book_en.lower() != "genesis" and "창세기 제 1 장" in html_probe:
        if "시편" not in html_probe and parsed.book_ko not in html_probe:
            return None

    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>|</div>|</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
        .replace("\xa0", " ")
    )
    text = normalize_breaks(text)
    text = re.sub(r"[ \t]+", " ", text)

    found: dict[int, str] = {}
    for m in re.finditer(
        r"(?:(?<=\n)|(?<=\s)|^)(\d{1,3})\s+([가-힣A-Za-z][^\n]{4,})",
        text,
    ):
        n = int(m.group(1))
        body = clean_verse_text(m.group(2).replace("\n", " "))
        body = re.split(r"\s+\d{1,3}\s+[가-힣]", body, maxsplit=1)[0].strip()
        body = clean_verse_text(body)
        if n < 1 or n > 200:
            continue
        if any(
            x in body
            for x in ("이전", "다음", "성경", "검색", "대한성서공회", "copyright", "개역개정")
        ):
            continue
        if len(body) < 6:
            continue
        if n not in found or len(body) > len(found[n]):
            found[n] = body

    if not found:
        return None

    vs = parsed.verse_start or min(found)
    ve = parsed.verse_end or parsed.verse_start or max(found)
    verses: list[str] = []
    for n in range(vs, ve + 1):
        if n in found:
            verses.append(f"{n} {found[n]}")

    if not verses or _is_bad_verses(verses) or _looks_like_rnksv(verses):
        return None
    if not _verses_match_book(parsed, verses):
        return None

    return ScriptureResult(
        reference=f"{parsed.display} ({TRANSLATION_LABEL})",
        verses=verses,
        source="remote",
        found=True,
    )


def _generated_reading(parsed: ParsedReference) -> ScriptureResult:
    """Last resort when local/remote fail — do NOT invent fake verse stubs."""
    return ScriptureResult(
        reference=parsed.display,
        verses=[],
        source="generated",
        found=False,
        message="개역개정 본문을 찾지 못했습니다. 구절을 확인하거나 본문을 직접 붙여 넣어 주세요.",
    )


def lookup_scripture(
    raw: str,
    *,
    allow_remote: bool = True,
) -> ScriptureResult:
    """Resolve a scripture reference to the full verse range (개역개정)."""
    cleaned = normalize_breaks(raw or "").strip()
    if not cleaned:
        return ScriptureResult(
            reference="",
            verses=[],
            source="generated",
            found=False,
            message="성경 구절을 입력해 주세요.",
        )

    parsed = parse_scripture_reference(cleaned)
    if parsed:
        local = _local_lookup(cleaned, parsed)
        if local and local.verses and _looks_like_rnksv(local.verses):
            local = None

        # Prefer complete 개역개정 local, else remote 개역개정
        if (
            local
            and _is_complete_range(parsed, local.verses)
            and _verses_match_book(parsed, local.verses)
        ):
            local.verses = _normalize_verses(local.verses)
            if TRANSLATION_LABEL not in (local.reference or ""):
                local.reference = f"{parsed.display} ({TRANSLATION_LABEL})"
            return local

        if allow_remote:
            remote = _fetch_remote(parsed)
            if (
                remote
                and remote.verses
                and not _is_bad_verses(remote.verses)
                and not _looks_like_rnksv(remote.verses)
                and _verses_match_book(parsed, remote.verses)
            ):
                remote.verses = _normalize_verses(remote.verses)
                remote.reference = f"{parsed.display} ({TRANSLATION_LABEL})"
                _save_cache(parsed.display, remote.reference, remote.verses)
                return remote

        if (
            local
            and local.verses
            and not _is_bad_verses(local.verses)
            and _verses_match_book(parsed, local.verses)
        ):
            local.verses = _normalize_verses(local.verses)
            if TRANSLATION_LABEL not in (local.reference or ""):
                local.reference = f"{parsed.display} ({TRANSLATION_LABEL})"
            return local

        return _generated_reading(parsed)

    # Unparseable reference — do NOT invent stub slides (they wipe real text in the UI)
    return ScriptureResult(
        reference=cleaned,
        verses=[],
        source="generated",
        found=False,
        message="성경 구절을 인식하지 못했습니다. 예: 요한복음 3:16-17",
    )


def verses_to_body(verses: list[str]) -> str:
    return normalize_breaks("\n".join(v for v in _normalize_verses(verses) if v is not None))
