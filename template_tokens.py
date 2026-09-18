"""Build token map from WorshipData for master-template injection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from text_normalize import normalize_breaks, normalize_line_list
from data_enrich import enrich_hymn, enrich_worship_data, hymn_label
from hymn_lookup import lookup_hymn, parse_hymn_number
from models import PREP_HYMN_COUNT, HymnEntry, WorshipData


def _scripture_ref_for_projection(ref: str) -> str:
    """Clean slide title — no translation tag, no ellipsis artifacts."""
    text = normalize_breaks(ref or "").strip()
    text = re.sub(
        r"\s*[\(\[]\s*(개역개정|새번역|개역한글|공동번역|NIV|ESV|KJV|GAE|RNKSV)\s*[\)\]]\s*$",
        "",
        text,
        flags=re.I,
    )
    text = text.rstrip(".…⋯")
    return text.strip()


def _responsive_title_for_projection(data: WorshipData) -> str:
    """Always show 교독문 number + scripture reference clearly."""
    from responsive_lookup import format_responsive_label, lookup_responsive, parse_responsive_number

    raw = normalize_breaks(data.responsive_reading_title or "").strip()
    if not raw:
        return "교독문"
    # Already well-formed
    if re.match(r"^교독문\s*\d+", raw) and "·" in raw:
        return raw
    num = parse_responsive_number(raw)
    hit = lookup_responsive(raw, allow_remote=False)
    if hit.found:
        return format_responsive_label(hit.number or num or 0, hit.title or raw)
    if num:
        return format_responsive_label(num, raw)
    return raw


@dataclass
class ResolvedHymn:
    number: int
    number_label: str  # "7장"
    title: str
    label: str  # "7장  ·  성부 성자 성령"
    lyrics: list[str]
    lyrics_text: str
    score_label: str  # 악보 슬라이드용 "찬송가 7장 · 성부 성자 성령"


def resolve_hymn_entry(h: HymnEntry, *, allow_remote: bool = True) -> ResolvedHymn:
    """Resolve a hymn slot by number to real title + lyrics for template injection."""
    enriched = enrich_hymn(h, allow_remote=allow_remote)
    raw_num = (enriched.number or h.number or "").strip()
    raw_title = (enriched.title or h.title or "").strip()
    num = parse_hymn_number(raw_num) or 0

    # Always re-query by number so {{HYMN_n}} gets catalog data, not empty stubs
    hit = None
    if num:
        hit = lookup_hymn(str(num), raw_title, allow_remote=allow_remote)

    if hit and hit.number:
        num = hit.number
        title = (raw_title or hit.title or "").strip() or hit.title
        lyrics = list(hit.lyrics or enriched.lyrics or [])
    else:
        title = raw_title
        lyrics = list(enriched.lyrics or [])

    number_label = f"{num}장" if num else (raw_num if "장" in raw_num else raw_num)
    label = hymn_label(HymnEntry(number=number_label, title=title, lyrics=lyrics)) or number_label or title
    lyrics_clean = normalize_line_list(lyrics)
    score_label = f"찬송가 {number_label}  ·  {title}".strip(" ·") if number_label or title else ""

    return ResolvedHymn(
        number=num or 0,
        number_label=number_label,
        title=normalize_breaks(title).strip(),
        label=normalize_breaks(label).strip(),
        lyrics=lyrics_clean,
        lyrics_text=normalize_breaks("\n".join(lyrics_clean)),
        score_label=normalize_breaks(score_label).strip(),
    )


def _hymn_pages(lyrics: list[str], *, lines_per_page: int = 4) -> list[str]:
    """
    One verse (절) per slide when short; long verses split to ~4 lines
    so projection text stays inside the frame.
    """
    cleaned = normalize_line_list(lyrics)
    if not cleaned:
        return [""]

    groups: list[list[str]] = []
    buf: list[str] = []
    verse_start = re.compile(r"^\s*\d+\s*[\.．、)]\s*")
    for ln in cleaned:
        if not str(ln).strip():
            if buf:
                groups.append(buf)
                buf = []
            continue
        text = str(ln).rstrip()
        if verse_start.match(text) and buf:
            groups.append(buf)
            buf = [text]
        else:
            buf.append(text)
    if buf:
        groups.append(buf)

    pages: list[str] = []
    for group in groups:
        if len(group) > lines_per_page:
            for i in range(0, len(group), lines_per_page):
                pages.append("\n".join(group[i : i + lines_per_page]))
        else:
            pages.append("\n".join(group))

    # Keep a lone trailing "아멘" with the previous verse
    amen_only = re.compile(r"^아멘\.?$|^Amen\.?$", re.I)
    if len(pages) >= 2 and amen_only.match(pages[-1].strip()):
        pages[-2] = pages[-2].rstrip() + "\n" + pages[-1].strip()
        pages.pop()
    return pages or [""]


def _text_pages(text: str, *, lines_per_page: int = 7) -> list[str]:
    """Paginate scripture/body text completely — no truncation."""
    lines = [ln for ln in normalize_breaks(text or "").splitlines()]
    # Keep blank lines as structure but don't start with blanks
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return [""]
    pages: list[str] = []
    for i in range(0, len(lines), lines_per_page):
        chunk = lines[i : i + lines_per_page]
        pages.append("\n".join(chunk))
    return pages or [""]


def _creed_pages(text: str, *, lines_per_page: int = 4) -> list[str]:
    """Apostles' Creed: exactly 4 content lines per slide."""
    raw = normalize_breaks(text or "").strip()
    if not raw:
        return [""]
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return [""]
    n = max(1, int(lines_per_page or 4))
    pages: list[str] = []
    for i in range(0, len(lines), n):
        pages.append("\n".join(lines[i : i + n]))
    return pages or [raw]


def _responsive_pages(text: str, *, max_pairs: int = 1, soft_max_chars: int = 9999) -> list[str]:
    """
    Responsive reading pages — keep source order, never drop lines.
    Prefer one 인도자 + 회중 pair per slide when they are consecutive;
    otherwise show the original line as-is (no invented role splits).
    """
    del max_pairs, soft_max_chars
    try:
        from responsive_lookup import sanitize_responsive_body

        raw = sanitize_responsive_body(text or "")
    except Exception:
        raw = normalize_breaks(text or "").strip()
    if not raw:
        return [""]

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    leader_re = re.compile(r"^인도자\s*[:：]", re.I)
    cong_re = re.compile(r"^회중\s*[:：]", re.I)

    pages: list[str] = []
    i = 0
    while i < len(lines):
        if leader_re.match(lines[i]) and i + 1 < len(lines) and cong_re.match(lines[i + 1]):
            pages.append(f"{lines[i]}\n{lines[i + 1]}")
            i += 2
            continue
        # Keep order: never show 회중 above 인도자 on the same slide
        pages.append(lines[i])
        i += 1

    return pages or [""]


def _set_paged_tokens(tokens: dict[str, str], prefix: str, pages: list[str]) -> None:
    """Write PREFIX, PREFIX_1..N and PREFIX_COUNT from a complete page list."""
    pages = [normalize_breaks(p) for p in (pages or [""])]
    if not pages:
        pages = [""]
    tokens[prefix] = pages[0]
    tokens[f"{prefix}_FULL"] = "\n".join(p for p in pages if p)
    tokens[f"{prefix}_COUNT"] = str(len(pages))
    # Always reserve slots 1..12 so master placeholders like _3 never KeyError
    for i in range(1, 13):
        tokens[f"{prefix}_{i}"] = pages[i - 1] if i <= len(pages) else ""
    # Clear any leftover higher pages from a previous longer hymn
    for i in range(13, 40):
        key = f"{prefix}_{i}"
        if key in tokens:
            del tokens[key]


def _order_block(data: WorshipData, hymns: dict[str, ResolvedHymn]) -> str:
    """One line per step — 10 numbered items (no response hymn)."""

    def _step(num: str, title: str, detail: str = "") -> str:
        detail = (detail or "").strip()
        if not detail or detail == "—":
            return f"{num}. {title}"
        return f"{num}. {title}  ·  {detail}"

    prep_detail = "  /  ".join(
        p
        for slot in (f"PREP_{i}" for i in range(1, PREP_HYMN_COUNT + 1))
        for p in (hymns[slot].label,)
        if (p or "").strip() and p != "—"
    )
    return "\n".join(
        [
            _step("1", "예배 준비의 시간", prep_detail),
            _step("2", "찬양과 기도", hymns["1"].label),
            _step("3", "사도신경"),
            _step("4", "교독문", data.responsive_reading_title),
            _step("5", "찬송가", hymns["2"].label),
            _step("6", "예배의 기도", data.worship_prayer_leader),
            _step("7", "성가대 찬양", hymns["CHOIR"].label),
            _step("8", "오늘의 말씀", data.scripture_reference),
            _step("9", "생명의 말씀", data.sermon_title),
            _step("10", "감사와 봉헌", hymns["3"].label),
            _step("11", "축도", data.benediction),
        ]
    )


def _add_hymn_tokens(tokens: dict[str, str], slot: str, h: ResolvedHymn) -> None:
    """Add HYMN_{n}* tokens — full lyrics paged in order to match the bulletin."""
    pages = _hymn_pages(h.lyrics, lines_per_page=4)
    tokens[f"HYMN_{slot}"] = h.label
    tokens[f"HYMN_{slot}_NUM"] = h.number_label
    tokens[f"HYMN_{slot}_NUMBER"] = h.number_label
    tokens[f"HYMN_{slot}_TITLE"] = h.title
    tokens[f"HYMN_{slot}_SCORE"] = h.score_label
    tokens[f"HYMN_{slot}_SCORE_LABEL"] = h.score_label
    tokens[f"HYMN_{slot}_LYRICS_FULL"] = h.lyrics_text
    _set_paged_tokens(tokens, f"HYMN_{slot}_LYRICS", pages)
    # Keep FULL as the complete lyric source (not only joined page chunks)
    tokens[f"HYMN_{slot}_LYRICS_FULL"] = h.lyrics_text


def build_token_map(data: WorshipData, *, allow_remote: bool = True) -> dict[str, str]:
    """Return TOKEN → value mapping for {{TOKEN}} injection (keys without braces)."""
    data = enrich_worship_data(data, allow_remote=allow_remote, force_hymn_lyrics=True)

    hymns = {
        **{
            f"PREP_{i}": resolve_hymn_entry(h, allow_remote=allow_remote)
            for i, h in enumerate(data.iter_prep_hymns(), start=1)
        },
        "1": resolve_hymn_entry(data.praise_hymn, allow_remote=allow_remote),
        "2": resolve_hymn_entry(data.hymn, allow_remote=allow_remote),
        "CHOIR": resolve_hymn_entry(data.choir_anthem, allow_remote=allow_remote),
        # Slot 3 = offering (response hymn removed from order)
        "3": resolve_hymn_entry(data.offering_hymn, allow_remote=allow_remote),
    }

    # Write resolved data back so PDF / preview stay in sync
    def _to_entry(r: ResolvedHymn) -> HymnEntry:
        return HymnEntry(
            number=r.number_label,
            title=r.title,
            lyrics=list(r.lyrics),
            include_lyrics=True,
        )

    for i in range(1, PREP_HYMN_COUNT + 1):
        setattr(data, f"prep_hymn_{i}", _to_entry(hymns[f"PREP_{i}"]))
    data.praise_hymn = _to_entry(hymns["1"])
    data.hymn = _to_entry(hymns["2"])
    data.choir_anthem = _to_entry(hymns["CHOIR"])
    data.offering_hymn = _to_entry(hymns["3"])
    # Keep response_hymn cleared so it never reappears in outputs
    data.response_hymn = HymnEntry()

    try:
        from defaults import CHURCH_NAME_KO, CHURCH_NAME_KO_ALIASES
    except Exception:
        CHURCH_NAME_KO = "플러톤 빌라 교회"
        CHURCH_NAME_KO_ALIASES = ()

    church_ko = (data.church_name_ko or "").strip()
    if (not church_ko) or (church_ko in CHURCH_NAME_KO_ALIASES) or ("플로튼" in church_ko) or ("장로교회" in church_ko.replace(" ", "")):
        church_ko = CHURCH_NAME_KO
    data.church_name_ko = church_ko

    tokens: dict[str, str] = {
        "CHURCH_EN": data.church_name_en or "",
        "CHURCH_KO": church_ko,

        "SERVICE_TITLE": data.service_title or "주일 예배",
        "DATE": data.date or "",
        "SERVICE_TIME": data.service_time or "",
        "PREACHER": data.preacher or "",
        "WORSHIP_LEADER": (
            f"인도자 {(data.worship_leader or '').strip()}"
            if (data.worship_leader or "").strip()
            else ""
        ),
        "META_LINE": "  ·  ".join(
            x for x in [data.date, data.service_time, f"설교 {data.preacher}" if data.preacher else ""] if x
        ),
        "ORDER_TEXT": _order_block(data, hymns),
        "APOSTLES_CREED_HEADING": "사도신경",
        "APOSTLES_CREED": (data.apostles_creed or "").strip(),
        "RESPONSIVE_TITLE": _responsive_title_for_projection(data),
        "RESPONSIVE_BODY": (data.responsive_reading or "").strip(),
        "RESPONSIVE_READING": (data.responsive_reading or "").strip(),
        # Master-template aliases
        "RESPONSIVE": (data.responsive_reading or "").strip(),
        "PRAYER_LEADER": data.worship_prayer_leader or "",
        "PRAYER_TEXT": (data.worship_prayer or "").strip(),
        "SCRIPTURE_REF": _scripture_ref_for_projection(data.scripture_reference or ""),
        "SCRIPTURE_REFERENCE": _scripture_ref_for_projection(data.scripture_reference or ""),
        "SCRIPTURE_TEXT": (data.scripture_text or "").strip(),
        "BIBLE_TEXT": (data.scripture_text or "").strip(),
        "BIBLE": (data.scripture_text or "").strip(),
        # Hero title only — never fall back to section label "생명의 말씀"
        "SERMON_TITLE": (data.sermon_title or "").strip(),
        "SERMON_SUBTITLE": (data.sermon_subtitle or "").strip(),
        "BENEDICTION": (data.benediction or "").strip() or "축도",
        "CLOSING_NOTE": (data.closing_note or "").strip(),
        "ANNOUNCEMENTS": (data.announcements or "").strip() or "이번 주 소식을 함께 나눕니다.",
    }
    # Combined body for 축도 slide (never leave the body frame empty)
    ben_bits = [tokens["BENEDICTION"]]
    if tokens["CLOSING_NOTE"]:
        ben_bits.append(tokens["CLOSING_NOTE"])
    tokens["BENEDICTION_BODY"] = "\n\n".join(ben_bits)

    bible_pages = _text_pages(tokens.get("BIBLE_TEXT", "") or tokens.get("SCRIPTURE_TEXT", ""), lines_per_page=4)
    _set_paged_tokens(tokens, "BIBLE_TEXT", bible_pages)
    tokens["SCRIPTURE_TEXT"] = tokens.get("BIBLE_TEXT_1", "") or tokens.get("BIBLE_TEXT", "")
    tokens["BIBLE"] = tokens.get("BIBLE_TEXT_FULL", "") or tokens.get("BIBLE_TEXT", "")

    creed_raw = normalize_breaks((data.apostles_creed or "").strip())
    # Dense lines only — no blank paragraph gaps on slides
    creed_src = "\n".join(ln.strip() for ln in creed_raw.splitlines() if ln.strip())
    creed_pages = _creed_pages(creed_src, lines_per_page=4)
    _set_paged_tokens(tokens, "APOSTLES_CREED", creed_pages)
    tokens["APOSTLES_CREED_FULL"] = creed_src

    resp_full = normalize_breaks((data.responsive_reading or "").strip())
    resp_pages = _responsive_pages(resp_full, max_pairs=1)
    _set_paged_tokens(tokens, "RESPONSIVE", resp_pages)
    tokens["RESPONSIVE_FULL"] = resp_full
    tokens["RESPONSIVE_BODY"] = resp_full
    tokens["RESPONSIVE_READING"] = resp_full

    for slot, h in hymns.items():
        _add_hymn_tokens(tokens, slot, h)

    # Legacy named slots (same data as HYMN_1..3)
    tokens.update(
        {
            "PRAISE_HYMN": hymns["1"].label,
            "PRAISE_NUM": hymns["1"].number_label,
            "PRAISE_TITLE": hymns["1"].title,
            "PRAISE_LYRICS": tokens.get("HYMN_1_LYRICS_1", ""),
            "PRAISE_LYRICS_1": tokens.get("HYMN_1_LYRICS_1", ""),
            "PRAISE_LYRICS_2": tokens.get("HYMN_1_LYRICS_2", ""),
            "PRAISE_SCORE": hymns["1"].score_label,
            "HYMN": hymns["2"].label,
            "HYMN_NUM": hymns["2"].number_label,
            "HYMN_TITLE": hymns["2"].title,
            "HYMN_LYRICS": tokens.get("HYMN_2_LYRICS_1", ""),
            "HYMN_LYRICS_1": tokens.get("HYMN_2_LYRICS_1", ""),
            "HYMN_LYRICS_2": tokens.get("HYMN_2_LYRICS_2", ""),
            "HYMN_SCORE": hymns["2"].score_label,
            "CHOIR_ANTHEM": hymns["CHOIR"].label,
            "CHOIR_ANTHEM_TITLE": hymns["CHOIR"].title,
            "CHOIR_ANTHEM_LYRICS": tokens.get("HYMN_CHOIR_LYRICS_1", "") or hymns["CHOIR"].lyrics_text,
            "OFFERING_HYMN": hymns["3"].label,
            "OFFERING_LYRICS": tokens.get("HYMN_3_LYRICS_1", ""),
            "OFFERING_LYRICS_1": tokens.get("HYMN_3_LYRICS_1", ""),
            # Cleared legacy response-hymn aliases
            "RESPONSE_HYMN": "",
            "RESPONSE_LYRICS": "",
            "RESPONSE_LYRICS_1": "",
            "HYMN_4": "",
            "HYMN_4_LYRICS": "",
            "HYMN_4_LYRICS_1": "",
            "HYMN_4_LYRICS_FULL": "",
        }
    )
    return {k: normalize_breaks(v if v is not None else "") for k, v in tokens.items()}


def apply_tokens(text: str, tokens: dict[str, str]) -> str:
    """Replace {{TOKEN}} placeholders; unknown tokens left intact."""
    if not text or "{{" not in text:
        return normalize_breaks(text or "")
    out = text
    for key in sorted(tokens.keys(), key=len, reverse=True):
        out = out.replace("{{" + key + "}}", tokens[key])
    return normalize_breaks(out)


def list_placeholders_in_text(text: str) -> list[str]:
    return sorted(set(re.findall(r"\{\{([A-Za-z0-9_]+)\}\}", text or "")))


def hymn_number_for_slot(tokens: dict[str, str], slot: str) -> int:
    """Parse resolved hymn number for score-image lookup (1–4)."""
    return parse_hymn_number(tokens.get(f"HYMN_{slot}_NUM", "") or "") or 0
