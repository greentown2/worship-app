"""Load 찬송가 / 교독문 catalogs from JSON files or GitHub (Streamlit Cloud safe)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_GITHUB_REPO = "pastoreom2-hue/senir-hotel-worship-order"
_GITHUB_REFS = ("master", "feature/worship-html-hymn-pptx")

INDEX: dict = {}
LYRICS: dict = {}
RESPONSIVE_INDEX: dict = {}
RESPONSIVE_READINGS: dict = {}
SOURCE = "empty"
ERROR = ""


def _read_json(path: Path) -> dict:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError):
        return {}


def _fetch_json(name: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GraceWorshipPPT/1.0)",
        "Accept": "application/json,text/plain,*/*",
    }
    urls = []
    for ref in _GITHUB_REFS:
        urls.append(f"https://raw.githubusercontent.com/{_GITHUB_REPO}/{ref}/data/{name}")
    urls.append(f"https://cdn.jsdelivr.net/gh/{_GITHUB_REPO}@master/data/{name}")
    for url in urls:
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if isinstance(data, dict) and data:
                return data
        except (URLError, HTTPError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
            continue
    return {}


def _search_roots() -> list[Path]:
    here = Path(__file__).resolve().parent
    cwd = Path.cwd().resolve()
    roots = [
        cwd,
        here,
        Path("/mount/src"),
        Path("/app"),
        cwd.parent,
        here.parent,
    ]
    out: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            root = root.resolve()
        except OSError:
            continue
        if root in seen:
            continue
        seen.add(root)
        out.append(root)
    return out


def load() -> str:
    """Populate module-level catalogs. Returns a short source label."""
    global INDEX, LYRICS, RESPONSIVE_INDEX, RESPONSIVE_READINGS, SOURCE, ERROR
    ERROR = ""
    files = {
        "hymn_index.json": "INDEX",
        "hymns_lyrics.json": "LYRICS",
        "responsive_index.json": "RESPONSIVE_INDEX",
        "responsive_readings.json": "RESPONSIVE_READINGS",
    }
    loaded = {attr: {} for attr in files.values()}
    source = "empty"

    for root in _search_roots():
        data_dir = root / "data"
        if not (data_dir / "hymn_index.json").is_file() and not (data_dir / "hymns_lyrics.json").is_file():
            continue
        for name, attr in files.items():
            data = _read_json(data_dir / name)
            if data:
                loaded[attr] = data
        if loaded["INDEX"] or loaded["LYRICS"]:
            source = f"disk:{data_dir}"
            break

    if not loaded["INDEX"] or not loaded["LYRICS"]:
        for name, attr in files.items():
            if loaded[attr]:
                continue
            fetched = _fetch_json(name)
            if fetched:
                loaded[attr] = fetched
                source = "github"
        if source == "empty" and not (loaded["INDEX"] or loaded["LYRICS"]):
            ERROR = "disk and GitHub hymn JSON both empty"
        elif not loaded["LYRICS"]:
            ERROR = "lyrics JSON missing"

    INDEX = loaded["INDEX"]
    LYRICS = loaded["LYRICS"]
    RESPONSIVE_INDEX = loaded["RESPONSIVE_INDEX"]
    RESPONSIVE_READINGS = loaded["RESPONSIVE_READINGS"]
    SOURCE = source
    return source


load()
