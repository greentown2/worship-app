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
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HYMN_INDEX_FILE = "hymn_index.json"
HYMN_LYRICS_FILE = "hymns_lyrics.json"
_FOLDERS = ("hymn_assets", "data")
_GITHUB_REPO = "pastoreom2-hue/senir-hotel-worship-order"
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


def _from_package(filename: str) -> dict:
    try:
        import hymn_assets
        data = hymn_assets.load_json(filename)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _from_github(filename: str) -> dict:
    urls = [
        f"https://raw.githubusercontent.com/{_GITHUB_REPO}/master/hymn_assets/{filename}",
        f"https://raw.githubusercontent.com/{_GITHUB_REPO}/master/data/{filename}",
        f"https://cdn.jsdelivr.net/gh/{_GITHUB_REPO}@master/hymn_assets/{filename}",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GraceWorshipPPT/1.0)",
        "Accept": "application/json,text/plain,*/*",
    }
    for url in urls:
        try:
            with urlopen(Request(url, headers=headers), timeout=8) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if isinstance(data, dict) and data:
                return data
        except (URLError, HTTPError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
            continue
    return {}


def _digit_dict(raw: dict, *, values_are_dict: bool) -> dict:
    out = {}
    for k, v in (raw or {}).items():
        if not str(k).isdigit():
            continue
        if values_are_dict:
            if isinstance(v, dict):
                out[str(k)] = v
        else:
            out[str(k)] = str(v or "")
    return out


def load_index() -> dict[str, str]:
    global _LAST_ERROR
    _ensure_sys_path()
    for loader in (_from_package, _from_files, _from_github):
        try:
            out = _digit_dict(loader(HYMN_INDEX_FILE), values_are_dict=False)
            if out:
                return out
        except Exception as exc:
            _LAST_ERROR = f"{loader.__name__} {type(exc).__name__}: {exc}"
    try:
        from hymn_index_embed import INDEX as embedded
        return _digit_dict(embedded, values_are_dict=False)
    except Exception as exc:
        _LAST_ERROR = f"hymn_index_embed {type(exc).__name__}: {exc}"
        return {}


def load_lyrics() -> dict:
    global _LAST_ERROR
    _ensure_sys_path()
    for loader in (_from_package, _from_files, _from_github):
        try:
            out = _digit_dict(loader(HYMN_LYRICS_FILE), values_are_dict=True)
            if out:
                return out
        except Exception as exc:
            _LAST_ERROR = f"{loader.__name__} {type(exc).__name__}: {exc}"
    try:
        from hymn_lyrics_embed import load as load_embed
        return _digit_dict(load_embed(), values_are_dict=True)
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
