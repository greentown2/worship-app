"""Build browser presentation HTML from WorshipData (aligned with Streamlit / PPT order)."""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from data_enrich import enrich_worship_data, hymn_label, hymn_pair_label
from defaults import ORDER_LABELS
from hymn_lookup import parse_hymn_number
from lookup_bundle import build_lookup_bundle, slim_lookup_for_html
from models import HymnEntry, WorshipData
from responsive_lookup import parse_responsive_number, sanitize_responsive_body
from text_normalize import normalize_breaks
from template_tokens import _creed_pages, _hymn_pages, _responsive_pages, _text_pages

ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "worship_presentation.html"

_HTML_VERSION = "2026-09-02-ads-type-v24"


def _esc(text: str) -> str:
    return html.escape(normalize_breaks(text or "").strip(), quote=True)


def _cover_image_data_uri() -> str:
    """Tiny SVG crucifix for HTML print preview — never embed the 800KB PNG."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 168" aria-hidden="true">'
        '<rect width="120" height="168" fill="#fff"/>'
        '<rect x="54" y="8" width="12" height="152" fill="#1a1a1a"/>'
        '<rect x="22" y="36" width="76" height="12" fill="#1a1a1a"/>'
        "</svg>"
    )
    return "data:image/svg+xml;charset=utf-8," + quote(svg, safe="")


def _hymn_label(h: HymnEntry) -> str:
    return hymn_label(h) or (h.number or h.title or "").strip() or "—"


def _hymn_has(h: HymnEntry) -> bool:
    return bool((h.number or "").strip() or (h.title or "").strip() or (h.lyrics or []))


def _scripture_ref_clean(ref: str) -> str:
    text = normalize_breaks(ref or "").strip()
    text = re.sub(
        r"\s*[\(\[]\s*(개역개정|새번역|개역한글|공동번역|NIV|ESV|KJV|GAE|RNKSV)\s*[\)\]]\s*$",
        "",
        text,
        flags=re.I,
    )
    return text.rstrip(".…⋯").strip()


def _creed_html(page: str) -> str:
    lines = [ln.strip() for ln in normalize_breaks(page).splitlines() if ln.strip()]
    return "<br>".join(_esc(ln) for ln in lines)


def _responsive_html(page: str) -> str:
    blocks: list[str] = []
    for ln in normalize_breaks(page).splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("인도자"):
            body = re.sub(r"^인도자\s*[:：]\s*", "", s)
            blocks.append(
                f'<div class="mb-5 leader-text"><span style="font-weight:700">인도자:</span> {_esc(body)}</div>'
            )
        elif s.startswith("회중"):
            body = re.sub(r"^회중\s*[:：]\s*", "", s)
            blocks.append(
                f'<div class="mb-5 congregation-text"><span style="font-weight:700">회중:</span> {_esc(body)}</div>'
            )
        else:
            blocks.append(f'<div class="mb-5">{_esc(s)}</div>')
    return "\n".join(blocks)


def _scripture_html(page: str) -> str:
    lines = [ln.strip() for ln in normalize_breaks(page).splitlines() if ln.strip()]
    body = "<br><br>".join(_esc(ln) for ln in lines)
    return f'<div class="text-left w-full max-w-5xl leading-relaxed">{body}</div>'


def _announce_html(text: str) -> str:
    lines = [ln.strip() for ln in normalize_breaks(text).splitlines() if ln.strip()]
    if not lines:
        lines = ["주일 예배에 오신 모든 분들을 주님의 이름으로 환영합니다."]
    items = "".join(f"<li>{_esc(ln)}</li>" for ln in lines[:12])
    return (
        '<ul class="text-left list-disc list-inside mt-8 text-3xl space-y-6 text-slate-200">'
        f"{items}</ul>"
    )


def _lyric_html(page: str) -> str:
    lines = [ln.strip() for ln in normalize_breaks(page).splitlines() if ln.strip()]
    return "<br>".join(_esc(ln) for ln in lines)


def _append_hymn_lyric_slides(
    slides: list[dict],
    *,
    header: str,
    label: str,
    hymn: HymnEntry,
    allow_remote: bool = True,
) -> None:
    """Append fullscreen lyric pages after a hymn intro section."""
    from hymn_lookup import (
        _looks_like_error_lyrics,
        _looks_like_incomplete_stub,
        _lyrics_richness,
        is_usable_lyrics,
        resolve_hymn_lyrics,
    )

    raw_lyrics = list(hymn.lyrics or [])
    num = parse_hymn_number(hymn.number or "")
    if num:
        hit = resolve_hymn_lyrics(str(num), hymn.title or "", allow_remote=allow_remote)
        options: list[list[str]] = []
        if raw_lyrics and is_usable_lyrics(raw_lyrics):
            options.append(raw_lyrics)
        if hit and hit.lyrics and is_usable_lyrics(hit.lyrics):
            options.append(list(hit.lyrics))
            if hit.title and (not label or label == "—" or str(num) in label):
                label = f"{hit.number}장  ·  {hit.title}"
        if options:
            raw_lyrics = max(
                options,
                key=lambda lines: (
                    0 if _looks_like_incomplete_stub(lines) else 1,
                    _lyrics_richness(lines),
                    len([ln for ln in lines if str(ln).strip()]),
                ),
            )

    pages = [p for p in _hymn_pages(raw_lyrics, lines_per_page=4) if (p or "").strip()]
    pages = [
        p
        for p in pages
        if p.strip()
        and "불러오지 못했" not in p
        and "가사를 직접 입력" not in p
    ]
    if not pages:
        if not num:
            return
        slides.append(
            {
                "type": "lyric",
                "header": header,
                "title": label or (f"{num}장" if num else "찬송가"),
                "content": _lyric_html(
                    f"(찬송가 {num or ''}장 가사를 찾지 못했습니다.\n"
                    "Streamlit에서 「온라인 보조 검색」을 켠 뒤 HTML을 다시 생성해 주세요.)"
                ),
            }
        )
        return
    total = len(pages)
    for i, page in enumerate(pages, start=1):
        title = f"{label} ({i}/{total})" if total > 1 else label
        slides.append(
            {
                "type": "lyric",
                "header": header,
                "title": title,
                "content": _lyric_html(page),
            }
        )


def _ensure_service_hymn_lyrics(bundle: dict, data: WorshipData, *, allow_remote: bool = True) -> dict:
    """Make sure this week's hymn numbers have full lyrics in the HTML lookup bundle."""
    from hymn_lookup import (
        _looks_like_error_lyrics,
        _looks_like_incomplete_stub,
        _lyrics_richness,
        is_usable_lyrics,
        resolve_hymn_lyrics,
    )

    lyrics_map = dict(bundle.get("hymnLyrics") or {})

    def _put(num: int, title: str, lines: list[str]) -> None:
        if not lines or _looks_like_error_lyrics(lines):
            return
        lyrics_map[str(num)] = {
            "title": title or "",
            "lyrics": "\n".join(str(ln).rstrip() for ln in lines),
        }

    for hymn in data.iter_hymns():
        num = parse_hymn_number(getattr(hymn, "number", "") or "")
        if not num:
            continue
        title = (getattr(hymn, "title", "") or "").strip()
        # Always resolve with remote compare for this week's hymns
        hit = resolve_hymn_lyrics(str(num), title, allow_remote=allow_remote)
        candidates: list[list[str]] = []
        slot = list(getattr(hymn, "lyrics", None) or [])
        if slot and is_usable_lyrics(slot):
            candidates.append(slot)
        existing = lyrics_map.get(str(num)) or {}
        if isinstance(existing, dict) and existing.get("lyrics"):
            candidates.append(str(existing.get("lyrics") or "").splitlines())
        elif isinstance(existing, str) and existing.strip():
            candidates.append(existing.splitlines())
        if hit and hit.lyrics and is_usable_lyrics(hit.lyrics):
            candidates.append(list(hit.lyrics))
            title = hit.title or title

        if not candidates:
            continue
        best = max(
            candidates,
            key=lambda lines: (
                0 if _looks_like_incomplete_stub(lines) else 1,
                _lyrics_richness(lines),
                len([ln for ln in lines if str(ln).strip()]),
            ),
        )
        _put(num, title, best)

    bundle = dict(bundle)
    bundle["hymnLyrics"] = lyrics_map
    return bundle


def build_presentation_slides(data: WorshipData, *, allow_remote: bool = True) -> list[dict]:
    """
    Slide list matching Streamlit / PPT worship order (10 steps + announcements).
    Hymn slots include intro + full lyric pages for fullscreen HTML projection.
    """
    # Prefer complete lyrics: honor allow_remote (HTML generator usually passes True)
    data = enrich_worship_data(data, allow_remote=allow_remote, force_hymn_lyrics=True)
    data.include_hymn_lyrics = True

    church = (data.church_name_en or data.church_name_ko or "").strip()
    meta = "  ·  ".join(
        x
        for x in [
            data.date,
            data.service_time,
            f"설교 {data.preacher}" if (data.preacher or "").strip() else "",
        ]
        if x
    )
    leader = (
        f"인도자 {(data.worship_leader or '').strip()}"
        if (data.worship_leader or "").strip()
        else ""
    )
    service_title = (data.service_title or "주일 예배").strip()
    prep = hymn_pair_label(*data.iter_prep_hymns()) or "—"
    praise = _hymn_label(data.praise_hymn)
    hymn = _hymn_label(data.hymn)
    offering = _hymn_label(data.offering_hymn)
    resp_title = (data.responsive_reading_title or "교독문").strip()
    scripture_ref = _scripture_ref_clean(data.scripture_reference or "")
    sermon = (data.sermon_title or "").strip()
    sermon_sub = (data.sermon_subtitle or "").strip()
    prayer_leader = (data.worship_prayer_leader or "").strip()
    benediction = (data.benediction or "축도").strip()

    slides: list[dict] = []

    # Cover — centered brand block (matches PPT cover info)
    slides.append(
        {
            "type": "cover",
            "title": service_title,
            "subtitle": meta or (data.date or ""),
            "footer": church,
            "extra": leader,
        }
    )

    # Order of worship (10 steps)
    details = {
        "1": prep,
        "2": praise,
        "3": "",
        "4": resp_title,
        "5": hymn,
        "6": prayer_leader,
        "7": scripture_ref,
        "8": sermon,
        "9": offering,
        "10": benediction,
    }
    order_rows = []
    for num, title, _en in ORDER_LABELS:
        detail = (details.get(num) or "").strip()
        if detail in {"", "—"} or detail == title or detail.startswith(title):
            extra = "" if detail in {"", "—", title} else detail[len(title):].lstrip(" ··")
            label = f"{num}. {title}" + (f"  ·  {extra}" if extra else "")
        else:
            label = f"{num}. {title}  ·  {detail}"
        order_rows.append(f"<div>{_esc(label)}</div>")
    slides.append(
        {
            "type": "title",
            "title": "예배 순서",
            "subtitle": "Order of Worship",
            "content": (
                '<div class="order-list grid grid-cols-1 gap-y-3 text-left w-max max-w-full mt-2 '
                'font-bold text-slate-200">'
                + "".join(order_rows)
                + "</div>"
            ),
        }
    )

    # 1. 예배 준비의 시간 — up to 5 hymns, intro + lyrics each
    prep_hymns = [h for h in data.iter_prep_hymns() if _hymn_has(h)]
    if prep_hymns:
        for h in prep_hymns:
            label = _hymn_label(h)
            slides.append({"type": "section", "title": "1. 예배 준비의 시간", "subtitle": label})
            _append_hymn_lyric_slides(
                slides,
                header="1. 예배 준비의 시간",
                label=label,
                hymn=h,
                allow_remote=allow_remote,
            )
    else:
        slides.append({"type": "section", "title": "1. 예배 준비의 시간", "subtitle": ""})

    # 2. 찬양과 기도 — intro + lyrics
    slides.append({"type": "section", "title": "2. 찬양과 기도", "subtitle": praise})
    _append_hymn_lyric_slides(
        slides,
        header="2. 찬양과 기도",
        label=praise,
        hymn=data.praise_hymn,
        allow_remote=allow_remote,
    )

    # 3. 사도신경
    creed_src = "\n".join(
        ln.strip() for ln in normalize_breaks(data.apostles_creed or "").splitlines() if ln.strip()
    )
    creed_pages = _creed_pages(creed_src, lines_per_page=4) if creed_src else [""]
    for i, page in enumerate(creed_pages):
        if not (page or "").strip():
            continue
        slides.append(
            {
                "type": "creed",
                "header": "3. 사도신경",
                "title": "사도신경" + (f" ({i + 1}/{len(creed_pages)})" if len(creed_pages) > 1 else ""),
                "content": _creed_html(page),
            }
        )

    # 4. 교독문
    slides.append({"type": "section", "title": "4. 교독문", "subtitle": resp_title})
    resp_body = sanitize_responsive_body(data.responsive_reading or "")
    for page in _responsive_pages(resp_body):
        if not (page or "").strip():
            continue
        slides.append(
            {
                "type": "responsive",
                "header": "4. 교독문",
                "title": resp_title,
                "content": _responsive_html(page),
            }
        )

    # 5. 찬송가 — intro + lyrics
    slides.append({"type": "section", "title": "5. 찬송가", "subtitle": hymn})
    _append_hymn_lyric_slides(
        slides,
        header="5. 찬송가",
        label=hymn,
        hymn=data.hymn,
        allow_remote=allow_remote,
    )

    # 6. 예배의 기도
    prayer_sub = prayer_leader or "다함께 마음을 모아 주님께 기도드립니다."
    slides.append({"type": "section", "title": "6. 예배의 기도", "subtitle": prayer_sub})
    prayer = normalize_breaks(data.worship_prayer or "").strip()
    if prayer:
        slides.append(
            {
                "type": "scripture",
                "header": "6. 예배의 기도",
                "title": prayer_leader or "예배의 기도",
                "content": (
                    f'<div class="text-left w-full max-w-5xl leading-relaxed">'
                    f"{_creed_html(prayer)}</div>"
                ),
            }
        )

    # 7. 오늘의 말씀
    slides.append(
        {
            "type": "section",
            "title": "7. 오늘의 말씀",
            "subtitle": scripture_ref or "성경 봉독",
        }
    )
    bible_pages = _text_pages(data.scripture_text or "", lines_per_page=4)
    for page in bible_pages:
        if not (page or "").strip():
            continue
        slides.append(
            {
                "type": "scripture",
                "header": "7. 오늘의 말씀",
                "title": scripture_ref,
                "content": _scripture_html(page),
            }
        )

    # 8. 생명의 말씀
    slides.append(
        {
            "type": "sermon",
            "header": "8. 생명의 말씀",
            "title": sermon or "생명의 말씀",
            "subtitle": sermon_sub or (f"본문: {scripture_ref}" if scripture_ref else ""),
            "footer": church,
        }
    )

    # 9. 감사와 봉헌 — intro + lyrics
    slides.append({"type": "section", "title": "9. 감사와 봉헌", "subtitle": offering})
    _append_hymn_lyric_slides(
        slides,
        header="9. 감사와 봉헌",
        label=offering,
        hymn=data.offering_hymn,
        allow_remote=allow_remote,
    )

    # 10. 축도
    slides.append({"type": "section", "title": "10. 축도", "subtitle": benediction})
    note = normalize_breaks(data.closing_note or "").strip()
    if note:
        slides.append(
            {
                "type": "title",
                "title": benediction,
                "subtitle": note,
                "content": "",
            }
        )

    # Announcements
    ads = normalize_breaks(data.announcements or "").strip()
    slides.append(
        {
            "type": "title",
            "title": "11. 안내 및 광고",
            "subtitle": "Announcements",
            "content": _announce_html(ads),
        }
    )

    # Closing
    note = normalize_breaks(data.closing_note or "").strip()
    slides.append(
        {
            "type": "cover",
            "title": "평안히 돌아가십시오",
            "subtitle": note or "God Bless You",
            "footer": church,
        }
    )
    return slides


def build_form_prefetch(data: WorshipData) -> dict:
    """Values to prefill the HTML editor panel from Streamlit."""
    def _num(h: HymnEntry) -> str:
        n = parse_hymn_number(h.number or "")
        return str(n) if n else ""

    def _lyrics(h: HymnEntry) -> str:
        if parse_hymn_number(h.number or ""):
            return ""
        return "\n".join(str(ln) for ln in (h.lyrics or []) if str(ln).strip() or ln == "")

    resp_n = parse_responsive_number(data.responsive_reading_title or "")
    return {
        "churchName": data.church_name_en or data.church_name_ko or "",
        "churchNameKo": data.church_name_ko or "플러톤 빌라 교회",
        "churchNameEn": data.church_name_en or "",
        "worshipDate": "  ·  ".join(x for x in [data.date, data.service_time] if x),
        **{
            k: v
            for i, h in enumerate(data.iter_prep_hymns(), start=1)
            for k, v in (
                (f"prepHymn{i}Num", _num(h)),
                (f"prepHymn{i}Title", (h.title or "").strip() if not _num(h) else (_hymn_label(h) if _hymn_has(h) else "")),
                (f"prepHymn{i}Lyrics", _lyrics(h)),
            )
        },
        "hymn1Num": _num(data.praise_hymn),
        "hymn1Title": _hymn_label(data.praise_hymn),
        "hymn1Lyrics": _lyrics(data.praise_hymn),
        "responsiveNum": str(resp_n) if resp_n else "",
        "responsiveTitle": data.responsive_reading_title or "",
        "hymn2Num": _num(data.hymn),
        "hymn2Title": _hymn_label(data.hymn),
        "hymn2Lyrics": _lyrics(data.hymn),
        "bibleRef": _scripture_ref_clean(data.scripture_reference or ""),
        "bibleText": normalize_breaks(data.scripture_text or ""),
        "memoryVerseRef": _scripture_ref_clean(getattr(data, "memory_verse_reference", "") or ""),
        "memoryVerseText": normalize_breaks(getattr(data, "memory_verse_text", "") or ""),
        "sermonTitle": data.sermon_title or "",
        "hymn4Num": _num(data.offering_hymn),
        "hymn4Title": _hymn_label(data.offering_hymn),
        "hymn4Lyrics": _lyrics(data.offering_hymn),
        "worshipLeader": data.worship_leader or "",
        "serviceTitle": data.service_title or "주일 예배",
        "apostlesCreed": normalize_breaks(data.apostles_creed or ""),
        "responsiveBody": normalize_breaks(data.responsive_reading or ""),
        "prayerText": normalize_breaks(data.worship_prayer or ""),
        "prayerLeader": data.worship_prayer_leader or "",
        "benediction": data.benediction or "",
        "closingNote": normalize_breaks(data.closing_note or ""),
        "announcements": normalize_breaks(data.announcements or ""),
    }


def generate_worship_html(
    data: WorshipData,
    *,
    allow_remote: bool = True,
    pptx_bytes: bytes | None = None,
    pptx_name: str = "worship.pptx",
    pdf_bytes: bytes | None = None,
    pdf_name: str = "bulletin.pdf",
    content_id: str = "",
) -> bytes:
    """Return a standalone HTML presentation filled from WorshipData."""
    # Warm this week's hymns into local DB first (remote only fills gaps)
    from hymn_lookup import parse_hymn_number, warm_hymn_numbers

    nums = []
    for h in data.iter_hymns():
        n = parse_hymn_number(getattr(h, "number", "") or "")
        if n:
            nums.append(n)
    if nums:
        warmed = warm_hymn_numbers(nums, allow_remote=bool(allow_remote))
        # Push warmed lyrics onto slots so slides never see stubs
        for slot_name in (
            *[f"prep_hymn_{i}" for i in range(1, 6)],
            "praise_hymn",
            "hymn",
            "offering_hymn",
            "response_hymn",
        ):
            slot = getattr(data, slot_name)
            n = parse_hymn_number(getattr(slot, "number", "") or "")
            hit = warmed.get(str(n)) if n else None
            if not hit or not hit.lyrics or not hit.found_lyrics:
                continue
            from hymn_lookup import is_usable_lyrics

            if is_usable_lyrics(hit.lyrics):
                slot.lyrics = list(hit.lyrics)
                if hit.title:
                    slot.title = hit.title

    slides = build_presentation_slides(data, allow_remote=bool(allow_remote))
    prefetch = build_form_prefetch(data)
    # Never embed PPT/PDF bytes — that alone was ~2MB and broke mobile GitHub Pages.
    lookup = slim_lookup_for_html(
        _ensure_service_hymn_lyrics(
            build_lookup_bundle(), data, allow_remote=bool(allow_remote)
        ),
        data,
    )
    cover_image = _cover_image_data_uri()
    payload = {
        "version": _HTML_VERSION,
        "contentId": content_id or "",
        "slides": slides,
        "form": prefetch,
        "source": "streamlit",
        "artifacts": {},
        "coverImage": cover_image,
        "lookup": lookup,
    }
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    injection = (
        "<script>\n"
        f"window.WORSHIP_PAYLOAD = {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))};\n"
        "</script>\n"
    )
    if "<!-- WORSHIP_PAYLOAD -->" in template:
        out = template.replace("<!-- WORSHIP_PAYLOAD -->", injection)
    else:
        out = template.replace("</head>", injection + "</head>", 1)

    # PWA manifest next to shared HTML (iPad home-screen = true fullscreen)
    try:
        manifest = {
            "name": "주일 예배 화면",
            "short_name": "주일예배",
            "start_url": "./worship_live.html?present=1",
            "scope": "./",
            "display": "fullscreen",
            "orientation": "any",
            "background_color": "#000000",
            "theme_color": "#000000",
            "lang": "ko",
        }
        (ROOT / "output").mkdir(parents=True, exist_ok=True)
        (ROOT / "output" / "worship.webmanifest").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        css_src = ROOT / "worship-deck.css"
        if css_src.exists():
            shutil.copy2(css_src, ROOT / "output" / "worship-deck.css")
    except OSError:
        pass

    return out.encode("utf-8")
