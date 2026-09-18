# -*- coding: utf-8 -*-
"""Streamlit Cloud hymn loader.

GitHub layout (exact names, lowercase):
  data/hymn_index.json
  data/hymns_lyrics.json
  hymn_assets/hymn_index.json
  hymn_assets/hymns_lyrics.json

Cloud clones the repo to /mount/src. Local uses this file's folder.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HYMN_INDEX_FILE = "hymn_index.json"
HYMN_LYRICS_FILE = "hymns_lyrics.json"
_FOLDERS = ("hymn_assets", "data")
_LAST_ERROR = ""


def _ensure_sys_path() -> None:
    for raw in ("/mount/src", "/app", str(Path(__file__).resolve().parent)):
        if raw and raw not in sys.path and Path(raw).exists():
            sys.path.insert(0, raw)


_ensure_sys_path()


def _roots() -> list[Path]:
    """Prefer Streamlit's clone path, then this module, then cwd."""
    out: list[Path] = []
    for raw in (
        Path("/mount/src"),
        Path("/app"),
        Path(__file__).resolve().parent,
        Path.cwd(),
    ):
        try:
            p = Path(raw).resolve()
        except OSError:
            continue
        if p in out or not p.exists():
            continue
        out.append(p)
    return out


def _read(path: Path) -> dict:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError):
        return {}


def _from_files(filename: str) -> dict:
    for root in _roots():
        for folder in _FOLDERS:
            data = _read(root / folder / filename)
            if data:
                return data
    return {}


def load_index() -> dict[str, str]:
    global _LAST_ERROR
    _ensure_sys_path()
    raw = _from_files(HYMN_INDEX_FILE)
    out = {str(k): str(v or "") for k, v in raw.items() if str(k).isdigit()}
    if out:
        return out
    try:
        from hymn_index_embed import INDEX as embedded
        return {str(k): str(v or "") for k, v in embedded.items() if str(k).isdigit()}
    except Exception as exc:
        _LAST_ERROR = f"hymn_index_embed {type(exc).__name__}: {exc}"
        return {}


def load_lyrics() -> dict:
    global _LAST_ERROR
    _ensure_sys_path()
    raw = _from_files(HYMN_LYRICS_FILE)
    out = {
        str(k): v
        for k, v in (raw or {}).items()
        if str(k).isdigit() and isinstance(v, dict)
    }
    if out:
        return out
    try:
        from hymn_lyrics_embed import load as load_embed
        data = load_embed()
        if not isinstance(data, dict):
            return {}
        return {
            str(k): v
            for k, v in data.items()
            if str(k).isdigit() and isinstance(v, dict)
        }
    except Exception as exc:
        _LAST_ERROR = f"hymn_lyrics_embed {type(exc).__name__}: {exc}"
        return {}


def debug_lines() -> list[str]:
    lines = [
        f"cwd={Path.cwd()}",
        f"hymn_db.py={Path(__file__).resolve()}",
        f"sys.path0={sys.path[0] if sys.path else ''}",
    ]
    if _LAST_ERROR:
        lines.append(f"error={_LAST_ERROR}")
    for root in _roots():
        for folder in _FOLDERS:
            for name in (HYMN_INDEX_FILE, HYMN_LYRICS_FILE):
                p = root / folder / name
                lines.append(f"{'Y' if p.is_file() else 'N'} {p}")
        embed = root / "hymn_index_embed.py"
        lyrics_py = root / "hymn_lyrics_embed.py"
        lines.append(f"{'Y' if embed.is_file() else 'N'} {embed}")
        lines.append(f"{'Y' if lyrics_py.is_file() else 'N'} {lyrics_py}")
    return lines
