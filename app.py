"""Grace Worship — Fullerton Villa order of worship UI."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import json
import os

import streamlit as st

# Streamlit Cloud clones to /mount/src. __file__ can be a temp copy without data/.
def _pin_workdir() -> Path:
    here = Path(__file__).resolve().parent
    for raw in (Path("/mount/src"), Path("/app"), here, Path.cwd()):
        try:
            cand = Path(raw).resolve()
        except OSError:
            continue
        if (
            (cand / "hymn_index_embed.py").is_file()
            or (cand / "data" / "hymn_index.json").is_file()
            or (cand / "hymn_assets" / "hymn_index.json").is_file()
        ):
            try:
                os.chdir(cand)
            except OSError:
                pass
            return cand
    try:
        os.chdir(here)
    except OSError:
        pass
    return here


_APP_DIR = _pin_workdir()
import sys
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from bulletin_parser import (
    PAGE_ROLES,
    ROLE_LABELS,
    parse_multipage_bulletin,
    parse_uploaded_bulletin_multipage,
)
from text_normalize import normalize_breaks, normalize_line_list

# Streamlit can keep stale modules in memory — always reload from disk
import importlib

import app_paths
import bulletin_parser
import defaults
import models
import build_master_templates
import data_enrich
import hymn_assets
import hymn_catalog
try:
    import hymn_db
except Exception:
    hymn_db = None
import hymn_lookup
import html_presentation
import lookup_bundle
import pdf_generator
import ppt_library
import pptx_generator
import pptx_from_slides
import pptx_html_capture
import pptx_polish
import pptx_slide_copy
import responsive_lookup
import scripture_lookup
import template_tokens

# Re-execute app.py on every Streamlit rerun, but keep imported modules (and
# their lyric caches) unless a .py file on disk actually changed.
_CODE_MODULES = tuple(
    pair for pair in (
        ("app_paths", app_paths),
        ("defaults", defaults),
        ("models", models),
        ("scripture_lookup", scripture_lookup),
        ("hymn_db", hymn_db),
        ("hymn_catalog", hymn_catalog),
        ("hymn_lookup", hymn_lookup),
        ("responsive_lookup", responsive_lookup),
        ("data_enrich", data_enrich),
        ("bulletin_parser", bulletin_parser),
        ("lookup_bundle", lookup_bundle),
        ("build_master_templates", build_master_templates),
        ("template_tokens", template_tokens),
        ("pdf_generator", pdf_generator),
        ("ppt_library", ppt_library),
        ("pptx_slide_copy", pptx_slide_copy),
        ("pptx_polish", pptx_polish),
        ("pptx_html_capture", pptx_html_capture),
        ("pptx_from_slides", pptx_from_slides),
        ("pptx_generator", pptx_generator),
        ("html_presentation", html_presentation),
    )
    if pair[1] is not None
)


def _source_stamp() -> tuple:
    root = Path(__file__).resolve().parent
    stamp = []
    for name, _mod in _CODE_MODULES:
        path = root / f"{name}.py"
        stamp.append((name, path.stat().st_mtime_ns if path.exists() else 0))
    return tuple(stamp)


_stamp = _source_stamp()
_prev_stamp = getattr(hymn_lookup, "_app_src_stamp", None)
if _prev_stamp != _stamp:
    if _prev_stamp is not None:
        for _name, _mod in _CODE_MODULES:
            importlib.reload(_mod)
        try:
            app_paths.clear_json_cache()
        except Exception:
            pass
        for _fn in (
            getattr(scripture_lookup, "_load_common", None),
            getattr(hymn_lookup, "_load_lyrics", None),
            getattr(hymn_lookup, "_load_index", None),
            getattr(hymn_lookup, "_load_runtime_cache", None),
            getattr(responsive_lookup, "_load_readings", None),
            getattr(responsive_lookup, "_load_index", None),
        ):
            if _fn is not None:
                try:
                    _fn.cache_clear()
                except Exception:
                    pass
    hymn_lookup._app_src_stamp = _stamp

from bulletin_parser import (
    PAGE_ROLES,
    ROLE_LABELS,
    parse_multipage_bulletin,
    parse_uploaded_bulletin_multipage,
)
from data_enrich import enrich_worship_data, hymn_label
from defaults import (
    CHURCH_NAME_EN,
    CHURCH_NAME_KO,
    CHURCH_NAME_KO_ALIASES,
    DEFAULT_APOSTLES_CREED,
    DEFAULT_BENEDICTION,
    DEFAULT_RESPONSIVE_READING,
    DEFAULT_SERVICE_TIME,
    DEFAULT_SERVICE_TITLE,
    DEFAULT_WORSHIP_PRAYER,
)
from models import PREP_HYMN_COUNT, HymnEntry, WorshipData
from hymn_lookup import lookup_hymn, parse_hymn_number, _looks_like_error_lyrics
from html_presentation import generate_worship_html
import html_share
from pdf_generator import bulletin_preview_text, generate_worship_pdf
from pptx_generator import generate_worship_pptx, pptx_slide_previews, scan_placeholders
from responsive_lookup import format_responsive_label, lookup_responsive, parse_responsive_number
from scripture_lookup import first_verse_body, lookup_scripture, single_verse_reference, verses_to_body

DEFAULT_WORSHIP_LEADER = getattr(defaults, "DEFAULT_WORSHIP_LEADER", "엄영민 목사")

_PDF_VERSION = getattr(pdf_generator, "_PDF_VERSION", "folded-letter")

HYMN_DB_BUILD = "20260918k"

st.set_page_config(
    page_title=f"Grace Worship · 찬송DB {HYMN_DB_BUILD}",
    page_icon="✝",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&family=Source+Serif+4:wght@600;700&display=swap');
    :root {
      --ink: #152019;
      --muted: #5a665e;
      --accent: #2f4a36;
      --accent-soft: #e6efe8;
      --line: #d5ddd7;
      --panel: #f7faf8;
    }
    html, body, [class*="css"] {
      font-family: "Noto Sans KR", "Malgun Gothic", sans-serif;
      color: var(--ink);
    }
    .stApp {
      background:
        radial-gradient(1200px 500px at 10% -10%, #e8f0ea 0%, transparent 55%),
        linear-gradient(180deg, #f4f7f5 0%, #eef3f0 100%);
    }
    .main .block-container { padding-top: 1.35rem; padding-bottom: 3.5rem; max-width: 1040px; }
    h1 {
      font-family: "Source Serif 4", "Noto Sans KR", serif !important;
      font-weight: 700 !important;
      letter-spacing: -0.03em !important;
      color: var(--ink) !important;
      font-size: 2.05rem !important;
    }
    .subtitle {
      color: var(--muted);
      margin-top: -0.35rem;
      margin-bottom: 1.15rem;
      font-size: 0.98rem;
      letter-spacing: -0.01em;
    }
    section[data-testid="stSidebar"],
    [data-testid="stSidebar"],
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"] {
      background: #f4f7f5 !important;
      color: #152019 !important;
      border-right: 1px solid #d5ddd7;
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
      color: #152019 !important;
    }
    .bulletin-banner {
        background: linear-gradient(135deg, #f8fbf9 0%, var(--accent-soft) 100%);
        border: 1px solid var(--line);
        border-left: 4px solid var(--accent);
        border-radius: 8px;
        padding: 0.95rem 1.1rem;
        margin: 0.35rem 0 1rem 0;
        box-shadow: 0 1px 0 rgba(21,32,25,0.04);
    }
    div[data-testid="stDownloadButton"] button,
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: var(--accent) !important;
        color: #fff !important;
        font-weight: 650 !important;
        border: none !important;
        border-radius: 8px !important;
    }
    div[data-testid="stButton"] button {
        border-radius: 8px !important;
        border-color: var(--line) !important;
        color: #152019 !important;
        background: #fff !important;
    }
    .order-step {
        font-weight: 700;
        color: var(--accent);
        margin-top: 0.7rem;
        padding: 0.35rem 0 0.15rem 0;
        border-bottom: 1px solid var(--line);
        letter-spacing: -0.01em;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--panel);
        border: 1px solid var(--line) !important;
        border-radius: 10px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _init_state():
    defaults = {
        "church_en": CHURCH_NAME_EN,
        "church_ko": CHURCH_NAME_KO,
        "service_title": DEFAULT_SERVICE_TITLE,
        "service_time": DEFAULT_SERVICE_TIME,
        "preacher": "",
        "worship_leader": DEFAULT_WORSHIP_LEADER,
        **{
            k: ""
            for i in range(1, PREP_HYMN_COUNT + 1)
            for k in (f"prep_hymn_{i}_num", f"prep_hymn_{i}_title")
        },
        "praise_num": "7",
        "praise_title": "",
        "_allow_remote": True,
        "apostles_creed": DEFAULT_APOSTLES_CREED,
        "responsive_num": "13",
        "responsive_title": "교독문 13번  ·  시편 23편",
        "responsive_body": "",
        "resolved_responsive": None,
        "hymn_num": "30",
        "hymn_title": "",
        "prayer_text": DEFAULT_WORSHIP_PRAYER,
        "prayer_leader": "",
        "choir_anthem_num": "",
        "choir_anthem_title": "",
        "scripture_reference_input": "히브리서 4:1-11",
        "scripture_text_area": "",
        "memory_verse_ref": "",
        "memory_verse_text": "",
        "resolved_memory_verse": None,
        "response_num": "",
        "response_title": "",
        "sermon_title": "",
        "sermon_subtitle": "",
        "offering_num": "35",
        "offering_title": "",
        "benediction": DEFAULT_BENEDICTION,
        "closing_note": "다음에 또 만나요. 평안하세요.",
        "announcements": "",
        "page_plan": {},
        "bulletin_pages": [],
        "bulletin_role_map": {},
        "resolved_scripture": None,
        "master_pptx_bytes": None,
        "master_pptx_name": "",
        "master_pptx_placeholders": [],
        "include_lyrics_ppt": False,
        "upload_parse_notes": [],
        "upload_raw_preview": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Prefer current brand spelling — wipe legacy wrong names (esp. PPT leftovers)
    _cko = (st.session_state.get("church_ko") or "").strip()
    _aliases = set(CHURCH_NAME_KO_ALIASES) | {
        "플러튼 빌라 교회",
        "플로튼 장로교회",
        "플로튼 장로 교회",
    }
    if (not _cko) or (_cko in _aliases) or ("플로튼" in _cko) or ("장로교회" in _cko.replace(" ", "")):
        st.session_state["church_ko"] = CHURCH_NAME_KO
    # Always use the full official English name on the cover
    st.session_state["church_en"] = CHURCH_NAME_EN
    if not (st.session_state.get("worship_leader") or "").strip():
        st.session_state["worship_leader"] = DEFAULT_WORSHIP_LEADER
    # Keep creed dense (no blank paragraph gaps); prefer user-saved template
    _creed_now = (st.session_state.get("apostles_creed") or "").strip()
    if _creed_now and "\n\n" in _creed_now.replace("\r\n", "\n"):
        dense = "\n".join(ln.strip() for ln in _creed_now.splitlines() if ln.strip())
        if dense:
            st.session_state["apostles_creed"] = dense
            _creed_now = dense
    if not _creed_now:
        st.session_state["apostles_creed"] = DEFAULT_APOSTLES_CREED

    # Drop leftover 새번역 scripture body so the next lookup fills 개역개정
    _sbody = (st.session_state.get("scripture_text_area") or "").strip()
    if _sbody and (
        scripture_lookup._looks_like_rnksv(_sbody)
        or "새번역" in (st.session_state.get("scripture_reference_input") or "")
    ):
        st.session_state["scripture_text_area"] = ""
        st.session_state["_pending_scripture_body"] = ""
        ref_now = (st.session_state.get("scripture_reference_input") or "").replace(" (새번역)", "").strip()
        if ref_now:
            st.session_state["scripture_reference_input"] = ref_now

    # Apply pending widget values BEFORE any widgets are created
    pending = {
        **{
            f"_p_prep_hymn_{i}_num": f"prep_hymn_{i}_num"
            for i in range(1, PREP_HYMN_COUNT + 1)
        },
        **{
            f"_p_prep_hymn_{i}_title": f"prep_hymn_{i}_title"
            for i in range(1, PREP_HYMN_COUNT + 1)
        },
        "_p_praise_num": "praise_num",
        "_p_praise_title": "praise_title",
        "_p_hymn_num": "hymn_num",
        "_p_hymn_title": "hymn_title",
        "_p_choir_anthem_num": "choir_anthem_num",
        "_p_choir_anthem_title": "choir_anthem_title",
        "_p_response_num": "response_num",
        "_p_response_title": "response_title",
        "_p_offering_num": "offering_num",
        "_p_offering_title": "offering_title",
        "_pending_scripture_ref": "scripture_reference_input",
        "_pending_scripture_body": "scripture_text_area",
        "_pending_memory_verse_ref": "memory_verse_ref",
        "_pending_memory_verse_text": "memory_verse_text",
        "_pending_responsive_title": "responsive_title",
        "_pending_responsive_body": "responsive_body",
        "_pending_responsive_num": "responsive_num",
    }
    for src, dst in pending.items():
        if src in st.session_state:
            st.session_state[dst] = st.session_state.pop(src)

    # Bulletin upload batch apply (full field map)
    if "_pending_bulletin_fields" in st.session_state:
        fields = st.session_state.pop("_pending_bulletin_fields")
        plan: dict = {}
        for key, value in fields.items():
            if key == "_page_plan_cover":
                plan["cover_order"] = [int(x) for x in str(value).split(",") if x.strip().isdigit()]
                continue
            if key == "_page_plan_readings":
                plan["readings"] = [int(x) for x in str(value).split(",") if x.strip().isdigit()]
                continue
            if key == "_page_plan_announcements":
                plan["announcements"] = [int(x) for x in str(value).split(",") if x.strip().isdigit()]
                continue
            st.session_state[key] = value
            # Seed hymn lyric caches + titles via local lookup
            if key in (
                *[f"prep_hymn_{i}_num" for i in range(1, PREP_HYMN_COUNT + 1)],
                "praise_num",
                "hymn_num",
                "choir_anthem_num",
                "offering_num",
            ) and value:
                hit = lookup_hymn(str(value), allow_remote=False)
                if hit:
                    if hit.lyrics:
                        st.session_state[f"lyrics_cache_{key}"] = list(hit.lyrics)
                    title_key = key.replace("_num", "_title")
                    if hit.title and not (st.session_state.get(title_key) or "").strip():
                        st.session_state[title_key] = hit.title
                    st.session_state[f"resolved_hymn_{key}"] = {
                        "number": hit.number,
                        "title": hit.title,
                        "source": hit.source,
                        "lyrics": len(hit.lyrics or []),
                    }
        if plan:
            st.session_state["page_plan"] = plan
        # Mark 교독문 / 성경 as resolved when upload filled them
        if st.session_state.get("responsive_num") or st.session_state.get("responsive_body"):
            rn = parse_responsive_number(str(st.session_state.get("responsive_num") or ""))
            st.session_state["resolved_responsive"] = {
                "number": rn or 0,
                "title": st.session_state.get("responsive_title") or "",
                "found": bool(st.session_state.get("responsive_body")),
                "source": "upload",
            }
        if st.session_state.get("scripture_reference_input") and st.session_state.get(
            "scripture_text_area"
        ):
            st.session_state["resolved_scripture"] = {
                "reference": st.session_state.get("scripture_reference_input"),
                "found": True,
                "source": "upload",
                "message": "",
            }


def _apply_multipage_bulletin(mp) -> None:
    """Queue multipage parse into session for next run."""
    parsed = mp.parsed
    fields = dict(parsed.field_map or {})
    st.session_state["_pending_bulletin_fields"] = fields
    st.session_state["upload_parse_notes"] = list(parsed.notes or [])
    st.session_state["upload_raw_preview"] = (parsed.raw_text or "")[:6000]
    st.session_state["upload_method"] = parsed.method or mp.method or ""
    st.session_state["bulletin_pages"] = [
        {
            "index": p.index,
            "text": p.text,
            "method": p.method,
            "suggested_role": p.suggested_role,
            "preview": p.preview,
        }
        for p in (mp.pages or [])
    ]
    st.session_state["bulletin_role_map"] = {int(k): v for k, v in (mp.role_map or {}).items()}


def _apply_parsed_bulletin(parsed) -> None:
    """Queue parsed bulletin fields into session_state for next run."""
    fields = parsed.field_map or {}
    st.session_state["_pending_bulletin_fields"] = fields
    st.session_state["upload_parse_notes"] = list(parsed.notes or [])
    st.session_state["upload_raw_preview"] = (parsed.raw_text or "")[:4000]
    st.session_state["upload_method"] = parsed.method or ""


def _current_role_map_from_ui(pages: list) -> dict[int, str]:
    role_map: dict[int, str] = {}
    for p in pages:
        idx = int(p["index"])
        key = f"page_role_{idx}"
        role_map[idx] = st.session_state.get(key) or p.get("suggested_role") or "cover_order"
    return role_map


def _rebuild_plan_from_roles(role_map: dict[int, str]) -> dict[str, list[int]]:
    plan: dict[str, list[int]] = {"cover_order": [], "readings": [], "announcements": []}
    for idx, role in sorted(role_map.items()):
        if role in plan:
            plan[role].append(idx)
    return plan


def _lyrics_line_score(lines: list[str]) -> int:
    body = [ln for ln in (lines or []) if (ln or "").strip()]
    return len(body) * 10 + sum(len(ln) for ln in body)


def _hymn_from_keys(num_key: str, title_key: str, *, allow_remote: bool) -> HymnEntry:
    num = normalize_breaks(st.session_state.get(num_key) or "").strip()
    title = normalize_breaks(st.session_state.get(title_key) or "").strip()
    text_lyrics = normalize_line_list(
        (st.session_state.get(f"lyrics_text_{num_key}") or "").splitlines()
    )
    cached = normalize_line_list(st.session_state.get(f"lyrics_cache_{num_key}") or [])
    seed = text_lyrics or cached
    if not parse_hymn_number(num):
        # Pasted lyrics only — do not reuse a previous 찬송가 cache
        entry = HymnEntry(
            number="",
            title=title,
            lyrics=list(text_lyrics),
            include_lyrics=bool(title or text_lyrics),
        )
        if text_lyrics:
            st.session_state[f"lyrics_cache_{num_key}"] = list(text_lyrics)
        else:
            st.session_state.pop(f"lyrics_cache_{num_key}", None)
        return entry
    if not (num or title):
        return HymnEntry(lyrics=list(seed), include_lyrics=bool(seed))
    # When a number is present, resolve title from the catalog (not a stale title)
    result = lookup_hymn(
        num or title,
        "" if parse_hymn_number(num) else title,
        allow_remote=allow_remote,
    )
    if result:
        lyrics = normalize_line_list(result.lyrics or [])
        # Prefer editable textarea / session seed only when it is fuller and not a stub
        from hymn_lookup import _looks_like_error_lyrics, _looks_like_incomplete_stub, is_usable_lyrics

        seed_ok = (
            seed
            and is_usable_lyrics(seed)
            and not _looks_like_incomplete_stub(seed)
            and not _looks_like_error_lyrics(seed)
        )
        lookup_ok = lyrics and is_usable_lyrics(lyrics) and not _looks_like_error_lyrics(lyrics)
        if seed_ok and (not lookup_ok or _lyrics_line_score(seed) > _lyrics_line_score(lyrics)):
            lyrics = seed
        elif not lookup_ok and seed:
            lyrics = seed
        catalog_title = result.title or title
        entry = HymnEntry(
            number=f"{result.number}장" if result.number else num,
            title=catalog_title,
            lyrics=lyrics,
            include_lyrics=True,
        )
    else:
        entry = HymnEntry(number=num, title=title, lyrics=list(seed), include_lyrics=True)
    if entry.lyrics:
        st.session_state[f"lyrics_cache_{num_key}"] = entry.lyrics
    elif seed:
        entry.lyrics = list(seed)
    return entry


def _build_worship_data(service_date, *, allow_remote: bool, force_lyrics: bool = True) -> WorshipData:
    body = normalize_breaks(st.session_state.get("scripture_text_area") or "").strip()
    ref = normalize_breaks(st.session_state.get("scripture_reference_input") or "").strip()
    if ref:
        result = lookup_scripture(ref, allow_remote=allow_remote)
        if (
            result.found
            and result.verses
            and not scripture_lookup._looks_like_rnksv(result.verses)
            and not scripture_lookup._is_bad_verses(result.verses)
        ):
            full = normalize_breaks(verses_to_body(result.verses))
            # Prefer freshly resolved 개역개정 text for PPT/PDF
            body = full
            ref = result.reference or ref
            # Queue body for the text area only — never rewrite the input with
            # a labeled ref that used to break re-parsing (now also stripped).
            if (st.session_state.get("scripture_text_area") or "").strip() != body:
                st.session_state["_pending_scripture_body"] = body

    mem_ref = normalize_breaks(st.session_state.get("memory_verse_ref") or "").strip()
    mem_body = normalize_breaks(st.session_state.get("memory_verse_text") or "").strip()
    if mem_ref:
        mem_result = lookup_scripture(mem_ref, allow_remote=allow_remote)
        mem_parsed = scripture_lookup.parse_scripture_reference(mem_ref)
        if (
            mem_result.found
            and mem_result.verses
            and not scripture_lookup._looks_like_rnksv(mem_result.verses)
            and not scripture_lookup._is_bad_verses(mem_result.verses)
        ):
            one = first_verse_body(mem_result.verses)
            labeled = single_verse_reference(mem_parsed, mem_result.reference or mem_ref)
            if labeled:
                mem_ref = labeled
                if (st.session_state.get("memory_verse_ref") or "").strip() != labeled:
                    st.session_state["_pending_memory_verse_ref"] = labeled
            if one and (not mem_body or mem_body == labeled or mem_body == mem_ref):
                mem_body = one
                st.session_state["_pending_memory_verse_text"] = one

    resp_num = normalize_breaks(st.session_state.get("responsive_num") or "").strip()
    resp_title = normalize_breaks(st.session_state.get("responsive_title") or "").strip()
    resp_body = normalize_breaks(st.session_state.get("responsive_body") or "").strip()
    resp_key = resp_num or resp_title
    resp_incomplete = (not resp_body) or not ("인도자:" in resp_body and "회중:" in resp_body)
    if resp_key and resp_incomplete:
        hit = lookup_responsive(resp_key, allow_remote=allow_remote)
        if hit.found and hit.body:
            labeled = format_responsive_label(hit.number, hit.title)
            resp_body = normalize_breaks(hit.body)
            resp_title = labeled
            if (st.session_state.get("responsive_body") or "").strip() != resp_body:
                st.session_state["_pending_responsive_body"] = resp_body
            if (st.session_state.get("responsive_title") or "").strip() != labeled:
                st.session_state["_pending_responsive_title"] = labeled
            if hit.number and str(st.session_state.get("responsive_num") or "").strip() != str(hit.number):
                st.session_state["_pending_responsive_num"] = str(hit.number)

    data = WorshipData(
        church_name_en=CHURCH_NAME_EN,
        church_name_ko=(
            CHURCH_NAME_KO
            if (
                ((st.session_state.get("church_ko") or "").strip() in set(CHURCH_NAME_KO_ALIASES))
                or ("플로튼" in (st.session_state.get("church_ko") or ""))
                or ("장로교회" in (st.session_state.get("church_ko") or "").replace(" ", ""))
                or not (st.session_state.get("church_ko") or "").strip()
            )
            else (st.session_state.get("church_ko") or CHURCH_NAME_KO).strip()
        ),
        service_title=(st.session_state.get("service_title") or DEFAULT_SERVICE_TITLE).strip(),
        date=service_date.strftime("%Y년 %m월 %d일"),
        service_time=(st.session_state.get("service_time") or DEFAULT_SERVICE_TIME).strip(),
        preacher=(st.session_state.get("preacher") or "").strip(),
        worship_leader=(st.session_state.get("worship_leader") or DEFAULT_WORSHIP_LEADER).strip(),
        **{
            f"prep_hymn_{i}": _hymn_from_keys(
                f"prep_hymn_{i}_num", f"prep_hymn_{i}_title", allow_remote=allow_remote
            )
            for i in range(1, PREP_HYMN_COUNT + 1)
        },
        praise_hymn=_hymn_from_keys("praise_num", "praise_title", allow_remote=allow_remote),
        apostles_creed=(st.session_state.get("apostles_creed") or "").strip(),
        responsive_reading_title=resp_title or resp_num,
        responsive_reading=resp_body,
        hymn=_hymn_from_keys("hymn_num", "hymn_title", allow_remote=allow_remote),
        worship_prayer=(st.session_state.get("prayer_text") or "").strip(),
        worship_prayer_leader=(st.session_state.get("prayer_leader") or "").strip(),
        choir_anthem=_hymn_from_keys(
            "choir_anthem_num", "choir_anthem_title", allow_remote=allow_remote
        ),
        scripture_reference=ref,
        scripture_text=body,
        memory_verse_reference=mem_ref,
        memory_verse_text=mem_body,
        response_hymn=HymnEntry(),  # removed from order — keep empty
        sermon_title=(st.session_state.get("sermon_title") or "").strip(),
        sermon_subtitle=(st.session_state.get("sermon_subtitle") or "").strip(),
        offering_hymn=_hymn_from_keys("offering_num", "offering_title", allow_remote=allow_remote),
        benediction=(st.session_state.get("benediction") or "").strip(),
        closing_note=(st.session_state.get("closing_note") or "").strip(),
        announcements=(st.session_state.get("announcements") or "").strip(),
        page_plan=dict(st.session_state.get("page_plan") or {}),
        source_pages=[],
        include_hymn_lyrics=bool(st.session_state.get("include_lyrics_ppt", True)),
    )
    # Live page-role mapping + exact source pages for 1:1 PDF
    pages = st.session_state.get("bulletin_pages") or []
    if pages:
        try:
            role_map = _current_role_map_from_ui(pages)
            data.page_plan = _rebuild_plan_from_roles(role_map)
            st.session_state["page_plan"] = data.page_plan
            data.source_pages = [
                {
                    "index": int(p["index"]),
                    "role": role_map.get(int(p["index"]), p.get("suggested_role") or "cover_order"),
                    "text": p.get("text") or "",
                }
                for p in pages
            ]
        except Exception:
            data.source_pages = [
                {
                    "index": int(p.get("index") or i + 1),
                    "role": p.get("suggested_role") or "cover_order",
                    "text": p.get("text") or "",
                }
                for i, p in enumerate(pages)
            ]
    return enrich_worship_data(data, allow_remote=allow_remote, force_hymn_lyrics=force_lyrics)


def _publish_html_for_devices(html_bytes: bytes) -> dict:
    """Write live HTML and start LAN share for iPad / iPhone."""
    live = html_share.ensure_live_file(html_bytes)
    st.session_state["html_live_path"] = str(live)
    info = html_share.start_share_server(live.parent)
    st.session_state["html_share"] = info
    return info


def _rebuild_pptx_for_data(data: WorshipData, *, allow_remote: bool, service_date) -> bytes | None:
    """Build worship PPT from the same WorshipData / slide list used for HTML."""
    data.include_hymn_lyrics = True
    out = generate_worship_pptx(
        data,
        master=st.session_state.get("master_pptx_bytes"),
        allow_remote=allow_remote,
        insert_this_week=False,
    )
    pptx_bytes = out.getvalue()
    st.session_state["pptx_file"] = pptx_bytes
    st.session_state["pptx_name"] = f"worship_{service_date.strftime('%Y%m%d')}.pptx"
    return pptx_bytes


def _render_device_share_panel() -> None:
    """Show LAN URL + QR so iPad/iPhone can open the worship HTML."""
    info = st.session_state.get("html_share") or {}
    live = st.session_state.get("html_live_path") or ""
    if not live or not Path(live).is_file():
        return

    st.markdown("##### iPad · iPhone으로 자동 공유")
    c1, c2 = st.columns([2, 1])
    with c1:
        if st.button("📱 iPad / iPhone 공유 시작", use_container_width=True, key="start_ios_share"):
            info = html_share.start_share_server(Path(live).parent)
            st.session_state["html_share"] = info
            if info.get("ok"):
                st.toast("공유가 시작되었습니다. QR 또는 주소로 여세요.")
            else:
                st.warning(info.get("message") or "공유를 시작할 수 없습니다.")
        url = (info or {}).get("url") or ""
        if info.get("ok") and url:
            st.success(info.get("message") or "공유 중")
            st.code(url, language=None)
            st.caption(
                "PC와 **같은 Wi‑Fi**에 연결한 뒤 Safari에서 주소를 열거나 QR을 스캔하세요. "
                "파일이 OneDrive 폴더에 있으면 OneDrive 앱에서도 동기화됩니다."
            )
            st.caption(f"로컬 파일: `{live}`")
        elif info and not info.get("ok"):
            st.warning(info.get("message") or "공유 서버가 꺼져 있습니다.")
        else:
            st.caption("버튼을 누르면 같은 Wi‑Fi의 iPad/iPhone에서 바로 열 수 있습니다.")
    with c2:
        url = (info or {}).get("url") or ""
        if info.get("ok") and url:
            png = html_share.qr_png_bytes(url)
            if png:
                st.image(png, caption="QR 스캔", width=180)
            else:
                st.caption("QR 표시를 위해 `pip install qrcode` 후 다시 시도하세요.")


def _on_hymn_num_change(num_key: str, title_key: str) -> None:
    """Streamlit widget callback: hymn number → catalog title + lyrics."""
    want = parse_hymn_number(st.session_state.get(num_key) or "")
    if not want:
        return
    prev = st.session_state.get(f"resolved_hymn_{num_key}") or {}
    if prev.get("number") != want:
        st.session_state.pop(f"lyrics_cache_{num_key}", None)
        st.session_state.pop(f"lyrics_text_{num_key}", None)
    allow_remote = bool(st.session_state.get("_allow_remote", True))
    hit = lookup_hymn(str(want), "", allow_remote=allow_remote)
    if not hit or not hit.number:
        st.session_state[f"resolved_hymn_{num_key}"] = {
            "number": want,
            "title": "",
            "source": "missing",
            "lyrics": 0,
        }
        return
    st.session_state[num_key] = str(hit.number)
    if hit.title:
        st.session_state[title_key] = hit.title
    lyrics = list(hit.lyrics or [])
    usable = (
        bool(lyrics)
        and getattr(hit, "found_lyrics", True)
        and hit.source != "generated"
        and not _looks_like_error_lyrics(lyrics)
    )
    if usable:
        st.session_state[f"lyrics_cache_{num_key}"] = lyrics
        st.session_state[f"lyrics_text_{num_key}"] = "\n".join(lyrics)
    st.session_state[f"resolved_hymn_{num_key}"] = {
        "number": hit.number,
        "title": hit.title,
        "source": getattr(hit, "source", "") or "",
        "lyrics": len(lyrics) if usable else 0,
    }


def _on_responsive_num_change() -> None:
    raw = (st.session_state.get("responsive_num") or "").strip()
    want = parse_responsive_number(raw)
    if not want:
        return
    hit = lookup_responsive(str(want), allow_remote=False)
    if not (hit.found and hit.body):
        st.session_state["resolved_responsive"] = {
            "number": want,
            "title": "",
            "found": False,
            "source": "missing",
        }
        return
    st.session_state["responsive_num"] = str(hit.number)
    st.session_state["responsive_title"] = format_responsive_label(hit.number, hit.title)
    st.session_state["responsive_body"] = normalize_breaks(hit.body)
    st.session_state["resolved_responsive"] = {
        "number": hit.number,
        "title": hit.title,
        "found": True,
        "source": hit.source,
    }


def _on_scripture_ref_change() -> None:
    ref = (st.session_state.get("scripture_reference_input") or "").strip()
    if not ref:
        return
    result = lookup_scripture(ref, allow_remote=False)
    parsed = scripture_lookup.parse_scripture_reference(ref)
    if (
        result.found
        and result.verses
        and not scripture_lookup._looks_like_rnksv(result.verses)
        and not scripture_lookup._is_bad_verses(result.verses)
    ):
        if parsed:
            st.session_state["scripture_reference_input"] = parsed.display
        st.session_state["scripture_text_area"] = normalize_breaks(verses_to_body(result.verses))
        st.session_state["resolved_scripture"] = {
            "reference": parsed.display if parsed else (result.reference or ref),
            "found": True,
            "source": result.source,
            "message": "",
        }
    else:
        st.session_state["resolved_scripture"] = {
            "reference": ref,
            "found": False,
            "source": getattr(result, "source", "") or "",
            "message": getattr(result, "message", "") or "본문을 찾지 못했습니다.",
        }


def _on_memory_verse_change() -> None:
    ref = (st.session_state.get("memory_verse_ref") or "").strip()
    if not ref:
        return
    result = lookup_scripture(ref, allow_remote=False)
    parsed = scripture_lookup.parse_scripture_reference(ref)
    if (
        result.found
        and result.verses
        and not scripture_lookup._looks_like_rnksv(result.verses)
        and not scripture_lookup._is_bad_verses(result.verses)
    ):
        labeled = single_verse_reference(parsed, result.reference or ref)
        if labeled:
            st.session_state["memory_verse_ref"] = labeled
        st.session_state["memory_verse_text"] = first_verse_body(result.verses)
        st.session_state["resolved_memory_verse"] = {
            "reference": labeled or ref,
            "found": True,
            "source": result.source,
            "message": "",
        }
    else:
        st.session_state["resolved_memory_verse"] = {
            "reference": ref,
            "found": False,
            "source": getattr(result, "source", "") or "",
            "message": getattr(result, "message", "") or "한 절을 찾지 못했습니다.",
        }


def _hymn_inputs(label: str, num_key: str, title_key: str, fetch_key: str, allow_remote: bool):
    """Hymn number → auto title only (lyrics optional later / PDF checkbox)."""
    st.markdown(f'<p class="order-step">{label}</p>', unsafe_allow_html=True)
    st.session_state["_allow_remote"] = allow_remote

    # Sync before widgets (covers IME / missed on_change when number already changed)
    want = parse_hymn_number(st.session_state.get(num_key) or "")
    resolved = st.session_state.get(f"resolved_hymn_{num_key}") or {}
    title_now = (st.session_state.get(title_key) or "").strip()
    if want and (resolved.get("number") != want or not title_now):
        _on_hymn_num_change(num_key, title_key)

    c1, c2, c3 = st.columns([1.1, 3.0, 1.5])
    with c1:
        st.text_input(
            "장번호",
            key=num_key,
            placeholder="예: 7",
            on_change=_on_hymn_num_change,
            args=(num_key, title_key),
        )
    with c2:
        st.text_input("제목", key=title_key, placeholder="번호 입력 시 자동 · 복음성가는 직접 입력")
    with c3:
        st.write("")
        st.write("")
        st.button(
            "가사 불러오기",
            key=fetch_key,
            use_container_width=True,
            on_click=_on_hymn_num_change,
            args=(num_key, title_key),
        )
    lyrics_key = f"lyrics_text_{num_key}"
    if lyrics_key not in st.session_state:
        st.session_state[lyrics_key] = ""
    has_custom = bool((st.session_state.get(lyrics_key) or "").strip()) and not parse_hymn_number(
        st.session_state.get(num_key) or ""
    )
    with st.expander("가사 붙여넣기 (복음성가)", expanded=has_custom):
        st.text_area(
            "가사",
            key=lyrics_key,
            height=110,
            placeholder="장번호가 있으면 자동입니다.\n복음성가는 번호를 비우고 여기에 가사를 붙여 넣으세요.",
            label_visibility="collapsed",
        )
    resolved = st.session_state.get(f"resolved_hymn_{num_key}")
    h = _hymn_from_keys(num_key, title_key, allow_remote=False)
    if parse_hymn_number(st.session_state.get(num_key) or "") and resolved and resolved.get("source") != "missing":
        n_lines = int(resolved.get("lyrics") or 0)
        extra = f" · 가사 {n_lines}줄" if n_lines else " · 가사 없음 → 가사 불러오기를 누르세요"
        st.caption(f"자동 제목: **{hymn_label(h) or resolved.get('title')}**{extra}")
    elif h.title or h.lyrics:
        st.caption(f"표시: **{hymn_label(h) or h.title}**")
    else:
        st.caption("찬송가는 장번호만 넣으면 됩니다. 복음성가는 번호를 비우고 제목과 가사를 넣으세요.")


def _hydrate_hymn_db() -> tuple[int, int, str]:
    """Load titles/lyrics without blocking the first paint on remote scrapes."""
    catalog_error = ""
    idx: dict = {}
    lyr: dict = {}
    try:
        if hymn_db is not None:
            idx = hymn_db.load_index()
            lyr = hymn_db.load_lyrics()
        else:
            catalog_error = "hymn_db import failed"
            idx = hymn_assets.index()
            lyr = hymn_assets.lyrics()
    except Exception as exc:
        catalog_error = f"{type(exc).__name__}: {exc}"
        try:
            idx = idx or hymn_assets.index()
            lyr = lyr or hymn_assets.lyrics()
        except Exception:
            pass
    n_index = sum(1 for k in idx if str(k).isdigit())
    n_lyrics = sum(1 for k in lyr if str(k).isdigit())
    if idx:
        hymn_catalog.INDEX = idx
    if lyr:
        hymn_catalog.LYRICS = lyr
    if n_index:
        hymn_catalog.SOURCE = "hymn_db"
    return n_index, n_lyrics, catalog_error


def main():
    _init_state()

    n_show_idx, n_show_ly, catalog_error = _hydrate_hymn_db()
    n_index, n_lyrics = n_show_idx, n_show_ly

    with st.sidebar:
        st.header("통합 흐름")
        st.markdown(
            "1. **템플릿** — 다중 페이지 업로드/매핑  \n"
            "2. **자동 불러오기** — 찬송·교독·성경 번호  \n"
            "3. **일치 출력** — 주보 PDF + PPT + HTML"
        )
        st.divider()
        st.header("예배 순서")
        st.markdown(
            "1. 예배 준비의 시간  \n2. 찬양과 기도  \n3. 사도신경  \n4. 교독문  \n"
            "5. 찬송가  \n6. 예배의 기도  \n7. 성가대 찬양  \n8. 오늘의 말씀  \n9. 생명의 말씀  \n"
            "10. 감사와 봉헌  \n11. 축도  \n12. 안내 및 광고"
        )
        allow_remote = st.toggle("온라인 보조 검색", value=True)
        st.caption("예배 직전에는 로컬 찬송 DB를 쓰는 것이 가장 안정적입니다.")
        src = getattr(hymn_catalog, "SOURCE", "") or "hymn_db"
        st.caption(f"찬송 DB 빌드 {HYMN_DB_BUILD}")
        if src:
            st.caption(f"DB 출처: {src}")
        st.metric("로컬 찬송 가사", f"{n_lyrics} / {n_index}")
        if catalog_error:
            st.caption(f"로드 오류: {catalog_error}")
        if (n_index == 0 or n_lyrics < 200) and hymn_db is not None:
            with st.expander("경로 진단", expanded=n_index == 0):
                st.code("\n".join(hymn_db.debug_lines()), language="text")
        if n_index == 0:
            st.error(
                "지금 화면이 예전 배포입니다. share.streamlit.io 에서 앱을 지운 뒤 "
                "GitHub `master` / Main file `app.py` 로 다시 Deploy 하세요."
            )
        if st.button("찬송 가사 DB 전체 받기 (645곡)", use_container_width=True, key="backfill_hymns"):
            with st.spinner("저장된 찬송 645곡을 앱에 복사하는 중…"):
                try:
                    import hymn_catalog as _install_cat

                    info = _install_cat.install_catalog()
                    try:
                        app_paths.clear_json_cache()
                    except Exception:
                        pass
                    st.session_state["_hymn_db_install_tried"] = True
                    st.session_state["_hymn_db_install_result"] = info
                    st.success(
                        f"완료 · 가사 {info.get('lyrics', 0)}곡 · 제목 {info.get('index', 0)}곡 · "
                        f"출처 {info.get('source') or '-'}"
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"DB 업데이트 실패: {exc}")
        st.divider()
        st.caption("Worship PPT & PDF Generator")
        if st.button("다른 PPT 자료 보관함 열기", use_container_width=True, key="sidebar_ppt_lib"):
            ppt_library.open_folder(None)
            st.toast("PPT 보관함 폴더를 열었습니다.")
        if st.button("이번 주 사용할 PPT 열기", use_container_width=True, key="sidebar_ppt_week"):
            ppt_library.open_folder("this_week")
            st.toast("이번 주 사용할 PPT 폴더를 열었습니다.")

    st.title("Worship PPT & PDF Generator")
    st.caption(f"빌드 {HYMN_DB_BUILD} · 로컬 찬송 {n_lyrics}/{n_index}")
    st.markdown(
        '<p class="subtitle">'
        "① 다중 페이지 주보 업로드 → ② 번호만으로 찬송·교독·성경 자동 채움 → "
        "③ 주보 PDF · PPT · 예배화면 HTML을 <strong>한 번에</strong> 생성"
        "</p>",
        unsafe_allow_html=True,
    )
    if n_lyrics < 200:
        st.error(
            f"찬송 DB {n_lyrics}/{n_index}. 이 숫자가 0/0 이고 빌드가 {HYMN_DB_BUILD}가 "
            "아니면 Streamlit이 예전 코드를 실행 중입니다. "
            "https://share.streamlit.io 에서 앱을 삭제한 뒤 "
            "`greentown2/worship-app` / 브랜치 `main` / "
            "Main file `app.py` 로 다시 Deploy 하세요."
        )

    st.session_state["_allow_remote"] = False
    if not st.session_state.get("_bootstrapped_lookups"):
        for nk, tk in (
            *[(f"prep_hymn_{i}_num", f"prep_hymn_{i}_title") for i in range(1, PREP_HYMN_COUNT + 1)],
            ("praise_num", "praise_title"),
            ("hymn_num", "hymn_title"),
            ("choir_anthem_num", "choir_anthem_title"),
            ("offering_num", "offering_title"),
        ):
            if parse_hymn_number(st.session_state.get(nk) or "") and not (
                st.session_state.get(tk) or ""
            ).strip():
                _on_hymn_num_change(nk, tk)
        if parse_responsive_number(st.session_state.get("responsive_num") or "") and not (
            st.session_state.get("responsive_body") or ""
        ).strip():
            _on_responsive_num_change()
        if (st.session_state.get("scripture_reference_input") or "").strip() and not (
            st.session_state.get("scripture_text_area") or ""
        ).strip():
            _on_scripture_ref_change()
        st.session_state["_bootstrapped_lookups"] = True
    st.session_state["_allow_remote"] = allow_remote

    # ===== TOP: Custom bulletin upload & auto-template parser =====
    st.markdown(
        '<div class="bulletin-banner">'
        "<strong>1단계 · 예배 순서 템플릿 자동 생성 (다중 페이지)</strong> — "
        "PDF·사진·텍스트를 올리면 페이지별로 분석하고, 입력칸·주보·PPT에 같은 내용으로 매핑합니다."
        "</div>",
        unsafe_allow_html=True,
    )
    st.subheader("예배 순서 템플릿 자동 생성 (다중 페이지)")
    st.caption(
        "현재 주보나 예배 순서를 업로드하세요. 여러 파일이면 Page 1, 2… 로 처리되고, "
        "찬송 장번호·교독문 번호·성경 구절이 보이면 본문까지 자동으로 채웁니다."
    )

    uploaded_files = st.file_uploader(
        "주보 / 예배 순서 파일 (다중 선택 가능)",
        type=["pdf", "png", "jpg", "jpeg", "webp", "txt", "md"],
        accept_multiple_files=True,
        help="다중 페이지 PDF, 페이지별 이미지, 또는 --- Page N --- 구분 텍스트를 지원합니다.",
        key="bulletin_uploader",
    )
    paste_text = st.text_area(
        "또는 주보/예배 순서 텍스트를 붙여넣기 (페이지는 빈 줄 3개 또는 --- Page N --- 로 구분)",
        height=110,
        placeholder="예:\n1. 예배 준비의 시간  9장  20장  30장  40장  50장\n2. 찬양과 기도  7장\n…\n\n\n--- Page 2 ---\n오늘의 말씀 히브리서 4:1-11\n…",
        key="bulletin_paste",
    )

    u1, u2 = st.columns([1.4, 1])
    with u1:
        parse_upload = st.button(
            "업로드 파일 분석 → 페이지별 미리보기",
            type="primary",
            use_container_width=True,
            key="btn_parse_upload",
            disabled=not uploaded_files,
        )
    with u2:
        parse_paste = st.button(
            "붙여넣은 텍스트 분석",
            use_container_width=True,
            key="btn_parse_paste",
            disabled=not (paste_text or "").strip(),
        )

    if parse_upload and uploaded_files:
        with st.spinner("다중 페이지 주보를 분석하는 중…"):
            files = [(f.name, f.getvalue()) for f in uploaded_files]
            mp = parse_uploaded_bulletin_multipage(files)
        _apply_multipage_bulletin(mp)
        st.rerun()

    if parse_paste and (paste_text or "").strip():
        with st.spinner("텍스트를 분석하는 중…"):
            # Treat paste as a text "upload" so page markers split correctly
            mp = parse_uploaded_bulletin_multipage([("paste.txt", paste_text.encode("utf-8"))])
        _apply_multipage_bulletin(mp)
        st.rerun()

    pages = st.session_state.get("bulletin_pages") or []
    if pages:
        st.markdown("#### 페이지별 미리보기 · 섹션 매핑")
        st.caption(
            "각 페이지가 인쇄 주보 PDF / PPT의 어느 구역으로 갈지 선택하세요. "
            "예: Page 1 → 표지·예배 순서, Page 2 → 말씀·교독·광고"
        )
        role_options = [r[0] for r in PAGE_ROLES]
        saved_roles = st.session_state.get("bulletin_role_map") or {}

        tabs = st.tabs([f"Page {p['index']}" for p in pages])
        for tab, p in zip(tabs, pages):
            with tab:
                idx = int(p["index"])
                default_role = saved_roles.get(idx) or p.get("suggested_role") or "cover_order"
                if default_role not in role_options:
                    default_role = "cover_order"
                st.selectbox(
                    f"Page {idx} → 출력 섹션",
                    options=role_options,
                    index=role_options.index(default_role),
                    format_func=lambda k: ROLE_LABELS.get(k, k),
                    key=f"page_role_{idx}",
                )
                st.caption(f"추출 방식: `{p.get('method') or '—'}` · 자동 추정: {ROLE_LABELS.get(p.get('suggested_role'), '')}")
                st.text((p.get("text") or "(텍스트 없음)")[:3500])

        map1, map2 = st.columns([1.4, 1])
        with map1:
            if st.button("페이지 매핑 적용 → 입력칸 채우기", type="primary", use_container_width=True, key="btn_apply_roles"):
                role_map = _current_role_map_from_ui(pages)
                rebuilt_pages = []
                from bulletin_parser import BulletinPage

                for p in pages:
                    rebuilt_pages.append(
                        BulletinPage(
                            index=int(p["index"]),
                            text=p.get("text") or "",
                            method=p.get("method") or "",
                            suggested_role=role_map.get(int(p["index"]), p.get("suggested_role") or "cover_order"),
                            preview=p.get("preview") or "",
                        )
                    )
                with st.spinner("매핑에 맞춰 다시 병합하는 중…"):
                    mp = parse_multipage_bulletin(rebuilt_pages, role_map=role_map)
                _apply_multipage_bulletin(mp)
                st.session_state["page_plan"] = _rebuild_plan_from_roles(role_map)
                st.rerun()
        with map2:
            plan = st.session_state.get("page_plan") or _rebuild_plan_from_roles(_current_role_map_from_ui(pages))
            bits = []
            for role, idxs in plan.items():
                if idxs:
                    bits.append(f"{ROLE_LABELS.get(role, role)} ← p.{', '.join(map(str, idxs))}")
            if bits:
                st.info(" · ".join(bits))

    if st.session_state.get("upload_parse_notes"):
        st.success("템플릿이 반영되었습니다. 아래 입력칸과 주보 PDF를 확인하세요.")
        method = st.session_state.get("upload_method") or ""
        if method:
            st.caption(f"추출 방식: `{method}`")
        for note in st.session_state["upload_parse_notes"][:16]:
            st.write(f"• {note}")
        with st.expander("추출된 원문 미리보기 (전체 페이지)", expanded=False):
            st.text(st.session_state.get("upload_raw_preview") or "(없음)")

    st.markdown("---")

    # ===== Cover =====
    st.subheader("표지 · 기본 정보")
    st.caption("아래 항목은 왼쪽부터 한 줄씩 입력됩니다.")
    st.text_input(
        "Church (EN)",
        value=CHURCH_NAME_EN,
        disabled=True,
        help="표지에는 항상 Fullerton Villa Community Church 가 표시됩니다.",
    )
    st.session_state["church_en"] = CHURCH_NAME_EN
    st.text_input("교회명 (KO)", key="church_ko")
    st.text_input("예배 제목", key="service_title")
    service_date = st.date_input("날짜", value=date.today(), key="service_date")
    st.text_input("예배 시간", key="service_time")
    st.text_input("설교자", key="preacher")
    st.text_input("예배 인도자", key="worship_leader", placeholder="엄영민 목사")

    st.info(
        "아래로 예배 순서를 입력하세요. **찬송 장번호 · 교독문 번호 · 성경 구절**만 넣어도 "
        "제목·본문이 자동으로 채워지며, 같은 내용으로 주보 PDF · PPT · HTML이 함께 만들어집니다."
    )

    st.markdown("---")

    # ===== Order 1–11 =====
    st.markdown(
        '<div class="bulletin-banner">'
        "<strong>2단계 · 예배 순서 입력 + 자동 불러오기</strong> — "
        "번호를 바꾸면 찬송·교독문·성경 본문을 자동으로 가져옵니다."
        "</div>",
        unsafe_allow_html=True,
    )
    st.subheader("예배 순서 입력 (1–11)")

    for i in range(1, PREP_HYMN_COUNT + 1):
        _hymn_inputs(
            f"1. 예배 준비의 시간 · {i}곡",
            f"prep_hymn_{i}_num",
            f"prep_hymn_{i}_title",
            f"fetch_prep_{i}",
            allow_remote,
        )

    _hymn_inputs("2. 찬양과 기도 (Praise & Prayer)", "praise_num", "praise_title", "fetch_praise", allow_remote)

    st.markdown('<p class="order-step">3. 사도신경</p>', unsafe_allow_html=True)
    st.text_area("사도신경 전문", key="apostles_creed", height=150)

    st.markdown('<p class="order-step">4. 교독문</p>', unsafe_allow_html=True)
    st.session_state["_allow_remote"] = allow_remote

    rc1, rc2, rc3 = st.columns([1.1, 2.6, 1.2])
    with rc1:
        st.text_input(
            "번호",
            key="responsive_num",
            placeholder="예: 13",
            on_change=_on_responsive_num_change,
        )
    with rc2:
        st.text_input("제목", key="responsive_title", placeholder="번호 입력 시 자동")
    with rc3:
        st.write("")
        st.write("")
        if st.button("교독문 불러오기", use_container_width=True, key="fetch_responsive"):
            raw = (st.session_state.get("responsive_num") or st.session_state.get("responsive_title") or "").strip()
            result = lookup_responsive(raw, allow_remote=allow_remote)
            st.session_state["resolved_responsive"] = {
                "number": result.number,
                "title": result.title,
                "found": result.found,
                "source": result.source,
            }
            if result.found:
                st.session_state["responsive_num"] = str(result.number) if result.number else raw
                st.session_state["responsive_title"] = format_responsive_label(
                    result.number, result.title
                )
                st.session_state["responsive_body"] = normalize_breaks(result.body)
            st.rerun()

    resolved_r = st.session_state.get("resolved_responsive")
    _want = parse_responsive_number(st.session_state.get("responsive_num") or "")
    if resolved_r and resolved_r.get("found"):
        st.success(
            f"자동: **교독문 {resolved_r.get('number')}번 · {resolved_r.get('title')}** · `{resolved_r.get('source')}`"
        )
    elif _want and not (resolved_r and resolved_r.get("found")):
        st.caption("번호를 입력(Enter)하면 교독문 본문이 자동으로 채워집니다.")
    st.text_area("교독문 본문 (`인도자:` / `회중:`)", key="responsive_body", height=140)

    _hymn_inputs("5. 찬송가 (Hymn)", "hymn_num", "hymn_title", "fetch_hymn", allow_remote)

    st.markdown('<p class="order-step">6. 예배의 기도</p>', unsafe_allow_html=True)
    p1, p2 = st.columns([2.2, 1])
    with p1:
        st.text_area("기도문", key="prayer_text", height=110)
    with p2:
        st.text_input("기도 인도", key="prayer_leader", placeholder="인도자")

    _hymn_inputs("7. 성가대 찬양", "choir_anthem_num", "choir_anthem_title", "fetch_choir", allow_remote)

    st.markdown('<p class="order-step">8. 오늘의 말씀</p>', unsafe_allow_html=True)
    st.session_state["_allow_remote"] = allow_remote

    sc1, sc2 = st.columns([3, 1])
    with sc1:
        st.text_input(
            "성경 구절",
            key="scripture_reference_input",
            placeholder="예: 히브리서 4:1-11 또는 히 4:1-11",
            on_change=_on_scripture_ref_change,
        )
    with sc2:
        st.write("")
        st.write("")
        if st.button("본문 불러오기", use_container_width=True, key="fetch_scripture"):
            try:
                app_paths.clear_json_cache()
            except Exception:
                pass
            _on_scripture_ref_change()
            st.rerun()
    resolved = st.session_state.get("resolved_scripture")
    if resolved and resolved.get("found"):
        st.success(f"자동: **{resolved['reference']}** · `{resolved['source']}`")
    elif resolved and resolved.get("message"):
        st.warning(resolved["message"])
    else:
        st.caption("성경 구절을 입력(Enter)하면 교독문처럼 개역개정 본문이 자동으로 채워집니다. 예: 히브리서 4:1-11 또는 히 4:1-11")
    st.text_area("성경 본문", key="scripture_text_area", height=150)

    st.markdown('<p class="order-step">금주의 암송구절</p>', unsafe_allow_html=True)
    mv1, mv2 = st.columns([3, 1])
    with mv1:
        st.text_input(
            "암송 구절 (한 절)",
            key="memory_verse_ref",
            placeholder="예: 요한복음 3:16 또는 요 3:16",
            on_change=_on_memory_verse_change,
        )
    with mv2:
        st.write("")
        st.write("")
        if st.button("한 절 불러오기", use_container_width=True, key="fetch_memory_verse"):
            _on_memory_verse_change()
            st.rerun()
    resolved_mv = st.session_state.get("resolved_memory_verse")
    if resolved_mv and resolved_mv.get("found"):
        st.success(f"암송: **{resolved_mv['reference']}** · `{resolved_mv['source']}`")
    elif resolved_mv and resolved_mv.get("message"):
        st.warning(resolved_mv["message"])
    else:
        st.caption("장·절을 넣으면 개역개정 한 절이 자동으로 채워지고, 주보 성경 본문 아래에 표시됩니다.")
    st.text_area(
        "암송 본문",
        key="memory_verse_text",
        height=80,
        placeholder="한 절 본문 (직접 입력도 가능)",
    )

    st.markdown('<p class="order-step">9. 생명의 말씀</p>', unsafe_allow_html=True)
    s1, s2 = st.columns(2)
    with s1:
        st.text_input("설교 제목", key="sermon_title", placeholder="생명의 말씀 제목")
    with s2:
        st.text_input("부제", key="sermon_subtitle")

    _hymn_inputs("10. 감사와 봉헌 (Offering)", "offering_num", "offering_title", "fetch_offering", allow_remote)

    st.markdown(
        '<div class="bulletin-banner" style="margin-top:0.5rem;">'
        "<strong>11–12 · 축도 · 안내 · 소식·광고</strong> — 주보·PPT·예배화면에 같이 들어갑니다."
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown('<p class="order-step">11. 축도</p>', unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        st.text_input("축도", key="benediction", placeholder="예: 담임목사")
    with b2:
        st.text_input("안내", key="closing_note", placeholder="예: 다음에 또 만나요. 평안하세요.")

    st.markdown('<p class="order-step">12. 안내 및 광고</p>', unsafe_allow_html=True)
    st.text_area(
        "소식 / 광고 본문 (한 줄에 하나씩)",
        key="announcements",
        height=140,
        placeholder="예:\n예배 후 친교실에서 교제가 있습니다.\n차량 운행에 협조해 주세요.\n중보 기도 요청은 사무실로 연락해 주세요.",
        help="주보 뒷면과 예배화면 광고 슬라이드에 동일하게 반영됩니다.",
    )

    # ===== ONE shared WorshipData → bulletin PDF + PPT + HTML together =====
    st.markdown("---")
    st.markdown(
        '<div class="bulletin-banner">'
        "<strong>3단계 · 주보 PDF · PPT · 예배화면 일치 생성</strong> — "
        "위 입력(또는 업로드 템플릿)이 <strong>같은 WorshipData</strong>로 주보·슬라이드·HTML에 반영됩니다."
        "</div>",
        unsafe_allow_html=True,
    )
    st.subheader("주보 PDF · 예배 PPT · 예배화면 HTML")
    st.info(
        "예배 PPT·HTML의 찬송은 **소개 슬라이드만** 나옵니다. "
        "실제 가사는 미리 받아 둔 찬송가 PPT를 따로 재생하세요. "
        "사도신경·교독문·성경 본문은 자동으로 채워집니다."
    )
    st.checkbox("주보 PDF에 찬송 가사 포함", key="include_lyrics_ppt")

    st.caption(
        f"주보 {_PDF_VERSION} · PPT {getattr(pptx_from_slides, '_PPTX_SLIDES_VERSION', 'dev')} · "
        "Letter 11×8.5 접지 + 예배 PPT (찬송 소개만)"
    )

    data = _build_worship_data(
        service_date,
        allow_remote=False,
        force_lyrics=bool(st.session_state.get("include_lyrics_ppt", False)),
    )
    # Apply queued widget updates on the next run (cannot mutate after widgets exist)
    if any(
        k in st.session_state
        for k in (
            "_pending_scripture_body",
            "_pending_scripture_ref",
            "_pending_responsive_body",
            "_pending_responsive_title",
            "_pending_responsive_num",
        )
    ):
        st.rerun()
    # PPT is built from the same slide list as HTML (includes hymn lyric pages)
    data.include_hymn_lyrics = True

    # this_week PPT files are merged into the master at HYMN_PREP_1..5 + HYMN_1/2/3 after generation
    try:
        _week_fp = "|".join(
            f"{p.name}:{p.stat().st_mtime_ns}:{p.stat().st_size}"
            for p in ppt_library.list_this_week()
        )
    except Exception:
        _week_fp = ""

    content_fingerprint = (
        f"{_PDF_VERSION}|{getattr(pptx_from_slides, '_PPTX_SLIDES_VERSION', '')}|"
        f"{getattr(pptx_generator, '_INJECT_VERSION', '')}|"
        f"{data.church_name_ko}|{data.worship_leader}|{data.sermon_title}|{data.sermon_subtitle}|"
        f"{data.scripture_reference}|{(data.scripture_text or '')[:120]}|"
        f"{data.memory_verse_reference}|{(data.memory_verse_text or '')[:80]}|"
        f"{data.responsive_reading_title}|{(data.responsive_reading or '')[:80]}|"
        f"{data.preacher}|{(data.announcements or '')[:80]}|"
        f"{'|'.join((h.number or '') + ':' + (h.title or '')[:24] + ':' + ''.join(h.lyrics or [])[:40] for h in data.iter_hymns())}|"
        f"{data.benediction}|{data.date}|"
        f"{(data.apostles_creed or '')[:40]}|{data.include_hymn_lyrics}|week:{_week_fp}"
    )

    templates_dir = Path(__file__).resolve().parent / "templates"
    bundled_master = templates_dir / "master_worship.pptx"
    design_ver = getattr(build_master_templates, "MASTER_DESIGN_VERSION", "dev")

    current_design = str(st.session_state.get("master_design_version") or "")
    is_manual_upload = current_design.startswith("upload:")
    if not st.session_state.get("master_pptx_bytes") and bundled_master.exists():
        st.session_state["master_pptx_bytes"] = bundled_master.read_bytes()
        st.session_state["master_pptx_name"] = "master_worship.pptx"
        if not is_manual_upload:
            st.session_state["master_design_version"] = current_design or design_ver
        try:
            st.session_state["master_pptx_placeholders"] = scan_placeholders(
                st.session_state["master_pptx_bytes"]
            )
        except Exception:
            st.session_state["master_pptx_placeholders"] = []

    mc1, mc2 = st.columns([2, 1])
    with mc1:
        master_upload = st.file_uploader(
            "선택: Master PPT 직접 업로드 (.pptx)",
            type=["pptx"],
            key="master_pptx_uploader",
            help="비워 두면 기본 시니어 마스터를 사용합니다.",
        )
    with mc2:
        st.write("")
        st.write("")
        if st.button("최신 배경 마스터 다시 불러오기", use_container_width=True, key="reload_master"):
            try:
                saved = build_master_templates.build_master_pptx(bundled_master)
                st.session_state["master_pptx_bytes"] = Path(saved).read_bytes()
                st.session_state["master_pptx_name"] = "master_worship.pptx"
                st.session_state["master_design_version"] = design_ver
                st.session_state.pop("pptx_file", None)
                st.session_state.pop("content_fingerprint", None)
                st.session_state["master_pptx_placeholders"] = scan_placeholders(
                    st.session_state["master_pptx_bytes"]
                )
                st.success("마스터를 다시 불러왔습니다.")
            except Exception as exc:
                st.error(f"마스터 불러오기 실패: {exc}")

    if master_upload is not None:
        st.session_state["master_pptx_bytes"] = master_upload.getvalue()
        st.session_state["master_pptx_name"] = master_upload.name
        st.session_state["master_design_version"] = f"upload:{master_upload.name}"
        st.session_state.pop("pptx_file", None)
        st.session_state.pop("content_fingerprint", None)
        try:
            st.session_state["master_pptx_placeholders"] = scan_placeholders(
                st.session_state["master_pptx_bytes"]
            )
        except Exception as exc:
            st.session_state["master_pptx_placeholders"] = []
            st.warning(f"마스터 파일을 읽는 중 문제가 있었습니다: {exc}")

    with st.expander("주보 내용 미리보기 (입력과 동일)", expanded=False):
        st.text(bulletin_preview_text(data))

    gc1, gc2 = st.columns([2, 1])
    with gc1:
        make_both = st.button(
            "주보 PDF + PPT + 예배화면 HTML 함께 만들기",
            type="primary",
            use_container_width=True,
            key="make_both",
        )
    with gc2:
        auto_both = st.toggle("자동 생성", value=False, key="auto_generate_outputs")
    st.caption("번호를 바꿀 때마다 PDF·PPT를 다시 만들지 않습니다. 다 입력한 뒤 「함께 만들기」를 누르세요.")

    engine_key = (
        f"{_PDF_VERSION}|{design_ver}|{getattr(pptx_from_slides, '_PPTX_SLIDES_VERSION', '')}|"
        f"{getattr(pptx_generator, '_INJECT_VERSION', '')}|"
        f"{getattr(html_presentation, '_HTML_VERSION', 'html')}|hymn-intro"
    )
    prev_engine = st.session_state.get("output_engine")
    engine_changed = prev_engine is not None and prev_engine != engine_key
    if st.session_state.get("output_engine") != engine_key:
        st.session_state.pop("pdf_file", None)
        st.session_state.pop("pptx_file", None)
        st.session_state.pop("html_file", None)
        st.session_state.pop("content_fingerprint", None)
        st.session_state["output_engine"] = engine_key
        if engine_changed:
            st.info(f"주보 디자인 엔진이 갱신되었습니다 · {_PDF_VERSION}")

    need_build = make_both or (
        auto_both and st.session_state.get("content_fingerprint") != content_fingerprint
    )
    if need_build:
        data = _build_worship_data(
            service_date,
            allow_remote=allow_remote,
            force_lyrics=True,
        )
        try:
            st.session_state["pdf_file"] = generate_worship_pdf(data, allow_remote=allow_remote).getvalue()
            st.session_state["pdf_name"] = f"bulletin_{service_date.strftime('%Y%m%d')}.pdf"
        except Exception as exc:
            st.error(f"PDF 오류: {exc}")

        # Rebuild bundled master only when the design version actually changed
        is_manual_upload = str(st.session_state.get("master_design_version") or "").startswith("upload:")
        if not is_manual_upload and st.session_state.get("master_design_version") != design_ver:
            try:
                saved = build_master_templates.build_master_pptx(bundled_master)
                st.session_state["master_pptx_bytes"] = Path(saved).read_bytes()
                st.session_state["master_pptx_name"] = "master_worship.pptx"
                st.session_state["master_design_version"] = design_ver
            except Exception as exc:
                st.warning(f"마스터 갱신 중 문제: {exc}")

        try:
            out = generate_worship_pptx(
                data,
                master=st.session_state.get("master_pptx_bytes"),
                allow_remote=allow_remote,
                insert_this_week=False,
            )
            st.session_state["pptx_file"] = out.getvalue()
            st.session_state["pptx_name"] = f"worship_{service_date.strftime('%Y%m%d')}.pptx"
            st.session_state["pptx_fingerprint"] = content_fingerprint
            notes = getattr(generate_worship_pptx, "last_insert_notes", None) or []
            if notes:
                st.info(" · ".join(notes))
        except Exception as exc:
            import traceback

            st.session_state.pop("pptx_file", None)
            st.session_state.pop("pptx_fingerprint", None)
            st.error(f"PPT 생성 오류: {exc}")
            st.code(traceback.format_exc())

        # Only embed PPT/PDF that match this exact worship content
        pptx_for_html = None
        pptx_name_for_html = st.session_state.get("pptx_name", "worship.pptx")
        if (
            st.session_state.get("pptx_file")
            and st.session_state.get("pptx_fingerprint") == content_fingerprint
        ):
            pptx_for_html = st.session_state["pptx_file"]
        pdf_for_html = st.session_state.get("pdf_file")

        try:
            st.session_state["html_file"] = generate_worship_html(
                data,
                allow_remote=allow_remote,
                pptx_bytes=pptx_for_html,
                pptx_name=pptx_name_for_html,
                pdf_bytes=pdf_for_html,
                pdf_name=st.session_state.get("pdf_name", "bulletin.pdf"),
                content_id=content_fingerprint,
            )
            st.session_state["html_name"] = f"worship_{service_date.strftime('%Y%m%d')}.html"
            st.session_state["html_fingerprint"] = content_fingerprint
            share = _publish_html_for_devices(st.session_state["html_file"])
            if share.get("ok"):
                st.info(f"iPad/iPhone 공유 주소 · {share.get('url')}")
            else:
                out_dir = Path(__file__).resolve().parent / "output"
                out_dir.mkdir(parents=True, exist_ok=True)
                live_path = out_dir / "worship_live.html"
                live_path.write_bytes(st.session_state["html_file"])
                st.session_state["html_live_path"] = str(live_path)
        except Exception as exc:
            import traceback

            st.error(f"예배화면 HTML 오류: {exc}")
            st.code(traceback.format_exc())

        st.session_state["content_fingerprint"] = content_fingerprint
        if make_both:
            st.success("같은 입력으로 주보 PDF · PPT · 예배화면 HTML을 함께 만들었습니다.")

    d1, d2, d3 = st.columns(3)
    with d1:
        if "pdf_file" in st.session_state:
            st.download_button(
                "⬇ 주보 PDF 다운로드",
                data=st.session_state["pdf_file"],
                file_name=st.session_state.get("pdf_name", "bulletin.pdf"),
                mime="application/pdf",
                use_container_width=True,
                key="dl_pdf",
            )
        else:
            st.caption("주보 PDF 대기 중")
    with d2:
        if "pptx_file" in st.session_state:
            st.download_button(
                "⬇ 예배 PPT 다운로드",
                data=st.session_state["pptx_file"],
                file_name=st.session_state.get("pptx_name", "worship.pptx"),
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True,
                type="primary",
                key="dl_pptx",
            )
            st.caption(
                "파일 이름이 **worship_날짜.pptx** 인지 확인하세요. "
                "Downloads의 예전 **master_worship_…pptx** 는 PowerPoint가 열 수 없습니다."
            )
        else:
            make_ppt = st.button(
                "⬇ 예배 PPT 다운로드",
                use_container_width=True,
                type="primary",
                key="dl_pptx_make",
                help="아직 PPT가 없으면 지금 생성한 뒤 다시 눌러 다운로드하세요.",
            )
            if make_ppt:
                try:
                    out = generate_worship_pptx(
                        data,
                        master=st.session_state.get("master_pptx_bytes"),
                        allow_remote=allow_remote,
                        insert_this_week=False,
                    )
                    st.session_state["pptx_file"] = out.getvalue()
                    st.session_state["pptx_name"] = f"worship_{service_date.strftime('%Y%m%d')}.pptx"
                    st.session_state["pptx_fingerprint"] = content_fingerprint
                    st.rerun()
                except Exception as exc:
                    st.error(f"PPT 생성 오류: {exc}")
    with d3:
        if "html_file" in st.session_state:
            st.download_button(
                "⬇ 예배화면 HTML",
                data=st.session_state["html_file"],
                file_name=st.session_state.get("html_name", "worship.html"),
                mime="text/html",
                use_container_width=True,
                key="dl_html",
            )
            if st.button("브라우저에서 예배화면 열기", use_container_width=True, key="open_html"):
                # Rebuild PPT + HTML from the same current data so downloads match the screen
                try:
                    pptx_bytes = _rebuild_pptx_for_data(
                        data, allow_remote=True, service_date=service_date
                    )
                    if pptx_bytes is not None:
                        st.session_state["pptx_fingerprint"] = content_fingerprint
                    fresh = generate_worship_html(
                        data,
                        allow_remote=True,
                        pptx_bytes=pptx_bytes or st.session_state.get("pptx_file"),
                        pptx_name=st.session_state.get("pptx_name", "worship.pptx"),
                        pdf_bytes=st.session_state.get("pdf_file"),
                        pdf_name=st.session_state.get("pdf_name", "bulletin.pdf"),
                        content_id=content_fingerprint,
                    )
                    st.session_state["html_file"] = fresh
                    st.session_state["html_fingerprint"] = content_fingerprint
                    _publish_html_for_devices(fresh)
                except Exception as exc:
                    st.warning(f"HTML 갱신 중 문제: {exc}")
                live = st.session_state.get("html_live_path") or ""
                if live and Path(live).is_file():
                    import os
                    import subprocess
                    import sys

                    if sys.platform.startswith("win"):
                        os.startfile(live)  # type: ignore[attr-defined]
                    elif sys.platform == "darwin":
                        subprocess.run(["open", live], check=False)
                    else:
                        subprocess.run(["xdg-open", live], check=False)
                    st.toast("최신 예배화면을 브라우저에서 열었습니다. (PPT도 같은 내용으로 갱신)")
                else:
                    st.warning("먼저 출력을 생성해 주세요.")
            _render_device_share_panel()
        else:
            st.caption("예배화면 HTML 대기 중")

    # —— PPT library: directly under download / open buttons ——
    ppt_library.ensure_dirs()
    st.markdown("---")
    lib_open, lib_toggle = st.columns([1, 2])
    with lib_open:
        if st.button("📂 다른 PPT 자료 보관함 열기", use_container_width=True, key="ppt_lib_open_below"):
            ppt_library.open_folder(None)
            st.toast("PPT 보관함 폴더를 열었습니다.")
    with lib_toggle:
        st.caption("찬송가·기타 PPT를 `library/ppt`에 보관 · 예배 마스터 PPT와 별도")

    with st.expander("다른 PPT 자료 보관 (찬송가 · 기타)", expanded=True):
        st.caption(
            "외부에서 가져온 찬송가 PPT·기타 PPT를 "
            f"`{ppt_library.LIBRARY_ROOT.relative_to(Path(__file__).resolve().parent)}` "
            "폴더에 모아 둡니다."
        )
        cat_label = st.radio(
            "보관 위치",
            options=["hymns", "other"],
            format_func=lambda k: ppt_library.CATEGORIES[k][0],
            horizontal=True,
            key="ppt_lib_category",
        )
        lib_uploads = st.file_uploader(
            "PPT 파일 선택 (.pptx, 여러 개 가능)",
            type=["pptx"],
            accept_multiple_files=True,
            key="ppt_lib_uploader",
        )
        b_save, b_open, b_open_all = st.columns(3)
        with b_save:
            do_save = st.button(
                "자료 보관하기",
                type="primary",
                use_container_width=True,
                key="ppt_lib_save",
                disabled=not lib_uploads,
            )
        with b_open:
            if st.button("이 폴더 열기", use_container_width=True, key="ppt_lib_open_cat"):
                ppt_library.open_folder(cat_label)
                st.toast(f"{ppt_library.CATEGORIES[cat_label][0]} 폴더를 열었습니다.")
        with b_open_all:
            if st.button("보관함 전체 열기", use_container_width=True, key="ppt_lib_open_root"):
                ppt_library.open_folder(None)
                st.toast("PPT 보관함 폴더를 열었습니다.")

        if do_save and lib_uploads:
            saved = []
            for f in lib_uploads:
                path = ppt_library.save_upload(cat_label, f.name, f.getvalue())
                saved.append(path.name)
            st.success(f"{len(saved)}개 보관: " + ", ".join(saved))
            st.rerun()

        stored = ppt_library.list_files()
        if not stored:
            st.caption("아직 보관된 PPT가 없습니다. 위에서 파일을 올려 「자료 보관하기」를 누르세요.")
        else:
            st.markdown(f"**보관 목록** · {len(stored)}개")
            for cat_key, path in stored:
                label = ppt_library.CATEGORIES[cat_key][0]
                c1, c2, c3 = st.columns([5, 2, 1])
                with c1:
                    st.markdown(f"`{label}` · **{path.name}**")
                    st.caption(f"{path.stat().st_size // 1024} KB")
                with c2:
                    st.download_button(
                        "받기",
                        data=path.read_bytes(),
                        file_name=path.name,
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        use_container_width=True,
                        key=f"ppt_lib_dl_{cat_key}_{path.name}",
                    )
                with c3:
                    if st.button("삭제", use_container_width=True, key=f"ppt_lib_del_{cat_key}_{path.name}"):
                        if ppt_library.delete_file(path):
                            st.toast(f"삭제: {path.name}")
                            st.rerun()

    with st.expander("이번 주 사용할 PPT (순서대로)", expanded=True):
        st.caption(
            "그 주에 쓸 찬송 PPT만 골라 **순서**로 모아 둡니다. "
            "예배 마스터 PPT 생성 시 **손대지 않고 그대로** 삽입됩니다 "
            "(1~5번째→예배 준비 1~5곡, 6번째→찬양/기도, 7번째→찬송가, 8번째→감사/봉헌). "
            f"폴더: `{ppt_library.THIS_WEEK_DIR.relative_to(Path(__file__).resolve().parent)}`"
        )
        week_uploads = st.file_uploader(
            "이번 주 PPT 추가 (.pptx, 선택 순서대로 맨 뒤에 붙음)",
            type=["pptx"],
            accept_multiple_files=True,
            key="ppt_week_uploader",
        )
        w1, w2, w3 = st.columns(3)
        with w1:
            do_week = st.button(
                "순서에 추가",
                type="primary",
                use_container_width=True,
                key="ppt_week_add",
                disabled=not week_uploads,
            )
        with w2:
            if st.button("이번 주 폴더 열기", use_container_width=True, key="ppt_week_open"):
                ppt_library.open_folder("this_week")
                st.toast("이번 주 사용할 PPT 폴더를 열었습니다.")
        with w3:
            if st.button("이번 주 목록 비우기", use_container_width=True, key="ppt_week_clear"):
                n = ppt_library.clear_this_week()
                st.toast(f"{n}개 삭제했습니다.")
                st.rerun()

        if do_week and week_uploads:
            added = []
            for f in week_uploads:
                path = ppt_library.add_to_this_week(f.name, f.getvalue())
                added.append(ppt_library.this_week_label(path))
            st.success("추가됨: " + " → ".join(added))
            st.rerun()

        # Optional: pick from library into this week
        lib_for_week = ppt_library.list_files()
        if lib_for_week:
            pick_opts = {
                f"{ppt_library.CATEGORIES[k][0]} · {p.name}": str(p)
                for k, p in lib_for_week
            }
            picked = st.multiselect(
                "보관함에서 이번 주로 가져오기",
                options=list(pick_opts.keys()),
                key="ppt_week_from_lib",
            )
            if st.button("선택한 보관 자료를 이번 주 순서에 추가", use_container_width=True, key="ppt_week_from_lib_go"):
                for label in picked:
                    ppt_library.add_library_file_to_this_week(Path(pick_opts[label]))
                st.success(f"{len(picked)}개 추가")
                st.rerun()

        week_list = ppt_library.list_this_week()
        if not week_list:
            st.caption("아직 이번 주 목록이 비어 있습니다. PPT를 올려 「순서에 추가」하세요.")
        else:
            st.markdown(f"**이번 주 재생 순서** · {len(week_list)}개")
            for path in week_list:
                c1, c2, c3, c4, c5 = st.columns([5, 1, 1, 1, 1])
                with c1:
                    st.markdown(f"**{ppt_library.this_week_label(path)}**")
                    st.caption(f"{path.stat().st_size // 1024} KB")
                with c2:
                    if st.button("↑", use_container_width=True, key=f"ppt_week_up_{path.name}"):
                        ppt_library.move_this_week(path, -1)
                        st.rerun()
                with c3:
                    if st.button("↓", use_container_width=True, key=f"ppt_week_dn_{path.name}"):
                        ppt_library.move_this_week(path, 1)
                        st.rerun()
                with c4:
                    st.download_button(
                        "받기",
                        data=path.read_bytes(),
                        file_name=path.name,
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        use_container_width=True,
                        key=f"ppt_week_dl_{path.name}",
                    )
                with c5:
                    if st.button("삭제", use_container_width=True, key=f"ppt_week_del_{path.name}"):
                        ppt_library.remove_this_week(path)
                        st.rerun()

    tab_pdf, tab_pptx, tab_html = st.tabs(
        ["주보 PDF 미리보기", "예배 PPT 미리보기", "예배화면 HTML"]
    )
    with tab_pdf:
        if "pdf_file" in st.session_state:
            try:
                st.pdf(st.session_state["pdf_file"], height=520)
            except Exception:
                st.caption("다운로드한 PDF로 주보를 확인하세요.")
        else:
            st.caption("주보 PDF가 아직 없습니다. 위 버튼으로 생성해 주세요.")
    with tab_pptx:
        if "pptx_file" in st.session_state:
            try:
                slides = pptx_slide_previews(st.session_state["pptx_file"])
                st.caption(f"총 {len(slides)}장 · 찬송은 인트로만 (가사 슬라이드 없음)")
                for i, text in enumerate(slides, 1):
                    with st.expander(f"슬라이드 {i}", expanded=(i <= 3)):
                        st.text(text)
            except Exception as exc:
                st.caption(f"PPT 미리보기를 만들 수 없습니다: {exc}")
        else:
            st.caption("예배 PPT가 아직 없습니다. 위 버튼으로 생성해 주세요.")
    with tab_html:
        if "html_file" in st.session_state:
            try:
                from html_presentation import build_presentation_slides

                html_slides = build_presentation_slides(data, allow_remote=False)
                st.caption(
                    f"총 {len(html_slides)}장 · Streamlit 입력과 동일 · 찬송 인트로만 · "
                    "전체화면은 브라우저에서 열어 사용"
                )
                for i, slide in enumerate(html_slides, 1):
                    title = slide.get("title") or slide.get("header") or slide.get("type")
                    sub = slide.get("subtitle") or ""
                    with st.expander(f"화면 {i} · {title}", expanded=(i <= 3)):
                        st.write(f"**유형:** {slide.get('type', '')}")
                        if sub:
                            st.write(sub)
            except Exception as exc:
                st.caption(f"HTML 미리보기를 만들 수 없습니다: {exc}")
            live = st.session_state.get("html_live_path")
            if live:
                st.caption(f"로컬 파일: `{live}`")
            _render_device_share_panel()
        else:
            st.caption("예배화면 HTML이 아직 없습니다. 위 버튼으로 생성해 주세요.")


if __name__ == "__main__":
    main()
