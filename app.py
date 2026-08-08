"""Grace Worship — Fullerton Villa order of worship UI."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

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
    DEFAULT_APOSTLES_CREED,
    DEFAULT_BENEDICTION,
    DEFAULT_RESPONSIVE_READING,
    DEFAULT_SERVICE_TIME,
    DEFAULT_SERVICE_TITLE,
    DEFAULT_WORSHIP_PRAYER,
)
from hymn_lookup import lookup_hymn
from models import HymnEntry, WorshipData
from pdf_generator import bulletin_preview_text, generate_worship_pdf
from pptx_generator import generate_worship_pptx, scan_placeholders
from scripture_lookup import lookup_scripture, verses_to_body
from text_normalize import normalize_breaks, normalize_line_list

st.set_page_config(
    page_title="Fullerton Villa Worship Generator",
    page_icon="✝",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: "Noto Sans KR", "Malgun Gothic", sans-serif; }
    .main .block-container { padding-top: 1.1rem; padding-bottom: 3rem; max-width: 980px; }
    h1 { font-weight: 700 !important; letter-spacing: -0.02em; }
    .subtitle { color: #4a5560; margin-top: -0.5rem; margin-bottom: 1rem; }
    .bulletin-banner {
        background: linear-gradient(135deg, #fbf8f1 0%, #e7efe6 100%);
        border: 1px solid #b7c4b5; border-radius: 10px;
        padding: 0.85rem 1.05rem; margin: 0.25rem 0 0.85rem 0;
    }
    div[data-testid="stDownloadButton"] button {
        background-color: #3d5a40; color: #fff; font-weight: 600; border: none;
    }
    .order-step { font-weight: 700; color: #3d5a40; margin-top: 0.45rem; }
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
        "praise_num": "7",
        "praise_title": "",
        "apostles_creed": DEFAULT_APOSTLES_CREED,
        "responsive_title": "교독문",
        "responsive_body": DEFAULT_RESPONSIVE_READING,
        "hymn_num": "30",
        "hymn_title": "",
        "prayer_text": DEFAULT_WORSHIP_PRAYER,
        "prayer_leader": "",
        "scripture_reference_input": "히브리서 4:1-11",
        "scripture_text_area": "",
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
        "include_lyrics_ppt": True,
        "upload_parse_notes": [],
        "upload_raw_preview": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Apply pending widget values BEFORE any widgets are created
    pending = {
        "_p_praise_num": "praise_num",
        "_p_praise_title": "praise_title",
        "_p_hymn_num": "hymn_num",
        "_p_hymn_title": "hymn_title",
        "_p_response_num": "response_num",
        "_p_response_title": "response_title",
        "_p_offering_num": "offering_num",
        "_p_offering_title": "offering_title",
        "_pending_scripture_ref": "scripture_reference_input",
        "_pending_scripture_body": "scripture_text_area",
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
            # Seed hymn lyric caches via local lookup
            if key.endswith("_num") and value:
                from hymn_lookup import lookup_hymn as _lh

                hit = _lh(str(value), allow_remote=False)
                if hit and hit.lyrics:
                    st.session_state[f"lyrics_cache_{key}"] = list(hit.lyrics)
                    title_key = key.replace("_num", "_title")
                    if title_key in st.session_state and not st.session_state.get(title_key):
                        st.session_state[title_key] = hit.title
        if plan:
            st.session_state["page_plan"] = plan


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


def _hymn_from_keys(num_key: str, title_key: str, *, allow_remote: bool) -> HymnEntry:
    num = normalize_breaks(st.session_state.get(num_key) or "").strip()
    title = normalize_breaks(st.session_state.get(title_key) or "").strip()
    cached = normalize_line_list(st.session_state.get(f"lyrics_cache_{num_key}") or [])
    if not (num or title):
        return HymnEntry()
    result = lookup_hymn(num or title, title, allow_remote=allow_remote)
    if result:
        lyrics = normalize_line_list(result.lyrics or cached or [])
        # Prefer fuller of lookup vs cache
        if cached and len(cached) > len(lyrics):
            lyrics = cached
        entry = HymnEntry(
            number=f"{result.number}장" if result.number else num,
            title=result.title or title,
            lyrics=lyrics,
            include_lyrics=True,
        )
    else:
        entry = HymnEntry(number=num, title=title, lyrics=list(cached), include_lyrics=True)
    if entry.lyrics:
        st.session_state[f"lyrics_cache_{num_key}"] = entry.lyrics
    elif cached:
        entry.lyrics = list(cached)
    return entry


def _build_worship_data(service_date, *, allow_remote: bool, force_lyrics: bool = True) -> WorshipData:
    body = normalize_breaks(st.session_state.get("scripture_text_area") or "").strip()
    ref = normalize_breaks(st.session_state.get("scripture_reference_input") or "").strip()
    if ref:
        result = lookup_scripture(ref, allow_remote=allow_remote)
        if result.found and result.verses:
            full = normalize_breaks(verses_to_body(result.verses))
            # Always prefer the complete looked-up range over a short/manual stub
            if not body or len(full) >= len(body):
                body = full
            ref = result.reference or ref

    data = WorshipData(
        church_name_en=(st.session_state.get("church_en") or CHURCH_NAME_EN).strip(),
        church_name_ko=(st.session_state.get("church_ko") or CHURCH_NAME_KO).strip(),
        service_title=(st.session_state.get("service_title") or DEFAULT_SERVICE_TITLE).strip(),
        date=service_date.strftime("%Y년 %m월 %d일"),
        service_time=(st.session_state.get("service_time") or DEFAULT_SERVICE_TIME).strip(),
        preacher=(st.session_state.get("preacher") or "").strip(),
        praise_hymn=_hymn_from_keys("praise_num", "praise_title", allow_remote=allow_remote),
        apostles_creed=(st.session_state.get("apostles_creed") or "").strip(),
        responsive_reading_title=(st.session_state.get("responsive_title") or "").strip(),
        responsive_reading=(st.session_state.get("responsive_body") or "").strip(),
        hymn=_hymn_from_keys("hymn_num", "hymn_title", allow_remote=allow_remote),
        worship_prayer=(st.session_state.get("prayer_text") or "").strip(),
        worship_prayer_leader=(st.session_state.get("prayer_leader") or "").strip(),
        scripture_reference=ref,
        scripture_text=body,
        response_hymn=_hymn_from_keys("response_num", "response_title", allow_remote=allow_remote),
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


def _hymn_inputs(label: str, num_key: str, title_key: str, fetch_key: str, allow_remote: bool):
    st.markdown(f'<p class="order-step">{label}</p>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.1, 3.2, 1.2])
    with c1:
        st.text_input("장번호", key=num_key, placeholder="예: 7")
    with c2:
        st.text_input("제목", key=title_key, placeholder="자동 입력 / 직접 수정")
    with c3:
        st.write("")
        st.write("")
        if st.button("가사 불러오기", key=fetch_key, use_container_width=True):
            h = _hymn_from_keys(num_key, title_key, allow_remote=allow_remote)
            st.session_state[f"_p_{num_key}"] = h.number
            st.session_state[f"_p_{title_key}"] = h.title
            if h.lyrics:
                st.session_state[f"lyrics_cache_{num_key}"] = h.lyrics
            st.rerun()
    h = _hymn_from_keys(num_key, title_key, allow_remote=False)
    if h.number or h.title:
        st.caption(f"연동: **{hymn_label(h) or '—'}** · 가사 {len(h.lyrics)}줄")


def main():
    _init_state()

    st.title("Fullerton Villa Worship Generator")
    st.markdown(
        '<p class="subtitle">플로튼 빌라 교회 전통 예배 순서 · 인쇄용 주보 PDF · 시니어 PPT</p>',
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("예배 순서")
        st.markdown(
            "1. 찬양과 기도  \n2. 사도신경  \n3. 교독문  \n4. 찬송가  \n"
            "5. 예배의 기도  \n6. 오늘의 말씀  \n7. 찬양  \n8. 생명의 말씀  \n"
            "9. 감사와 봉헌  \n10. 축도"
        )
        allow_remote = st.toggle("온라인 보조 검색", value=True)
        st.divider()
        st.caption("Fullerton Villa Community Church")

    # ===== TOP: Custom bulletin upload & auto-template parser =====
    st.markdown(
        '<div class="bulletin-banner">'
        "<strong>주보 / 예배 순서 업로드</strong> — 다중 페이지 PDF · 여러 장의 사진 · 텍스트를 올리면 "
        "페이지별로 분석하고, 인쇄 주보·PPT 섹션에 매핑합니다."
        "</div>",
        unsafe_allow_html=True,
    )
    st.subheader("예배 순서 템플릿 자동 생성 (다중 페이지)")
    st.caption(
        "예배 순서 템플릿을 만들 수 있도록 현재의 주보나 예배 순서를 업로드해 주세요. "
        "여러 파일을 올리면 순서대로 Page 1, 2… 로 처리됩니다."
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
        placeholder="예:\n1. 찬양과 기도  7장\n…\n\n\n--- Page 2 ---\n오늘의 말씀 히브리서 4:1-11\n…",
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
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Church (EN)", key="church_en")
        st.text_input("교회명 (KO)", key="church_ko")
        st.text_input("예배 제목", key="service_title")
    with c2:
        service_date = st.date_input("날짜", value=date.today(), key="service_date")
        st.text_input("예배 시간", key="service_time")
        st.text_input("설교자", key="preacher")

    # ===== PDF TOP (reads session state; syncs as fields below update) =====
    st.markdown(
        '<div class="bulletin-banner">'
        "<strong>인쇄용 주일 주보 PDF</strong> — PPT와 분리된 "
        "A4 인쇄용 주보입니다. 교회명·예배명·날짜·정돈된 예배 순서가 "
        "한 흐름으로 배치되며, 슬라이드처럼 쪼개지거나 "
        "<code>_x000B_</code> 줄바꿈 코드가 보이지 않습니다."
        "</div>",
        unsafe_allow_html=True,
    )
    st.subheader("인쇄용 주일 주보 PDF")

    data = _build_worship_data(service_date, allow_remote=allow_remote, force_lyrics=True)

    with st.expander("주보 내용 미리보기", expanded=True):
        st.text(bulletin_preview_text(data))

    pc1, pc2 = st.columns([2, 1])
    with pc1:
        make_pdf = st.button("주보 PDF 생성 / 새로고침", type="primary", use_container_width=True, key="make_pdf")
    with pc2:
        auto_pdf = st.toggle("자동 생성", value=True, key="auto_pdf")

    if make_pdf or auto_pdf:
        try:
            st.session_state["pdf_file"] = generate_worship_pdf(data, allow_remote=allow_remote).getvalue()
            st.session_state["pdf_name"] = f"bulletin_{service_date.strftime('%Y%m%d')}.pdf"
            if make_pdf:
                st.success("A4 인쇄용 주보 PDF 준비 완료.")
        except Exception as exc:
            st.error(f"PDF 오류: {exc}")

    if "pdf_file" in st.session_state:
        st.download_button(
            "⬇ 인쇄용 주보 PDF 다운로드",
            data=st.session_state["pdf_file"],
            file_name=st.session_state.get("pdf_name", "bulletin.pdf"),
            mime="application/pdf",
            use_container_width=True,
            key="dl_pdf",
        )
        try:
            st.pdf(st.session_state["pdf_file"], height=520)
        except Exception:
            st.caption("다운로드한 PDF로 주보를 확인하세요.")

    st.markdown("---")

    # ===== Order 1–10 =====
    st.subheader("예배 순서 입력 (1–10)")

    _hymn_inputs("1. 찬양과 기도 (Praise & Prayer)", "praise_num", "praise_title", "fetch_praise", allow_remote)

    st.markdown('<p class="order-step">2. 사도신경</p>', unsafe_allow_html=True)
    st.text_area("사도신경 전문", key="apostles_creed", height=150)

    st.markdown('<p class="order-step">3. 교독문</p>', unsafe_allow_html=True)
    st.text_input("교독문 제목/번호", key="responsive_title")
    st.text_area("교독문 본문 (`인도자:` / `회중:`)", key="responsive_body", height=140)

    _hymn_inputs("4. 찬송가 (Hymn)", "hymn_num", "hymn_title", "fetch_hymn", allow_remote)

    st.markdown('<p class="order-step">5. 예배의 기도</p>', unsafe_allow_html=True)
    p1, p2 = st.columns([2.2, 1])
    with p1:
        st.text_area("기도문", key="prayer_text", height=110)
    with p2:
        st.text_input("기도 인도", key="prayer_leader", placeholder="인도자")

    st.markdown('<p class="order-step">6. 오늘의 말씀</p>', unsafe_allow_html=True)
    sc1, sc2 = st.columns([3, 1])
    with sc1:
        st.text_input("성경 구절", key="scripture_reference_input", placeholder="예: 히브리서 4장 1-11절")
    with sc2:
        st.write("")
        st.write("")
        if st.button("본문 불러오기", use_container_width=True, key="fetch_scripture"):
            result = lookup_scripture(
                st.session_state.get("scripture_reference_input", ""),
                allow_remote=allow_remote,
            )
            st.session_state.resolved_scripture = {
                "reference": result.reference,
                "found": result.found,
                "source": result.source,
            }
            if result.reference:
                st.session_state["_pending_scripture_ref"] = result.reference
            if result.verses:
                st.session_state["_pending_scripture_body"] = normalize_breaks(verses_to_body(result.verses))
            st.rerun()
    resolved = st.session_state.get("resolved_scripture")
    if resolved and resolved.get("found"):
        st.success(f"불러옴: **{resolved['reference']}** · `{resolved['source']}`")
    st.text_area("성경 본문", key="scripture_text_area", height=150)

    _hymn_inputs("7. 찬양 (Hymn of Response)", "response_num", "response_title", "fetch_response", allow_remote)

    st.markdown('<p class="order-step">8. 생명의 말씀</p>', unsafe_allow_html=True)
    s1, s2 = st.columns(2)
    with s1:
        st.text_input("설교 제목", key="sermon_title", placeholder="생명의 말씀 제목")
    with s2:
        st.text_input("부제", key="sermon_subtitle")

    _hymn_inputs("9. 감사와 봉헌 (Offering)", "offering_num", "offering_title", "fetch_offering", allow_remote)

    st.markdown('<p class="order-step">10. 축도</p>', unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        st.text_input("축도", key="benediction")
    with b2:
        st.text_input("안내", key="closing_note")

    st.markdown('<p class="order-step">소식 · 광고 (다중 페이지)</p>', unsafe_allow_html=True)
    st.text_area(
        "주보 2면 이후 소식/광고 본문",
        key="announcements",
        height=120,
        placeholder="업로드한 광고·소식 페이지가 여기로 매핑됩니다.",
    )

    st.markdown("---")
    st.subheader("예배 PPT — 마스터 템플릿 주입")
    st.markdown(
        '<div class="bulletin-banner">'
        "<strong>Step 1.</strong> Master Worship PPT (.pptx)를 업로드하세요 "
        "(샘플: <code>templates/master_worship.pptx</code>). "
        "슬라이드에 <code>{{HYMN_1}}</code>, <code>{{HYMN_1_LYRICS}}</code>, "
        "<code>{{RESPONSIVE}}</code>, <code>{{BIBLE_TEXT}}</code>, "
        "<code>{{SERMON_TITLE}}</code>, <code>{{HYMN_2}}</code> "
        "같은 플레이스홀더를 넣어 두면 "
        "<strong>Step 2</strong>에서 입력한 주간 내용만 그대로 치환됩니다. "
        "레이아웃·글꼴·배경·순서는 절대 바꾸지 않습니다."
        "</div>",
        unsafe_allow_html=True,
    )

    master_upload = st.file_uploader(
        "Master Worship PPT 업로드 (.pptx)",
        type=["pptx"],
        key="master_pptx_uploader",
        help="예: {{HYMN_1}}, {{HYMN_1_LYRICS}}, {{RESPONSIVE}}, {{BIBLE_TEXT}}, "
        "{{SERMON_TITLE}}, {{HYMN_2}}. "
        "악보 이미지는 도형 이름을 HYMN_1_SCORE_IMAGE 로 두고 data/hymn_scores/7.png 를 넣으면 주입됩니다.",
    )
    if master_upload is not None:
        st.session_state["master_pptx_bytes"] = master_upload.getvalue()
        st.session_state["master_pptx_name"] = master_upload.name
        try:
            found = scan_placeholders(st.session_state["master_pptx_bytes"])
            st.session_state["master_pptx_placeholders"] = found
        except Exception as exc:
            st.session_state["master_pptx_placeholders"] = []
            st.warning(f"마스터 파일을 읽는 중 문제가 있었습니다: {exc}")

    if st.session_state.get("master_pptx_bytes"):
        st.success(
            f"마스터 준비됨: **{st.session_state.get('master_pptx_name', 'master.pptx')}** "
            f"({len(st.session_state['master_pptx_bytes']) // 1024} KB)"
        )
        placeholders = st.session_state.get("master_pptx_placeholders") or []
        if placeholders:
            with st.expander("감지된 플레이스홀더", expanded=False):
                st.code(", ".join("{{" + p + "}}" for p in placeholders))
        else:
            st.caption(
                "플레이스홀더가 보이지 않습니다. PPT 텍스트 상자에 "
                "`{{SERMON_TITLE}}` 형식으로 넣어 주세요."
            )
    else:
        st.info("먼저 Master Worship PPT 파일을 업로드해 주세요.")

    st.checkbox("가사 토큰도 채우기 ({{HYMN_1_LYRICS}} 등)", key="include_lyrics_ppt")
    make_pptx = st.button(
        "주간 내용 주입 → PPT 만들기",
        type="primary",
        use_container_width=True,
        key="make_pptx",
        disabled=not st.session_state.get("master_pptx_bytes"),
    )
    if make_pptx:
        ppt_data = _build_worship_data(
            service_date,
            allow_remote=allow_remote,
            force_lyrics=bool(st.session_state.get("include_lyrics_ppt", True)),
        )
        ppt_data.include_hymn_lyrics = bool(st.session_state.get("include_lyrics_ppt", True))
        try:
            out = generate_worship_pptx(
                ppt_data,
                master=st.session_state["master_pptx_bytes"],
                allow_remote=allow_remote,
            )
            st.session_state["pptx_file"] = out.getvalue()
            base = Path(st.session_state.get("master_pptx_name") or "worship").stem
            st.session_state["pptx_name"] = f"{base}_{service_date.strftime('%Y%m%d')}.pptx"
            st.success("마스터 파일에 주간 내용을 주입했습니다. 디자인·순서는 원본 그대로입니다.")
        except Exception as exc:
            st.error(f"PPT 주입 오류: {exc}")

    if "pptx_file" in st.session_state:
        st.download_button(
            "⬇ 완성된 PowerPoint 다운로드 (.pptx)",
            data=st.session_state["pptx_file"],
            file_name=st.session_state.get("pptx_name", "worship.pptx"),
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            use_container_width=True,
            key="dl_pptx",
        )


if __name__ == "__main__":
    main()
