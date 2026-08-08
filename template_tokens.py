"""Build token map from WorshipData for master-template injection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from text_normalize import normalize_breaks, normalize_line_list
from data_enrich import enrich_hymn, enrich_worship_data, hymn_label
from hymn_lookup import lookup_hymn, parse_hymn_number
from models import HymnEntry, WorshipData


@dataclass
class ResolvedHymn:
    number: int
    number_label: str  # "7장"
    title: str
    label: str  # "7장  ·  성부 성자 성령"
    lyrics: list[str]
    lyrics_text: str
    score_label: str  # 악보 슬라이드용 "새찬송가 7장 · 성부 성자 성령"


def resolve_hymn_entry(h: HymnEntry, *, allow_remote: bool = True) -> ResolvedHymn:
    """Resolve a hymn slot by number to real title + lyrics for template injection."""
    enriched = enrich_hymn(h, allow_remote=allow_remote)
    raw_num = (enriched.number or h.number or "").strip()
    raw_title = (enriched.title or h.title or "").strip()
    num = parse_hymn_number(raw_num) or parse_hymn_number(raw_title) or 0

    # Always re-query by number so {{HYMN_n}} gets catalog data, not empty stubs
    hit = None
    if num:
        hit = lookup_hymn(str(num), raw_title, allow_remote=allow_remote)
    elif raw_title:
        hit = lookup_hymn(raw_title, raw_title, allow_remote=allow_remote)

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
    score_label = f"새찬송가 {number_label}  ·  {title}".strip(" ·") if number_label or title else ""

    return ResolvedHymn(
        number=num or 0,
        number_label=number_label,
        title=normalize_breaks(title).strip(),
        label=normalize_breaks(label).strip(),
        lyrics=lyrics_clean,
        lyrics_text=normalize_breaks("\n".join(lyrics_clean)),
        score_label=normalize_breaks(score_label).strip(),
    )


def _hymn_pages(lyrics: list[str], *, lines_per_page: int = 8) -> list[str]:
    if not lyrics:
        return [""]
    pages: list[str] = []
    for i in range(0, len(lyrics), lines_per_page):
        pages.append("\n".join(lyrics[i : i + lines_per_page]))
    return pages or [""]


def _order_block(data: WorshipData, hymns: dict[str, ResolvedHymn]) -> str:
    return "\n".join(
        [
            f"1. 찬양과 기도  ·  {hymns['1'].label or '—'}",
            "2. 사도신경",
            f"3. 교독문  ·  {data.responsive_reading_title or '—'}",
            f"4. 찬송가  ·  {hymns['2'].label or '—'}",
            f"5. 예배의 기도  ·  {data.worship_prayer_leader or '—'}",
            f"6. 오늘의 말씀  ·  {data.scripture_reference or '—'}",
            f"7. 찬양  ·  {hymns['3'].label or '—'}",
            f"8. 생명의 말씀  ·  {data.sermon_title or '—'}",
            f"9. 감사와 봉헌  ·  {hymns['4'].label or '—'}",
            f"10. 축도  ·  {data.benediction or '—'}",
        ]
    )


def _add_hymn_tokens(tokens: dict[str, str], slot: str, h: ResolvedHymn) -> None:
    """Add HYMN_{n}* and legacy aliases for one hymn slot."""
    pages = _hymn_pages(h.lyrics)
    tokens[f"HYMN_{slot}"] = h.label
    tokens[f"HYMN_{slot}_NUM"] = h.number_label
    tokens[f"HYMN_{slot}_NUMBER"] = h.number_label
    tokens[f"HYMN_{slot}_TITLE"] = h.title
    tokens[f"HYMN_{slot}_LYRICS"] = h.lyrics_text
    tokens[f"HYMN_{slot}_LYRICS_1"] = pages[0] if pages else ""
    tokens[f"HYMN_{slot}_LYRICS_2"] = pages[1] if len(pages) > 1 else ""
    tokens[f"HYMN_{slot}_SCORE"] = h.score_label
    tokens[f"HYMN_{slot}_SCORE_LABEL"] = h.score_label


def build_token_map(data: WorshipData, *, allow_remote: bool = True) -> dict[str, str]:
    """Return TOKEN → value mapping for {{TOKEN}} injection (keys without braces)."""
    data = enrich_worship_data(data, allow_remote=allow_remote, force_hymn_lyrics=True)

    hymns = {
        "1": resolve_hymn_entry(data.praise_hymn, allow_remote=allow_remote),
        "2": resolve_hymn_entry(data.hymn, allow_remote=allow_remote),
        "3": resolve_hymn_entry(data.response_hymn, allow_remote=allow_remote),
        "4": resolve_hymn_entry(data.offering_hymn, allow_remote=allow_remote),
    }

    # Write resolved data back so PDF / preview stay in sync
    def _to_entry(r: ResolvedHymn) -> HymnEntry:
        return HymnEntry(
            number=r.number_label,
            title=r.title,
            lyrics=list(r.lyrics),
            include_lyrics=True,
        )

    data.praise_hymn = _to_entry(hymns["1"])
    data.hymn = _to_entry(hymns["2"])
    data.response_hymn = _to_entry(hymns["3"])
    data.offering_hymn = _to_entry(hymns["4"])

    tokens: dict[str, str] = {
        "CHURCH_EN": data.church_name_en or "",
        "CHURCH_KO": data.church_name_ko or "",
        "SERVICE_TITLE": data.service_title or "주일 예배",
        "DATE": data.date or "",
        "SERVICE_TIME": data.service_time or "",
        "PREACHER": data.preacher or "",
        "META_LINE": "  ·  ".join(
            x for x in [data.date, data.service_time, f"설교 {data.preacher}" if data.preacher else ""] if x
        ),
        "ORDER_TEXT": _order_block(data, hymns),
        "APOSTLES_CREED": (data.apostles_creed or "").strip(),
        "RESPONSIVE_TITLE": data.responsive_reading_title or "교독문",
        "RESPONSIVE_BODY": (data.responsive_reading or "").strip(),
        "RESPONSIVE_READING": (data.responsive_reading or "").strip(),
        # Master-template aliases
        "RESPONSIVE": (data.responsive_reading or "").strip(),
        "PRAYER_LEADER": data.worship_prayer_leader or "",
        "PRAYER_TEXT": (data.worship_prayer or "").strip(),
        "SCRIPTURE_REF": data.scripture_reference or "",
        "SCRIPTURE_REFERENCE": data.scripture_reference or "",
        "SCRIPTURE_TEXT": (data.scripture_text or "").strip(),
        "BIBLE_TEXT": (data.scripture_text or "").strip(),
        "BIBLE": (data.scripture_text or "").strip(),
        "SERMON_TITLE": data.sermon_title or "",
        "SERMON_SUBTITLE": data.sermon_subtitle or "",
        "BENEDICTION": data.benediction or "",
        "CLOSING_NOTE": data.closing_note or "",
        "ANNOUNCEMENTS": (data.announcements or "").strip(),
    }

    for slot, h in hymns.items():
        _add_hymn_tokens(tokens, slot, h)

    # Legacy named slots (same data as HYMN_1..4)
    tokens.update(
        {
            "PRAISE_HYMN": hymns["1"].label,
            "PRAISE_NUM": hymns["1"].number_label,
            "PRAISE_TITLE": hymns["1"].title,
            "PRAISE_LYRICS": hymns["1"].lyrics_text,
            "PRAISE_LYRICS_1": tokens["HYMN_1_LYRICS_1"],
            "PRAISE_LYRICS_2": tokens["HYMN_1_LYRICS_2"],
            "PRAISE_SCORE": hymns["1"].score_label,
            "HYMN": hymns["2"].label,
            "HYMN_NUM": hymns["2"].number_label,
            "HYMN_TITLE": hymns["2"].title,
            "HYMN_LYRICS": hymns["2"].lyrics_text,
            "HYMN_LYRICS_1": tokens["HYMN_2_LYRICS_1"],
            "HYMN_LYRICS_2": tokens["HYMN_2_LYRICS_2"],
            "HYMN_SCORE": hymns["2"].score_label,
            "RESPONSE_HYMN": hymns["3"].label,
            "RESPONSE_LYRICS": hymns["3"].lyrics_text,
            "RESPONSE_LYRICS_1": tokens["HYMN_3_LYRICS_1"],
            "OFFERING_HYMN": hymns["4"].label,
            "OFFERING_LYRICS": hymns["4"].lyrics_text,
            "OFFERING_LYRICS_1": tokens["HYMN_4_LYRICS_1"],
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
