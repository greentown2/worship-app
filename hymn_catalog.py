"""Load 찬송가 / 교독문 catalogs from JSON files (Streamlit Cloud safe).

GitHub raw fallback is skipped for private repos — it 404s and can stall
the Streamlit import for minutes. Titles are always available from the
embedded index even if data/hymn_index.json is missing on disk.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_GITHUB_REPO = "pastoreom2-hue/senir-hotel-worship-order"
_GITHUB_REFS = ("master", "feature/worship-html-hymn-pptx")

try:
    from hymn_index_embed import INDEX as _EMBEDDED_INDEX
except Exception:
    _EMBEDDED_INDEX = {}

INDEX: dict = {str(k): str(v or "") for k, v in _EMBEDDED_INDEX.items() if str(k).isdigit()}
LYRICS: dict = {}
RESPONSIVE_INDEX: dict = {}
RESPONSIVE_READINGS: dict = {}
SOURCE = "embed" if INDEX else "empty"
ERROR = ""


def _read_json(path: Path) -> dict:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError):
        return {}


def _numeric_len(data: dict) -> int:
    return sum(1 for k in (data or {}) if str(k).isdigit())


def _better(new: dict, old: dict) -> bool:
    return _numeric_len(new) > _numeric_len(old)


def _fetch_json(name: str) -> dict:
    """GitHub raw fallback. Repo is public; keep timeouts short so Cloud does not stall."""
    token = (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_PAT")
        or ""
    ).strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GraceWorshipPPT/1.0)",
        "Accept": "application/json,text/plain,*/*",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    urls = [
        f"https://raw.githubusercontent.com/{_GITHUB_REPO}/{ref}/data/{name}"
        for ref in _GITHUB_REFS
    ]
    urls.append(f"https://cdn.jsdelivr.net/gh/{_GITHUB_REPO}@master/data/{name}")
    urls.append(f"https://raw.githubusercontent.com/{_GITHUB_REPO}/master/hymn_assets/{name}")
    for url in urls:
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=8) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if isinstance(data, dict) and data:
                return data
        except (URLError, HTTPError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
            continue
    return {}


def _search_data_dirs() -> list[Path]:
    """Folders that contain hymn_index.json / hymns_lyrics.json next to the app."""
    here = Path(__file__).resolve().parent
    cwd = Path.cwd().resolve()
    folders = [
        Path("/mount/src") / "hymn_assets",
        Path("/mount/src") / "data",
        here / "hymn_assets",
        here / "data",
        cwd / "hymn_assets",
        cwd / "data",
        Path(tempfile.gettempdir()) / "worship-data",
    ]
    out: list[Path] = []
    seen: set[Path] = set()
    for folder in folders:
        try:
            folder = folder.resolve()
        except OSError:
            continue
        if folder in seen:
            continue
        seen.add(folder)
        out.append(folder)
    return out


def _embedded_index() -> dict:
    try:
        from hymn_index_embed import INDEX as embedded
    except Exception:
        return {}
    if not isinstance(embedded, dict):
        return {}
    return {str(k): str(v or "") for k, v in embedded.items() if str(k).isdigit()}


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
    sources: list[str] = []

    try:
        from hymn_db import load_index as _db_index, load_lyrics as _db_lyrics
        idx = _db_index()
        lyr = _db_lyrics()
        if idx:
            loaded["INDEX"] = idx
            sources.append("hymn_db")
        if lyr:
            loaded["LYRICS"] = lyr
            if "hymn_db" not in sources:
                sources.append("hymn_db")
    except Exception:
        pass

    try:
        from app_paths import load_local_hymn_json
        for name, attr in files.items():
            data = load_local_hymn_json(name)
            if data and _better(data, loaded[attr]):
                loaded[attr] = data
        if _numeric_len(loaded["LYRICS"]) or _numeric_len(loaded["INDEX"]):
            sources.append("app-dir")
    except Exception:
        pass

    try:
        import hymn_assets
        for name, attr in files.items():
            data = hymn_assets.load_json(name)
            if data and _better(data, loaded[attr]):
                loaded[attr] = data
        if _numeric_len(loaded["LYRICS"]) or _numeric_len(loaded["INDEX"]):
            if "package" not in sources:
                sources.append("package")
    except Exception:
        pass

    for data_dir in _search_data_dirs():
        for name, attr in files.items():
            data = _read_json(data_dir / name)
            if data and _better(data, loaded[attr]):
                loaded[attr] = data
                label = f"disk:{data_dir}"
                if label not in sources:
                    sources.append(label)

    embedded = _embedded_index() or dict(INDEX)
    if embedded and _better(embedded, loaded["INDEX"]):
        loaded["INDEX"] = embedded
        if "embed" not in sources:
            sources.append("embed")

    if _numeric_len(loaded["INDEX"]) < 200 or _numeric_len(loaded["LYRICS"]) < 200:
        # Do not fetch GitHub during import — Streamlit Cloud kills slow imports.
        # Sidebar install_catalog() downloads after the page is up.
        pass

    if _numeric_len(INDEX) > _numeric_len(loaded["INDEX"]):
        loaded["INDEX"] = dict(INDEX)
        if "embed" not in sources:
            sources.append("embed")
    if _numeric_len(LYRICS) > _numeric_len(loaded["LYRICS"]):
        loaded["LYRICS"] = dict(LYRICS)

    INDEX = loaded["INDEX"]
    LYRICS = loaded["LYRICS"]
    RESPONSIVE_INDEX = loaded["RESPONSIVE_INDEX"]
    RESPONSIVE_READINGS = loaded["RESPONSIVE_READINGS"]
    SOURCE = "+".join(sources) if sources else "empty"
    if _numeric_len(INDEX) == 0 and _numeric_len(LYRICS) == 0:
        ERROR = "hymn JSON missing next to app.py"
    elif _numeric_len(LYRICS) == 0:
        ERROR = "lyrics JSON missing"
    elif _numeric_len(INDEX) == 0:
        ERROR = "hymn index missing"
    return SOURCE


def install_catalog() -> dict:
    """Copy packaged or GitHub hymn JSON into a writable folder (Streamlit /tmp)."""
    from app_paths import clear_json_cache, save_json, writable_data_dir

    names = {
        "hymn_index.json": "INDEX",
        "hymns_lyrics.json": "LYRICS",
        "responsive_index.json": "RESPONSIVE_INDEX",
        "responsive_readings.json": "RESPONSIVE_READINGS",
    }
    got: dict[str, dict] = {}
    source = ""
    try:
        import hymn_assets
        for name in names:
            data = hymn_assets.load_json(name)
            if data:
                got[name] = data
        if got:
            source = "package"
    except Exception:
        pass
    for name in names:
        if _numeric_len(got.get(name, {})) >= 200:
            continue
        fetched = _fetch_json(name)
        if fetched:
            got[name] = fetched
            source = source or "github"
            if source == "package":
                source = "package+github"
    writable_data_dir()
    for name, data in got.items():
        save_json(name, data)
    try:
        clear_json_cache()
    except Exception:
        pass
    load()
    return {
        "source": source or "empty",
        "index": _numeric_len(INDEX),
        "lyrics": _numeric_len(LYRICS),
        "files": {name: _numeric_len(data) for name, data in got.items()},
    }


# Do not load lyrics at import — Streamlit Cloud kills slow imports.
# app.py / hymn_db load JSON from data/ and hymn_assets/ after the page starts.
