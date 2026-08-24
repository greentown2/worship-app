"""Compact lookup catalogs for the browser presentation HTML."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


def build_lookup_bundle() -> dict:
    """
    Embeddable catalogs:
      hymns: { "7": "성부 성자 성령", ... }
      hymnLyrics: { "7": { "title": "...", "lyrics": "1절…\\n…" }, ... }
      responsive: { "13": { "title": "...", "body": "..." }, ... }
      scripture: { "히브리서 4:1-11": "1 ...\\n2 ...", ... }  (common set)
    """
    hymns: dict[str, str] = {}
    hymn_path = DATA_DIR / "hymn_index.json"
    if hymn_path.exists():
        raw = json.loads(hymn_path.read_text(encoding="utf-8"))
        for k, v in (raw or {}).items():
            hymns[str(k)] = str(v or "").strip()

    hymn_lyrics: dict[str, dict] = {}

    def _ingest_lyrics(raw: dict) -> None:
        for k, entry in (raw or {}).items():
            if str(k).startswith("_") or not isinstance(entry, dict):
                continue
            lines = entry.get("lyrics") or []
            if isinstance(lines, str):
                body = lines.strip()
            else:
                body = "\n".join(str(ln).rstrip() for ln in lines).strip()
            if not body:
                continue
            key = str(int(k)) if str(k).isdigit() else str(k)
            title = str(entry.get("title") or hymns.get(key) or "").strip()
            prev = hymn_lyrics.get(key)
            # Keep the richer lyric text when both local and cache exist
            if prev and len(prev.get("lyrics") or "") >= len(body):
                continue
            hymn_lyrics[key] = {"title": title, "lyrics": body}

    for fname in ("hymns_lyrics.json", "hymns_lyrics_cache.json"):
        path = DATA_DIR / fname
        if not path.exists():
            continue
        try:
            _ingest_lyrics(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError):
            continue

    responsive: dict[str, dict] = {}
    resp_path = DATA_DIR / "responsive_readings.json"
    if resp_path.exists():
        raw = json.loads(resp_path.read_text(encoding="utf-8"))
        for k, entry in (raw or {}).items():
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "").strip()
            body = str(entry.get("body") or "").strip()
            if body:
                responsive[str(k)] = {"title": title, "body": body}

    # Prefer sanitized bodies from the same sanitizer Streamlit uses
    try:
        from responsive_lookup import format_responsive_label, sanitize_responsive_body

        for num, entry in list(responsive.items()):
            clean = sanitize_responsive_body(entry.get("body") or "")
            if clean:
                entry["body"] = clean
            entry["label"] = format_responsive_label(int(num), entry.get("title") or "")
    except Exception:
        pass

    scripture: dict[str, str] = {}

    def _add_scripture_entry(ref: str, body: str) -> None:
        ref = (ref or "").strip()
        body = (body or "").strip()
        if not ref or not body:
            return
        scripture[ref] = body
        bare = ref
        for label in (" (개역개정)", " (새번역)", " (KRV)"):
            if bare.endswith(label):
                bare = bare[: -len(label)].strip()
        if bare and bare not in scripture:
            scripture[bare] = body

    for fname in ("scripture_common.json", "scripture_cache.json"):
        sc_path = DATA_DIR / fname
        if not sc_path.exists():
            continue
        try:
            raw = json.loads(sc_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for _k, entry in (raw or {}).items():
            if str(_k).startswith("_") or not isinstance(entry, dict):
                continue
            ref = str(entry.get("reference") or entry.get("display") or _k or "").strip()
            verses = entry.get("verses") or entry.get("text") or ""
            if isinstance(verses, list):
                body = "\n".join(str(v).strip() for v in verses if str(v).strip())
            else:
                body = str(verses or "").strip()
            _add_scripture_entry(ref, body)
            _add_scripture_entry(str(_k), body)

    return {
        "hymns": hymns,
        "hymnLyrics": hymn_lyrics,
        "responsive": responsive,
        "scripture": scripture,
    }
