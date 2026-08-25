"""Enrich WorshipData — resolve hymn lyrics and scripture for all order slots."""

from __future__ import annotations

import re

from hymn_lookup import _lyrics_richness, is_usable_lyrics, lookup_hymn
from models import HymnEntry, WorshipData
from responsive_lookup import format_responsive_label, lookup_responsive, parse_responsive_number
from scripture_lookup import _is_bad_verses, _looks_like_rnksv, lookup_scripture, verses_to_body
from text_normalize import normalize_breaks, normalize_line_list


def enrich_hymn(h: HymnEntry, *, allow_remote: bool = True) -> HymnEntry:
    number = normalize_breaks(h.number or "").strip()
    title = normalize_breaks(h.title or "").strip()
    lyrics = normalize_line_list(h.lyrics or [])
    if not (number or title):
        return h

    # Always re-query so short local stubs are replaced by full lyrics.
    # When a number is present, take the catalog title (do not keep a previous hymn's title).
    has_num = bool(re.search(r"\d", number or ""))
    result = lookup_hymn(
        number or title,
        "" if has_num else title,
        allow_remote=allow_remote,
    )
    if result:
        if result.number:
            number = f"{result.number}장"
        title = (result.title or title) if has_num else (title or result.title)
        new_lyrics = normalize_line_list(result.lyrics or [])
        if new_lyrics and is_usable_lyrics(new_lyrics) and (
            not is_usable_lyrics(lyrics)
            or _lyrics_richness(new_lyrics) >= _lyrics_richness(lyrics)
        ):
            lyrics = new_lyrics

    return HymnEntry(
        number=number,
        title=title,
        lyrics=lyrics,
        include_lyrics=True if (number or title) else h.include_lyrics,
    )


def _body_verse_count(body: str) -> int:
    body = normalize_breaks(body or "")
    nums = re.findall(r"(?m)^\s*(\d+)\s+", body)
    if nums:
        return len({int(n) for n in nums})
    return len([ln for ln in body.splitlines() if ln.strip()])


def enrich_worship_data(
    data: WorshipData,
    *,
    allow_remote: bool = True,
    force_hymn_lyrics: bool = True,
) -> WorshipData:
    data.prep_hymn_1 = enrich_hymn(data.prep_hymn_1, allow_remote=allow_remote)
    data.prep_hymn_2 = enrich_hymn(data.prep_hymn_2, allow_remote=allow_remote)
    data.praise_hymn = enrich_hymn(data.praise_hymn, allow_remote=allow_remote)
    data.hymn = enrich_hymn(data.hymn, allow_remote=allow_remote)
    data.response_hymn = enrich_hymn(data.response_hymn, allow_remote=allow_remote)
    data.offering_hymn = enrich_hymn(data.offering_hymn, allow_remote=allow_remote)

    if force_hymn_lyrics:
        data.include_hymn_lyrics = True
        for slot in data.iter_hymns():
            slot.include_lyrics = True

    # Normalize free-text fields
    data.apostles_creed = normalize_breaks(data.apostles_creed)
    data.responsive_reading = normalize_breaks(data.responsive_reading)
    data.responsive_reading_title = normalize_breaks(data.responsive_reading_title).strip()
    data.worship_prayer = normalize_breaks(data.worship_prayer)
    data.sermon_title = normalize_breaks(data.sermon_title).strip()
    data.sermon_subtitle = normalize_breaks(data.sermon_subtitle).strip()
    data.benediction = normalize_breaks(data.benediction)
    data.closing_note = normalize_breaks(data.closing_note)
    data.announcements = normalize_breaks(data.announcements)
    data.scripture_text = normalize_breaks(data.scripture_text)

    # 교독문: number, "교독문 N번", or title like "시편 23편"
    resp_key = (data.responsive_reading_title or "").strip()
    resp_body = normalize_breaks(data.responsive_reading or "").strip()
    if resp_key:
        result = lookup_responsive(resp_key, allow_remote=allow_remote)
        if result.found and result.body:
            labeled = format_responsive_label(result.number, result.title)
            if (
                not resp_body
                or parse_responsive_number(resp_key)
                or len(result.body) > len(resp_body) + 10
            ):
                data.responsive_reading_title = labeled
                data.responsive_reading = normalize_breaks(result.body)

    ref = normalize_breaks(data.scripture_reference or "").strip()
    body = normalize_breaks(data.scripture_text or "").strip()
    body_lines = [ln for ln in body.splitlines() if ln.strip()]
    rnksv_body = _looks_like_rnksv(body_lines) if body_lines else False
    bad_body = rnksv_body or _is_bad_verses(body_lines) or any(
        m in body
        for m in ("로컬 자료에 없어", "직접 입력", "본문이 없", "missing", "오늘의 말씀을 함께", "새번역")
    )
    if bad_body:
        body = ""
        data.scripture_text = ""
    if ref:
        result = lookup_scripture(ref, allow_remote=allow_remote)
        new_body = (
            verses_to_body(result.verses)
            if (
                result.found
                and result.verses
                and not _is_bad_verses(result.verses)
                and not _looks_like_rnksv(result.verses)
            )
            else ""
        )
        if new_body and (
            not body
            or bad_body
            or rnksv_body
            or _body_verse_count(body) < _body_verse_count(new_body)
            or len(new_body) > len(body) + 20
        ):
            data.scripture_text = normalize_breaks(new_body)
            data.scripture_reference = result.reference or ref
        elif result.found and result.reference:
            data.scripture_reference = result.reference
        else:
            data.scripture_reference = ref
    return data


def hymn_label(h: HymnEntry) -> str:
    num = normalize_breaks(h.number or "").strip()
    title = normalize_breaks(h.title or "").strip()
    if num and title:
        if "장" not in num and num.isdigit():
            num = f"{num}장"
        return f"{num}  ·  {title}"
    return title or num


def hymn_pair_label(*hymns: HymnEntry) -> str:
    parts = [hymn_label(h) for h in hymns if hymn_label(h)]
    return "  /  ".join(parts)
