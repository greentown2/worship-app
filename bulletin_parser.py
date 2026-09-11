"""Extract and parse worship-order text from uploaded bulletins (PDF / image / text)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

from hymn_lookup import lookup_hymn
from responsive_lookup import (
    format_responsive_label,
    lookup_responsive,
    parse_responsive_number,
)
from scripture_lookup import lookup_scripture, verses_to_body
from text_normalize import normalize_breaks

# --- Text extraction ---------------------------------------------------------


def extract_text_from_upload(filename: str, raw: bytes) -> tuple[str, str]:
    """
    Return (extracted_text, method_note).
    method_note describes how text was obtained (pdf / ocr / plain / partial).
    """
    name = (filename or "").lower()
    if name.endswith((".txt", ".md", ".csv")):
        for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
            try:
                return normalize_breaks(raw.decode(enc)), "text"
            except UnicodeDecodeError:
                continue
        return normalize_breaks(raw.decode("utf-8", errors="replace")), "text(lossy)"

    if name.endswith(".pdf"):
        text, note = _extract_pdf(raw)
        return normalize_breaks(text), note

    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
        text, note = _extract_image(raw)
        return normalize_breaks(text), note

    # Unknown — try UTF-8 text
    try:
        return normalize_breaks(raw.decode("utf-8")), "text"
    except UnicodeDecodeError:
        return "", "unsupported"


def _extract_pdf(raw: bytes) -> tuple[str, str]:
    text_parts: list[str] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        for page in reader.pages:
            text_parts.append(page.extract_text() or "")
    except Exception as exc:
        text_parts = []
        pdf_err = str(exc)
    else:
        pdf_err = ""

    joined = "\n".join(text_parts).strip()
    # If almost empty, try OCR via rendering first page with pypdfium2 or skip
    if len(re.sub(r"\s+", "", joined)) < 40:
        ocr_text, ocr_note = _ocr_pdf_pages(raw)
        if ocr_text.strip():
            return ocr_text, f"pdf-ocr ({ocr_note})"
        if joined:
            return joined, "pdf(sparse)"
        return "", f"pdf-failed ({pdf_err or ocr_note})"
    return joined, "pdf"


def _ocr_pdf_pages(raw: bytes) -> tuple[str, str]:
    """Best-effort OCR for image-only PDFs using pdf2image if available."""
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        return "", "pdf2image not installed"

    try:
        images = convert_from_bytes(raw, dpi=200, first_page=1, last_page=2)
    except Exception as exc:
        return "", f"pdf2image failed: {exc}"

    chunks = []
    for img in images:
        t, note = _ocr_pil(img)
        if t:
            chunks.append(t)
    return "\n".join(chunks), note if chunks else "no ocr text"


def _extract_image(raw: bytes) -> tuple[str, str]:
    try:
        from PIL import Image
    except ImportError:
        return "", "Pillow not installed"

    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
    except Exception as exc:
        return "", f"image open failed: {exc}"

    return _ocr_pil(img)


def _ocr_pil(img) -> tuple[str, str]:
    try:
        import pytesseract
    except ImportError:
        return "", "pytesseract not installed — install Tesseract OCR for image bulletins"

    # Common Windows install path
    from pathlib import Path

    candidates = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for c in candidates:
        if c.exists():
            pytesseract.pytesseract.tesseract_cmd = str(c)
            break

    langs = []
    try:
        available = set(pytesseract.get_languages(config=""))
        if "kor" in available and "eng" in available:
            langs = ["kor+eng"]
        elif "kor" in available:
            langs = ["kor"]
        elif "eng" in available:
            langs = ["eng"]
        else:
            langs = ["eng"]
    except Exception:
        langs = ["kor+eng", "kor", "eng"]

    last_err = ""
    for lang in langs:
        try:
            text = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
            if text and text.strip():
                return text.strip(), f"ocr:{lang}"
        except Exception as exc:
            last_err = str(exc)
            continue
    return "", f"ocr-failed ({last_err})"


# --- Worship order parsing ---------------------------------------------------

@dataclass
class ParsedBulletin:
    church_name_en: str = ""
    church_name_ko: str = ""
    service_title: str = ""
    service_time: str = ""
    preacher: str = ""
    prep_hymn_1_num: str = ""
    prep_hymn_1_title: str = ""
    prep_hymn_2_num: str = ""
    prep_hymn_2_title: str = ""
    prep_hymn_3_num: str = ""
    prep_hymn_3_title: str = ""
    prep_hymn_4_num: str = ""
    prep_hymn_4_title: str = ""
    prep_hymn_5_num: str = ""
    prep_hymn_5_title: str = ""
    praise_num: str = ""
    praise_title: str = ""
    responsive_num: str = ""
    responsive_title: str = ""
    responsive_body: str = ""
    hymn_num: str = ""
    hymn_title: str = ""
    prayer_leader: str = ""
    prayer_text: str = ""
    choir_anthem_title: str = ""
    scripture_reference: str = ""
    scripture_text: str = ""
    response_num: str = ""
    response_title: str = ""
    sermon_title: str = ""
    sermon_subtitle: str = ""
    offering_num: str = ""
    offering_title: str = ""
    benediction: str = ""
    raw_text: str = ""
    method: str = ""
    notes: list[str] = field(default_factory=list)
    field_map: dict[str, str] = field(default_factory=dict)


_HYMN_RE = re.compile(
    r"(?:찬송(?:가)?|찬양|봉헌(?:찬송)?|송영|기도)?\s*"
    r"(?:[#No\.]*)?\s*"
    r"(\d{1,3})\s*장"
    r"(?:\s*[·.\-]?\s*([가-힣A-Za-z0-9][가-힣A-Za-z0-9\s]{1,40}))?",
    re.IGNORECASE,
)
_HYMN_INLINE = re.compile(r"(\d{1,3})\s*장(?:\s+([가-힣][가-힣\s]{1,30}))?")

_SCRIPTURE_RE = re.compile(
    r"(?<![가-힣])("
    r"창세기|출애굽기|레위기|민수기|신명기|여호수아|사사기|룻기|"
    r"사무엘상|사무엘하|열왕기상|열왕기하|역대상|역대하|에스라|느헤미야|에스더|"
    r"욥기|시편|잠언|전도서|아가|이사야|예레미야|예레미야애가|에스겔|다니엘|"
    r"호세아|요엘|아모스|오바댜|요나|미가|나훔|하박국|스바냐|학개|스가랴|말라기|"
    r"마태복음|마가복음|누가복음|요한복음|사도행전|로마서|고린도전서|고린도후서|"
    r"갈라디아서|에베소서|빌립보서|골로새서|데살로니가전서|데살로니가후서|"
    r"디모데전서|디모데후서|디도서|빌레몬서|히브리서|야고보서|베드로전서|베드로후서|"
    r"요한일서|요한이서|요한삼서|유다서|요한계시록|계시록|"
    r"창|출|레|민|신|수|삿|룻|삼상|삼하|왕상|왕하|대상|대하|스|느|에|욥|시|잠|"
    r"사|렘|겔|단|호|욜|암|옵|욘|미|나|합|습|학|슥|말|마|막|눅|요|행|롬|고전|고후|갈|엡|빌|골|"
    r"살전|살후|딤전|딤후|딛|몬|히|약|벧전|벧후|요일|요이|요삼|유|계"
    # NOTE: omit bare '전' / '아' — too many false positives (오전, 아멘)
    r")\s*"
    r"(?:"
    r"(\d+)\s*장(?:\s*(\d+)\s*(?:[-~–—]\s*(\d+))?\s*절)?"
    r"|"
    r"(\d+)\s*[:：]\s*(\d+)(?:\s*[-~–—]\s*(\d+))?"
    r"|"
    r"(\d+)\s*편"
    r")"
)

_TIME_RE = re.compile(r"((?:오전|오후)\s*\d{1,2}\s*:\s*\d{2}|\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?)")
_CHURCH_KO_RE = re.compile(r"([가-힣A-Za-z0-9 ]{2,40}교회)")
_ORDER_LINE_RE = re.compile(
    r"^\s*(?:\(?\s*)?(\d{1,2})\s*[.)、．:\-]\s*(.+)$"
)


def _clean_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _section_blocks(text: str) -> list[tuple[str, str]]:
    """Split text into (heading, body) using numbered / keyword headings."""
    lines = [_clean_line(ln) for ln in text.replace("\r\n", "\n").split("\n")]
    lines = [ln for ln in lines if ln]

    keyword_heads = [
        "예배 준비",
        "준비찬양",
        "찬양과 기도",
        "사도신경",
        "교독문",
        "감사와 봉헌",
        "생명의 말씀",
        "오늘의 말씀",
        "예배의 기도",
        "성가대",
        "성경봉독",
        "찬송가",
        "찬송",
        "축도",
        "설교",
        "봉헌",
        "찬양",
        "기도",
        "말씀",
        "order of worship",
        "예배 순서",
    ]

    blocks: list[tuple[str, list[str]]] = []
    current_h = "header"
    current_b: list[str] = []

    def flush():
        nonlocal current_h, current_b
        if current_b or (current_h and current_h != "header"):
            blocks.append((current_h, list(current_b)))
        current_b = []

    for ln in lines:
        m = _ORDER_LINE_RE.match(ln)
        matched_kw = ""
        rest = ln
        if m:
            rest = m.group(2)

        for kw in keyword_heads:
            if rest.lower().startswith(kw.lower()) or rest.startswith(kw):
                matched_kw = kw
                break

        if matched_kw:
            flush()
            current_h = rest  # keep full rest for hymn/scripture on same line
            # Also keep same-line remainder after keyword as body seed
            remainder = rest[len(matched_kw) :].strip(" ·:-")
            if remainder:
                current_b.append(remainder)
            elif m:
                # numbered heading with only keyword — still record empty body section
                pass
        else:
            current_b.append(ln)
    flush()
    return [(h, "\n".join(b)) for h, b in blocks]


def _first_hymn(text: str) -> tuple[str, str]:
    # Prefer hymn numbers that are NOT part of a scripture "N장 M절" pattern
    text_wo_scripture = _SCRIPTURE_RE.sub(" ", text)
    m = _HYMN_INLINE.search(text_wo_scripture)
    if not m:
        # fall back: any N장 not followed by 절
        for m2 in _HYMN_INLINE.finditer(text):
            after = text[m2.end() : m2.end() + 4]
            if after.strip().startswith("절"):
                continue
            m = m2
            break
    if not m:
        return "", ""
    num = m.group(1)
    title = _clean_line((m.group(2) or "").replace("\n", " "))
    title = re.sub(r"^[·.\-:\s]+", "", title)
    title = re.split(r"\s{2,}|\d+\s*[.)]", title)[0].strip()
    if not title:
        hit = lookup_hymn(num, allow_remote=False)
        title = hit.title if hit else ""
    return f"{num}장", title


def _hymns_from_text(text: str, limit: int = 5) -> list[tuple[str, str]]:
    """Collect unique hymn numbers from a block (skips scripture 'N장 M절')."""
    text_wo_scripture = _SCRIPTURE_RE.sub(" ", text or "")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for m in _HYMN_INLINE.finditer(text_wo_scripture):
        num = m.group(1)
        if num in seen:
            continue
        after = text_wo_scripture[m.end() : m.end() + 4]
        if after.strip().startswith("절"):
            continue
        title = _clean_line((m.group(2) or "").replace("\n", " "))
        title = re.sub(r"^[·.\-:\s]+", "", title)
        title = re.split(r"\s{2,}|\d+\s*[.)]", title)[0].strip()
        if not title:
            hit = lookup_hymn(num, allow_remote=False)
            title = hit.title if hit else ""
        seen.add(num)
        out.append((f"{num}장", title))
        if len(out) >= limit:
            break
    if out:
        return out
    first = _first_hymn(text)
    return [first] if first[0] else []


def _first_scripture(text: str) -> str:
    # Skip obvious time strings
    text_wo_time = _TIME_RE.sub(" ", text)
    m = _SCRIPTURE_RE.search(text_wo_time)
    if not m:
        return ""
    book = m.group(1)
    if m.group(2):  # N장 M-K절
        ch, vs, ve = m.group(2), m.group(3), m.group(4)
        if vs and ve:
            return f"{book} {ch}:{vs}-{ve}"
        if vs:
            return f"{book} {ch}:{vs}"
        return f"{book} {ch}장"
    if m.group(5):  # N:M-K
        ch, vs, ve = m.group(5), m.group(6), m.group(7)
        # Reject clock times like 11:00
        if vs is not None and ve is None and int(vs) == 0:
            return ""
        if ve:
            return f"{book} {ch}:{vs}-{ve}"
        return f"{book} {ch}:{vs}"
    if m.group(8):
        return f"{book} {m.group(8)}편"
    return ""


def _classify_heading(head: str) -> str:
    h = head.lower()
    if "사도신경" in head:
        return "creed"
    if "교독" in head:
        return "responsive"
    if "예배 준비" in head or "준비찬양" in head or "prelude" in h:
        return "prep"
    if "찬양과 기도" in head or ("praise" in h and "prayer" in h):
        return "praise"
    if "봉헌" in head or "감사와" in head or "offering" in h:
        return "offering"
    if "생명의 말씀" in head or "설교" in head or "sermon" in h:
        return "sermon"
    if "오늘의 말씀" in head or "성경봉독" in head or "성경" in head or "scripture" in h:
        return "scripture"
    if "예배의 기도" in head:
        return "prayer"
    if "성가대" in head or "choir" in h:
        return "choir"
    if "축도" in head or "benediction" in h:
        return "benediction"
    # "7. 찬양 …" response hymn — after praise/prayer already handled
    if re.match(r"^찬양\b", head.strip()) or "response" in h:
        return "response"
    if "찬송" in head or "hymn" in h:
        return "hymn"
    if "기도" in head:
        return "prayer"
    return "other"


def parse_bulletin_text(text: str, *, method: str = "") -> ParsedBulletin:
    result = ParsedBulletin(raw_text=text, method=method)
    if not text or not text.strip():
        result.notes.append("추출된 텍스트가 없습니다.")
        return result

    lines = [_clean_line(ln) for ln in text.replace("\r\n", "\n").split("\n") if _clean_line(ln)]
    header = "\n".join(lines[:12])

    # Church names
    for ln in lines[:15]:
        if re.search(r"[A-Za-z]{4,}", ln) and ("church" in ln.lower() or "community" in ln.lower()):
            result.church_name_en = ln
            break
    ko_m = _CHURCH_KO_RE.search(header)
    if ko_m:
        result.church_name_ko = ko_m.group(1).strip()

    if re.search(r"주일|예배|worship|service", header, re.I):
        for ln in lines[:10]:
            if "예배" in ln and len(ln) < 30:
                result.service_title = ln
                break

    tm = _TIME_RE.search(header)
    if tm:
        result.service_time = tm.group(1).strip()

    for ln in lines[:20]:
        if "설교" in ln:
            result.preacher = re.sub(r"^.*설교\s*[:：]?\s*", "", ln).strip()
            break

    blocks = _section_blocks(text)
    hymn_slots_used = {
        "prep": False,
        "praise": False,
        "hymn": False,
        "response": False,
        "offering": False,
    }

    for head, body in blocks:
        kind = _classify_heading(head)
        combo = f"{head}\n{body}"

        if kind == "prep" and not hymn_slots_used["prep"]:
            found = _hymns_from_text(combo, limit=5)
            if found:
                result.prep_hymn_1_num, result.prep_hymn_1_title = found[0]
            if len(found) > 1:
                result.prep_hymn_2_num, result.prep_hymn_2_title = found[1]
            if len(found) > 2:
                result.prep_hymn_3_num, result.prep_hymn_3_title = found[2]
            if len(found) > 3:
                result.prep_hymn_4_num, result.prep_hymn_4_title = found[3]
            if len(found) > 4:
                result.prep_hymn_5_num, result.prep_hymn_5_title = found[4]
            hymn_slots_used["prep"] = True
            prep_note = " / ".join(
                f"{n} {t}".strip()
                for n, t in (
                    (result.prep_hymn_1_num, result.prep_hymn_1_title),
                    (result.prep_hymn_2_num, result.prep_hymn_2_title),
                    (result.prep_hymn_3_num, result.prep_hymn_3_title),
                    (result.prep_hymn_4_num, result.prep_hymn_4_title),
                    (result.prep_hymn_5_num, result.prep_hymn_5_title),
                )
                if n or t
            )
            result.notes.append(f"1. 예배 준비의 시간 ← {prep_note}".strip())
        elif kind == "praise" and not hymn_slots_used["praise"]:
            num, title = _first_hymn(combo)
            result.praise_num, result.praise_title = num, title
            hymn_slots_used["praise"] = True
            result.notes.append(f"2. 찬양과 기도 ← {num} {title}".strip())
        elif kind == "creed":
            result.notes.append("3. 사도신경 감지")
        elif kind == "responsive":
            result.responsive_title = head if "교독" in head else "교독문"
            # Keep responsive body if it has leader/congregation markers or length
            if "인도" in body or "회중" in body or len(body) > 40:
                result.responsive_body = body
            resp_n = parse_responsive_number(combo) or parse_responsive_number(head)
            if resp_n:
                result.responsive_num = str(resp_n)
            result.notes.append(
                f"4. 교독문 ← {result.responsive_num or ''} {result.responsive_title}".strip()
            )
        elif kind == "hymn" and not hymn_slots_used["hymn"]:
            num, title = _first_hymn(combo)
            result.hymn_num, result.hymn_title = num, title
            hymn_slots_used["hymn"] = True
            result.notes.append(f"5. 찬송가 ← {num} {title}".strip())
        elif kind == "prayer":
            if "인도" in head or re.search(r"[가-힣]{2,8}$", head):
                leader = re.sub(r".*기도\s*", "", head).strip(" ·-:")
                if leader and leader not in ("예배의", "예배"):
                    result.prayer_leader = leader
            if body and len(body) > 20:
                result.prayer_text = body
            result.notes.append("6. 예배의 기도 감지")
        elif kind == "choir":
            title = re.sub(r"^.*?성가대\s*(찬양)?\s*[:：-]?\s*", "", head).strip()
            if not title or title in ("성가대", "성가대 찬양"):
                title = body.split("\n")[0].strip() if body else ""
            result.choir_anthem_title = title[:80]
            result.notes.append(f"7. 성가대 찬양 ← {result.choir_anthem_title or '(제목 미확인)'}")
        elif kind == "scripture":
            ref = _first_scripture(combo) or _first_scripture(head)
            if ref:
                result.scripture_reference = ref
            # If body looks like verse text, keep it
            if re.search(r"^\d+\s+\S+", body, re.M) or len(body) > 60:
                result.scripture_text = body
            result.notes.append(f"8. 오늘의 말씀 ← {result.scripture_reference or '(구절 미확인)'}")
        elif kind == "response":
            # numbered order has no response hymn
            result.notes.append("응답 찬양 감지 (현재 순서에서는 사용하지 않음)")
        elif kind == "sermon":
            # Title often after colon or on same line
            title = re.sub(r"^(생명의 말씀|설교)\s*[:：-]?\s*", "", head).strip()
            if not title or title in ("생명의 말씀", "설교"):
                title = body.split("\n")[0].strip() if body else ""
            result.sermon_title = title[:80]
            result.notes.append(f"9. 생명의 말씀 ← {result.sermon_title or '(제목 미확인)'}")
        elif kind == "offering" and not hymn_slots_used["offering"]:
            num, title = _first_hymn(combo)
            result.offering_num, result.offering_title = num, title
            hymn_slots_used["offering"] = True
            result.notes.append(f"10. 감사와 봉헌 ← {num} {title}".strip())
        elif kind == "benediction":
            result.benediction = body.split("\n")[0][:60] if body else result.benediction
            result.notes.append("11. 축도 감지")

    # Fallback: collect hymns only from lines that mention 장 with worship context
    all_hymns = []
    for ln in lines:
        if "장" not in ln:
            continue
        if any(k in ln for k in ("절", "복음", "기서", "시편", "히브리", "창세기", "말씀")):
            # likely scripture line — skip unless also has 찬송/찬양/봉헌
            if not any(k in ln for k in ("찬송", "찬양", "봉헌")):
                continue
        if not any(k in ln for k in ("찬송", "찬양", "봉헌", "기도")):
            continue
        num, title = _first_hymn(ln)
        if num:
            all_hymns.append((num, title))
    seen = set()
    unique = []
    for n, t in all_hymns:
        if n not in seen:
            seen.add(n)
            unique.append((n, t))

    slots = [
        ("praise_num", "praise_title"),
        ("hymn_num", "hymn_title"),
        ("offering_num", "offering_title"),
    ]
    ui = 0
    for attr_n, attr_t in slots:
        if not getattr(result, attr_n) and ui < len(unique):
            setattr(result, attr_n, unique[ui][0])
            setattr(result, attr_t, unique[ui][1])
            result.notes.append(f"자동 배치 찬송 → {attr_n}: {unique[ui][0]}")
            ui += 1

    if not result.scripture_reference:
        ref = _first_scripture(text)
        if ref:
            result.scripture_reference = ref
            result.notes.append(f"성경 구절 자동 감지 ← {ref}")

    _enrich_parsed_lookups(result)

    result.field_map = result_to_session_updates(result)
    return result


def _enrich_parsed_lookups(result: ParsedBulletin) -> None:
    """Fill titles/bodies from local hymn · 교독문 · scripture indexes by number/ref."""
    for num_attr, title_attr in (
        ("prep_hymn_1_num", "prep_hymn_1_title"),
        ("prep_hymn_2_num", "prep_hymn_2_title"),
        ("prep_hymn_3_num", "prep_hymn_3_title"),
        ("prep_hymn_4_num", "prep_hymn_4_title"),
        ("prep_hymn_5_num", "prep_hymn_5_title"),
        ("praise_num", "praise_title"),
        ("hymn_num", "hymn_title"),
        ("offering_num", "offering_title"),
    ):
        num = (getattr(result, num_attr) or "").strip()
        title = (getattr(result, title_attr) or "").strip()
        if not num:
            continue
        hit = lookup_hymn(num, title, allow_remote=False)
        if hit:
            if hit.number:
                setattr(result, num_attr, str(hit.number))
            if hit.title and (not title or title == num):
                setattr(result, title_attr, hit.title)
                result.notes.append(f"찬송 자동 제목 ← {hit.number}장 {hit.title}")

    resp_key = (result.responsive_num or result.responsive_title or "").strip()
    if not resp_key and result.responsive_body:
        resp_key = result.responsive_title
    if resp_key or (result.responsive_title or "").strip():
        key = resp_key or result.responsive_title
        hit = lookup_responsive(key, allow_remote=False)
        body = (result.responsive_body or "").strip()
        incomplete = (not body) or not ("인도자" in body and "회중" in body)
        if hit.found and hit.body and (incomplete or not result.responsive_title):
            result.responsive_num = str(hit.number) if hit.number else result.responsive_num
            result.responsive_title = format_responsive_label(hit.number, hit.title)
            if incomplete:
                result.responsive_body = normalize_breaks(hit.body)
            result.notes.append(
                f"교독문 자동 불러옴 ← {result.responsive_num}번 · {hit.title}"
            )

    if result.scripture_reference and not (result.scripture_text or "").strip():
        sc = lookup_scripture(result.scripture_reference, allow_remote=False)
        if sc.found and sc.verses:
            result.scripture_text = normalize_breaks(verses_to_body(sc.verses))
            # Keep parseable ref in the form (no translation label suffix)
            from scripture_lookup import parse_scripture_reference

            parsed = parse_scripture_reference(result.scripture_reference)
            result.scripture_reference = (
                parsed.display if parsed else re.sub(
                    r"\s*\(개역개정\)\s*$", "", sc.reference or result.scripture_reference
                ).strip()
            )
            result.notes.append(f"성경 본문 자동 불러옴 ← {result.scripture_reference}")
    elif result.scripture_reference:
        # Prefer clean local 개역개정 when OCR body is thin
        body = (result.scripture_text or "").strip()
        if body and len(body) < 40:
            sc = lookup_scripture(result.scripture_reference, allow_remote=False)
            if sc.found and sc.verses:
                result.scripture_text = normalize_breaks(verses_to_body(sc.verses))
                from scripture_lookup import parse_scripture_reference

                parsed = parse_scripture_reference(result.scripture_reference)
                if parsed:
                    result.scripture_reference = parsed.display
                result.notes.append(f"성경 본문 보강 ← {result.scripture_reference}")


def result_to_session_updates(p: ParsedBulletin) -> dict[str, str]:
    """Map parser result to Streamlit session_state keys (via pending)."""
    mapping = {
        "church_en": p.church_name_en,
        "church_ko": p.church_name_ko,
        "service_title": p.service_title,
        "service_time": p.service_time,
        "preacher": p.preacher,
        "prep_hymn_1_num": p.prep_hymn_1_num,
        "prep_hymn_1_title": p.prep_hymn_1_title,
        "prep_hymn_2_num": p.prep_hymn_2_num,
        "prep_hymn_2_title": p.prep_hymn_2_title,
        "prep_hymn_3_num": p.prep_hymn_3_num,
        "prep_hymn_3_title": p.prep_hymn_3_title,
        "prep_hymn_4_num": p.prep_hymn_4_num,
        "prep_hymn_4_title": p.prep_hymn_4_title,
        "prep_hymn_5_num": p.prep_hymn_5_num,
        "prep_hymn_5_title": p.prep_hymn_5_title,
        "praise_num": p.praise_num,
        "praise_title": p.praise_title,
        "responsive_num": p.responsive_num,
        "responsive_title": p.responsive_title,
        "responsive_body": p.responsive_body,
        "hymn_num": p.hymn_num,
        "hymn_title": p.hymn_title,
        "prayer_leader": p.prayer_leader,
        "prayer_text": p.prayer_text,
        "choir_anthem_title": p.choir_anthem_title,
        "scripture_reference_input": p.scripture_reference,
        "scripture_text_area": p.scripture_text,
        "response_num": p.response_num,
        "response_title": p.response_title,
        "sermon_title": p.sermon_title,
        "sermon_subtitle": p.sermon_subtitle,
        "offering_num": p.offering_num,
        "offering_title": p.offering_title,
        "benediction": p.benediction,
    }
    return {k: v for k, v in mapping.items() if v and str(v).strip()}


# --- Multi-page extraction ---------------------------------------------------

PAGE_ROLES = (
    ("cover_order", "표지 · 예배 순서 (Cover & Order)"),
    ("readings", "말씀 · 교독 · 기도 (Readings & Worship)"),
    ("announcements", "소식 · 광고 (Announcements)"),
    ("skip", "사용 안 함 (Skip)"),
)

ROLE_LABELS = {k: v for k, v in PAGE_ROLES}


@dataclass
class BulletinPage:
    index: int  # 1-based
    text: str
    method: str = ""
    suggested_role: str = "cover_order"
    preview: str = ""  # short preview


@dataclass
class MultiPageBulletin:
    pages: list[BulletinPage] = field(default_factory=list)
    role_map: dict[int, str] = field(default_factory=dict)  # page index -> role
    parsed: ParsedBulletin = field(default_factory=ParsedBulletin)
    method: str = ""


def suggest_page_role(text: str, page_index: int, total: int) -> str:
    """Heuristic role for a bulletin page."""
    ko = text or ""
    score = {
        "cover_order": 0,
        "readings": 0,
        "announcements": 0,
    }
    if any(k in ko for k in ("예배 순서", "order of worship", "사도신경", "찬양과 기도", "축도")):
        score["cover_order"] += 3
    if any(k in ko for k in ("교독", "성경", "오늘의 말씀", "히브리", "복음", "인도자", "회중", "생명의 말씀")):
        score["readings"] += 3
    if any(k in ko for k in ("광고", "소식", "안내", "알림", "모임", "announcement", "소식지")):
        score["announcements"] += 4
    if page_index == 1:
        score["cover_order"] += 2
    if page_index == 2 and total >= 2:
        score["readings"] += 1
    if page_index >= 3:
        score["announcements"] += 1
    best = max(score, key=score.get)
    if score[best] == 0:
        return "cover_order" if page_index == 1 else "readings"
    return best


def extract_pages_from_upload(filename: str, raw: bytes) -> list[BulletinPage]:
    """Split an upload into per-page text units."""
    name = (filename or "").lower()
    pages: list[BulletinPage] = []

    if name.endswith((".txt", ".md", ".csv")):
        text, method = extract_text_from_upload(filename, raw)
        chunks = _split_text_into_pages(text)
        for i, chunk in enumerate(chunks, start=1):
            pages.append(
                BulletinPage(
                    index=i,
                    text=chunk,
                    method=method,
                    suggested_role=suggest_page_role(chunk, i, len(chunks)),
                    preview=_preview(chunk),
                )
            )
        return pages

    if name.endswith(".pdf"):
        return _extract_pdf_pages(raw)

    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
        text, method = _extract_image(raw)
        pages.append(
            BulletinPage(
                index=1,
                text=text,
                method=method,
                suggested_role=suggest_page_role(text, 1, 1),
                preview=_preview(text),
            )
        )
        return pages

    text, method = extract_text_from_upload(filename, raw)
    return [
        BulletinPage(
            index=1,
            text=text,
            method=method,
            suggested_role=suggest_page_role(text, 1, 1),
            preview=_preview(text),
        )
    ]


def extract_pages_from_uploads(files: list[tuple[str, bytes]]) -> list[BulletinPage]:
    """Multiple images/files become sequential pages."""
    if len(files) == 1:
        return extract_pages_from_upload(files[0][0], files[0][1])

    pages: list[BulletinPage] = []
    idx = 1
    for filename, raw in files:
        name = (filename or "").lower()
        if name.endswith(".pdf"):
            sub = _extract_pdf_pages(raw)
            for p in sub:
                p.index = idx
                pages.append(p)
                idx += 1
        else:
            part_pages = extract_pages_from_upload(filename, raw)
            for p in part_pages:
                p.index = idx
                p.suggested_role = suggest_page_role(p.text, idx, max(len(files), idx))
                pages.append(p)
                idx += 1
    # re-suggest with final total
    total = len(pages)
    for p in pages:
        p.suggested_role = suggest_page_role(p.text, p.index, total)
    return pages


def _preview(text: str, n: int = 280) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return (t[:n] + "…") if len(t) > n else t


def _split_text_into_pages(text: str) -> list[str]:
    if not text.strip():
        return [""]
    # Form-feed or markdown page markers
    if "\f" in text:
        parts = [p.strip() for p in text.split("\f") if p.strip()]
        return parts or [text]
    marked = re.split(r"(?i)\n\s*---\s*page\s*\d+\s*---\s*\n", text)
    marked = [p.strip() for p in marked if p.strip()]
    if len(marked) > 1:
        return marked
    # Double blank-line chunks if very long
    if text.count("\n") > 80:
        rough = re.split(r"\n\s*\n\s*\n+", text)
        rough = [p.strip() for p in rough if p.strip()]
        if len(rough) > 1:
            return rough
    return [text.strip()]


def _extract_pdf_pages(raw: bytes) -> list[BulletinPage]:
    pages: list[BulletinPage] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        for i, page in enumerate(reader.pages, start=1):
            t = (page.extract_text() or "").strip()
            pages.append(
                BulletinPage(
                    index=i,
                    text=t,
                    method="pdf",
                    suggested_role="cover_order",
                    preview=_preview(t),
                )
            )
    except Exception as exc:
        return [
            BulletinPage(
                index=1,
                text="",
                method=f"pdf-failed:{exc}",
                suggested_role="cover_order",
                preview="",
            )
        ]

    # OCR sparse pages
    sparse = sum(1 for p in pages if len(re.sub(r"\s+", "", p.text)) < 30)
    if sparse == len(pages) and pages:
        ocr_pages = _ocr_pdf_pages_list(raw)
        if ocr_pages:
            return ocr_pages

    total = len(pages)
    for p in pages:
        p.suggested_role = suggest_page_role(p.text, p.index, total)
        p.preview = _preview(p.text)
    return pages


def _ocr_pdf_pages_list(raw: bytes) -> list[BulletinPage]:
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        return []
    try:
        images = convert_from_bytes(raw, dpi=200)
    except Exception:
        return []
    out: list[BulletinPage] = []
    for i, img in enumerate(images, start=1):
        t, note = _ocr_pil(img)
        out.append(
            BulletinPage(
                index=i,
                text=t,
                method=f"pdf-ocr:{note}",
                suggested_role=suggest_page_role(t, i, len(images)),
                preview=_preview(t),
            )
        )
    return out


def _merge_parsed(base: ParsedBulletin, extra: ParsedBulletin, *, role: str) -> ParsedBulletin:
    """Fill empty fields from extra; append announcements; prefer role-specific content."""
    fill_attrs = [
        "church_name_en",
        "church_name_ko",
        "service_title",
        "service_time",
        "preacher",
        "prep_hymn_1_num",
        "prep_hymn_1_title",
        "prep_hymn_2_num",
        "prep_hymn_2_title",
        "prep_hymn_3_num",
        "prep_hymn_3_title",
        "prep_hymn_4_num",
        "prep_hymn_4_title",
        "prep_hymn_5_num",
        "prep_hymn_5_title",
        "praise_num",
        "praise_title",
        "responsive_num",
        "responsive_title",
        "responsive_body",
        "hymn_num",
        "hymn_title",
        "prayer_leader",
        "prayer_text",
        "choir_anthem_title",
        "scripture_reference",
        "scripture_text",
        "response_num",
        "response_title",
        "sermon_title",
        "sermon_subtitle",
        "offering_num",
        "offering_title",
        "benediction",
    ]
    for attr in fill_attrs:
        cur = getattr(base, attr, "") or ""
        new = getattr(extra, attr, "") or ""
        if not cur and new:
            setattr(base, attr, new)
        elif role == "readings" and attr in (
            "scripture_reference",
            "scripture_text",
            "responsive_body",
            "responsive_title",
            "responsive_num",
            "prayer_text",
        ) and new:
            # Prefer readings-page content for these
            if len(new) > len(cur):
                setattr(base, attr, new)

    if role == "announcements":
        chunk = (extra.raw_text or "").strip()
        if chunk:
            if base.raw_text and "ANNOUNCEMENTS" not in (base.notes or []):
                pass
            existing_notes = "\n".join(base.notes)
            # stash in field_map later via announcements key
            base.notes.append(f"소식/광고 페이지 감지 ({len(chunk)}자)")
            # Use sermon_subtitle spare? Better: encode in field_map
            fm = dict(base.field_map or {})
            prev = fm.get("announcements", "")
            fm["announcements"] = (prev + "\n\n" + chunk).strip() if prev else chunk
            base.field_map = fm

    base.notes.extend(extra.notes or [])
    return base


def parse_multipage_bulletin(
    pages: list[BulletinPage],
    *,
    role_map: Optional[dict[int, str]] = None,
) -> MultiPageBulletin:
    """Parse each page and merge into one bulletin template + page plan."""
    if not pages:
        empty = ParsedBulletin(notes=["페이지가 없습니다."])
        empty.field_map = {}
        return MultiPageBulletin(pages=[], parsed=empty)

    role_map = dict(role_map or {})
    for p in pages:
        role_map.setdefault(p.index, p.suggested_role)

    merged = ParsedBulletin(method="multipage")
    announcements_parts: list[str] = []
    page_plan: dict[str, list[int]] = {
        "cover_order": [],
        "readings": [],
        "announcements": [],
    }

    for p in pages:
        role = role_map.get(p.index, p.suggested_role)
        if role == "skip":
            merged.notes.append(f"p.{p.index} 건너뜀")
            continue
        page_plan.setdefault(role, []).append(p.index)
        parsed = parse_bulletin_text(p.text, method=f"p{p.index}:{p.method}")
        parsed.notes = [f"[p.{p.index}/{role}] {n}" for n in parsed.notes]
        if role == "announcements":
            if p.text.strip():
                announcements_parts.append(p.text.strip())
            merged.notes.append(f"p.{p.index} → 소식/광고")
        else:
            merged = _merge_parsed(merged, parsed, role=role)
            merged.notes.append(f"p.{p.index} → {ROLE_LABELS.get(role, role)}")

    # Combined raw text
    merged.raw_text = "\n\n".join(
        f"--- Page {p.index} ({role_map.get(p.index)}) ---\n{p.text}" for p in pages
    )
    merged.method = ",".join(sorted({p.method for p in pages if p.method})) or "multipage"
    _enrich_parsed_lookups(merged)
    merged.field_map = result_to_session_updates(merged)
    if announcements_parts:
        merged.field_map["announcements"] = "\n\n".join(announcements_parts)
    # Persist plan as JSON-ish string list for session (handled in app)
    merged.field_map["_page_plan_cover"] = ",".join(str(i) for i in page_plan.get("cover_order", []))
    merged.field_map["_page_plan_readings"] = ",".join(str(i) for i in page_plan.get("readings", []))
    merged.field_map["_page_plan_announcements"] = ",".join(
        str(i) for i in page_plan.get("announcements", [])
    )

    return MultiPageBulletin(
        pages=pages,
        role_map=role_map,
        parsed=merged,
        method=merged.method,
    )


def parse_uploaded_bulletin(filename: str, raw: bytes) -> ParsedBulletin:
    mp = parse_multipage_bulletin(extract_pages_from_upload(filename, raw))
    parsed = mp.parsed
    if not any((p.text or "").strip() for p in mp.pages):
        parsed.notes.insert(
            0,
            "텍스트를 추출하지 못했습니다. 이미지/스캔 PDF는 Tesseract OCR(한글 언어팩) 설치가 필요합니다. "
            "또는 텍스트로 복사해 붙여넣기 칸을 사용하세요.",
        )
    return parsed


def parse_uploaded_bulletin_multipage(
    files: list[tuple[str, bytes]],
    *,
    role_map: Optional[dict[int, str]] = None,
) -> MultiPageBulletin:
    pages = extract_pages_from_uploads(files)
    return parse_multipage_bulletin(pages, role_map=role_map)
