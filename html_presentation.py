"""Build browser presentation HTML from WorshipData (aligned with Streamlit / PPT order)."""

from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path

from data_enrich import enrich_worship_data, hymn_label
from defaults import ORDER_LABELS
from hymn_lookup import parse_hymn_number
from lookup_bundle import build_lookup_bundle
from models import HymnEntry, WorshipData
from responsive_lookup import parse_responsive_number, sanitize_responsive_body
from text_normalize import normalize_breaks
from template_tokens import _creed_pages, _hymn_pages, _responsive_pages, _text_pages

ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "worship_presentation.html"

_HTML_VERSION = "2026-08-23-hymn-refrain-expand"


def _esc(text: str) -> str:
    return html.escape(normalize_breaks(text or "").strip(), quote=True)


def _hymn_label(h: HymnEntry) -> str:
    return hymn_label(h) or (h.number or h.title or "").strip() or "—"


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
) -> None:
    """Append fullscreen lyric pages after a hymn intro section."""
    from hymn_lookup import _looks_like_error_lyrics, lookup_hymn

    raw_lyrics = list(hymn.lyrics or [])
    # If enrich left this slot empty, fetch full lyrics now (online if needed)
    usable = [
        str(ln).rstrip()
        for ln in raw_lyrics
        if str(ln).strip() and not any(
            m in str(ln) for m in ("불러오지 못했", "가사가 없", "직접 입력", "로컬 캐시")
        )
    ]
    if len(usable) < 4 or _looks_like_error_lyrics(raw_lyrics):
        num = parse_hymn_number(hymn.number or "") or parse_hymn_number(label)
        if num:
            hit = lookup_hymn(str(num), hymn.title or "", allow_remote=True)
            if hit and hit.lyrics and not _looks_like_error_lyrics(hit.lyrics):
                raw_lyrics = list(hit.lyrics)
                if hit.title and (not label or label == "—"):
                    label = f"{hit.number}장  ·  {hit.title}"

    pages = [p for p in _hymn_pages(raw_lyrics, lines_per_page=4) if (p or "").strip()]
    # Drop placeholder-only pages
    pages = [
        p
        for p in pages
        if p.strip()
        and "불러오지 못했" not in p
        and "가사를 직접 입력" not in p
    ]
    if not pages:
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


def _ensure_service_hymn_lyrics(bundle: dict, data: WorshipData) -> dict:
    """Make sure this week's hymn numbers have full lyrics in the HTML lookup bundle."""
    from hymn_lookup import _looks_like_error_lyrics, lookup_hymn

    lyrics_map = dict(bundle.get("hymnLyrics") or {})
    for hymn in (data.praise_hymn, data.hymn, data.offering_hymn, data.response_hymn):
        num = parse_hymn_number(getattr(hymn, "number", "") or "")
        if not num:
            continue
        key = str(num)
        existing = lyrics_map.get(key) or {}
        body = ""
        if isinstance(existing, dict):
            body = str(existing.get("lyrics") or "")
        elif isinstance(existing, str):
            body = existing
        # Refresh when missing or too short for a real hymn
        if body.count("\n") >= 5 and len(re.findall(r"[가-힣]", body)) >= 80:
            continue
        hit = lookup_hymn(key, getattr(hymn, "title", "") or "", allow_remote=True)
        if not hit or not hit.lyrics or _looks_like_error_lyrics(hit.lyrics):
            continue
        lyrics_map[key] = {
            "title": hit.title or (existing.get("title") if isinstance(existing, dict) else "") or "",
            "lyrics": "\n".join(str(ln).rstrip() for ln in hit.lyrics),
        }
    bundle = dict(bundle)
    bundle["hymnLyrics"] = lyrics_map
    return bundle


def build_presentation_slides(data: WorshipData, *, allow_remote: bool = True) -> list[dict]:
    """
    Slide list matching Streamlit / PPT worship order (9 steps).
    Hymn slots include intro + full lyric pages for fullscreen HTML projection.
    """
    # Prefer online full lyrics when local stubs are incomplete
    data = enrich_worship_data(data, allow_remote=True, force_hymn_lyrics=True)
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

    # Order of worship (9 steps)
    details = {
        "1": praise,
        "2": "",
        "3": resp_title,
        "4": hymn,
        "5": prayer_leader,
        "6": scripture_ref,
        "7": sermon,
        "8": offering,
        "9": benediction,
    }
    order_rows = []
    for num, title, _en in ORDER_LABELS:
        detail = (details.get(num) or "").strip()
        label = f"{num}. {title}" + (f"  ·  {detail}" if detail and detail != "—" else "")
        order_rows.append(f"<div>{_esc(label)}</div>")
    slides.append(
        {
            "type": "title",
            "title": "예배 순서",
            "subtitle": "Order of Worship",
            "content": (
                '<div class="grid grid-cols-1 gap-y-4 text-left w-full max-w-4xl mx-auto mt-8 '
                'text-2xl text-slate-200">'
                + "".join(order_rows)
                + "</div>"
            ),
        }
    )

    # 1. 찬양과 기도 — intro + lyrics
    slides.append({"type": "section", "title": "1. 찬양과 기도", "subtitle": praise})
    _append_hymn_lyric_slides(
        slides,
        header="1. 찬양과 기도",
        label=praise,
        hymn=data.praise_hymn,
    )

    # 2. 사도신경
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
                "header": "2. 사도신경",
                "title": "사도신경" + (f" ({i + 1}/{len(creed_pages)})" if len(creed_pages) > 1 else ""),
                "content": _creed_html(page),
            }
        )

    # 3. 교독문
    slides.append({"type": "section", "title": "3. 교독문", "subtitle": resp_title})
    resp_body = sanitize_responsive_body(data.responsive_reading or "")
    for page in _responsive_pages(resp_body):
        if not (page or "").strip():
            continue
        slides.append(
            {
                "type": "responsive",
                "header": "3. 교독문",
                "title": resp_title,
                "content": _responsive_html(page),
            }
        )

    # 4. 찬송가 — intro + lyrics
    slides.append({"type": "section", "title": "4. 찬송가", "subtitle": hymn})
    _append_hymn_lyric_slides(
        slides,
        header="4. 찬송가",
        label=hymn,
        hymn=data.hymn,
    )

    # 5. 예배의 기도
    prayer_sub = prayer_leader or "다함께 마음을 모아 주님께 기도드립니다."
    slides.append({"type": "section", "title": "5. 예배의 기도", "subtitle": prayer_sub})
    prayer = normalize_breaks(data.worship_prayer or "").strip()
    if prayer:
        slides.append(
            {
                "type": "scripture",
                "header": "5. 예배의 기도",
                "title": prayer_leader or "예배의 기도",
                "content": (
                    f'<div class="text-left w-full max-w-5xl leading-relaxed">'
                    f"{_creed_html(prayer)}</div>"
                ),
            }
        )

    # 6. 오늘의 말씀
    slides.append(
        {
            "type": "section",
            "title": "6. 오늘의 말씀",
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
                "header": "6. 오늘의 말씀",
                "title": scripture_ref,
                "content": _scripture_html(page),
            }
        )

    # 7. 생명의 말씀
    slides.append(
        {
            "type": "sermon",
            "header": "7. 생명의 말씀",
            "title": sermon or "생명의 말씀",
            "subtitle": sermon_sub or (f"본문: {scripture_ref}" if scripture_ref else ""),
            "footer": church,
        }
    )

    # 8. 감사와 봉헌 — intro + lyrics
    slides.append({"type": "section", "title": "8. 감사와 봉헌", "subtitle": offering})
    _append_hymn_lyric_slides(
        slides,
        header="8. 감사와 봉헌",
        label=offering,
        hymn=data.offering_hymn,
    )

    # 9. 축도
    slides.append({"type": "section", "title": "9. 축도", "subtitle": benediction})
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
            "title": "10. 소식 · 광고",
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

    resp_n = parse_responsive_number(data.responsive_reading_title or "")
    return {
        "churchName": data.church_name_en or data.church_name_ko or "",
        "worshipDate": "  ·  ".join(x for x in [data.date, data.service_time] if x),
        "hymn1Num": _num(data.praise_hymn),
        "hymn1Title": _hymn_label(data.praise_hymn),
        "responsiveNum": str(resp_n) if resp_n else "",
        "responsiveTitle": data.responsive_reading_title or "",
        "hymn2Num": _num(data.hymn),
        "hymn2Title": _hymn_label(data.hymn),
        "bibleRef": _scripture_ref_clean(data.scripture_reference or ""),
        "bibleText": normalize_breaks(data.scripture_text or ""),
        "sermonTitle": data.sermon_title or "",
        "hymn4Num": _num(data.offering_hymn),
        "hymn4Title": _hymn_label(data.offering_hymn),
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
) -> bytes:
    """Return a standalone HTML presentation filled from WorshipData."""
    slides = build_presentation_slides(data, allow_remote=allow_remote)
    prefetch = build_form_prefetch(data)
    artifacts: dict = {}
    if pptx_bytes:
        artifacts["pptx"] = {
            "name": pptx_name,
            "base64": base64.b64encode(pptx_bytes).decode("ascii"),
            "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
    if pdf_bytes:
        artifacts["pdf"] = {
            "name": pdf_name,
            "base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "mime": "application/pdf",
        }
    payload = {
        "version": _HTML_VERSION,
        "slides": slides,
        "form": prefetch,
        "source": "streamlit",
        "artifacts": artifacts,
        "lookup": _ensure_service_hymn_lyrics(build_lookup_bundle(), data),
    }
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    injection = (
        "<script>\n"
        f"window.WORSHIP_PAYLOAD = {json.dumps(payload, ensure_ascii=False)};\n"
        "</script>\n"
    )
    if "<!-- WORSHIP_PAYLOAD -->" in template:
        out = template.replace("<!-- WORSHIP_PAYLOAD -->", injection)
    else:
        out = template.replace("</head>", injection + "</head>", 1)
    return out.encode("utf-8")
