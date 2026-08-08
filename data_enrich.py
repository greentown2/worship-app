"""Enrich WorshipData — resolve hymn lyrics and scripture for all order slots."""

from __future__ import annotations

import re

from hymn_lookup import is_usable_lyrics, lookup_hymn
from models import HymnEntry, WorshipData
from scripture_lookup import lookup_scripture, verses_to_body
from text_normalize import normalize_breaks, normalize_line_list


def enrich_hymn(h: HymnEntry, *, allow_remote: bool = True) -> HymnEntry:
    number = normalize_breaks(h.number or "").strip()
    title = normalize_breaks(h.title or "").strip()
    lyrics = normalize_line_list(h.lyrics or [])
    if not (number or title):
        return h

    needs = not is_usable_lyrics(lyrics)
    # Also refresh when existing lyrics look like a short stub
    stubby = len([ln for ln in lyrics if ln.strip()]) < 6
    if needs or stubby or (number and not title):
        result = lookup_hymn(number or title, title, allow_remote=allow_remote)
        if result:
            number = f"{result.number}장" if result.number else number
            title = title or result.title
            if result.lyrics and (
                not is_usable_lyrics(lyrics)
                or len(normalize_line_list(result.lyrics)) >= len(lyrics)
            ):
                lyrics = normalize_line_list(result.lyrics)

    if (number or title) and not is_usable_lyrics(lyrics):
        result = lookup_hymn(number or title, title, allow_remote=allow_remote)
        if result and result.lyrics:
            lyrics = normalize_line_list(result.lyrics)
            title = title or result.title
            if result.number and not number:
                number = f"{result.number}장"

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
    data.praise_hymn = enrich_hymn(data.praise_hymn, allow_remote=allow_remote)
    data.hymn = enrich_hymn(data.hymn, allow_remote=allow_remote)
    data.response_hymn = enrich_hymn(data.response_hymn, allow_remote=allow_remote)
    data.offering_hymn = enrich_hymn(data.offering_hymn, allow_remote=allow_remote)

    if force_hymn_lyrics:
        data.include_hymn_lyrics = True
        for slot in (data.praise_hymn, data.hymn, data.response_hymn, data.offering_hymn):
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

    ref = normalize_breaks(data.scripture_reference or "").strip()
    body = normalize_breaks(data.scripture_text or "").strip()
    bad_body = any(
        m in body
        for m in ("로컬 자료에 없어", "직접 입력", "본문이 없", "missing", "오늘의 말씀을 함께")
    )
    if ref:
        result = lookup_scripture(ref, allow_remote=allow_remote)
        new_body = verses_to_body(result.verses) if result.verses else ""
        if new_body and (
            not body
            or bad_body
            or _body_verse_count(body) < _body_verse_count(new_body)
            or len(new_body) > len(body) + 20
        ):
            data.scripture_text = normalize_breaks(new_body)
            data.scripture_reference = result.reference or ref
        elif result.reference:
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
