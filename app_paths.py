"""Resolve repo / data directories on Windows, Streamlit Cloud, and temp copies."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_MARKER = "hymn_index.json"
_GITHUB_REPO = "pastoreom2-hue/senir-hotel-worship-order"
_GITHUB_BRANCHES = (
    "feature/worship-html-hymn-pptx",
    "master",
)
_BUNDLED_JSON = frozenset(
    {
        "hymn_index.json",
        "hymns_lyrics.json",
        "hymns_lyrics_cache.json",
        "responsive_index.json",
        "responsive_readings.json",
        "scripture_common.json",
        "scripture_cache.json",
        "scripture_rnksv.json",
    }
)

_JSON_MEMO: dict[str, dict] = {}
_ROOT: Optional[Path] = None


def is_streamlit_cloud() -> bool:
    if os.environ.get("STREAMLIT_SHARING_MODE"):
        return True
    home = os.environ.get("HOME", "")
    if home.startswith("/home/appuser"):
        return True
    if Path("/mount/src").is_dir():
        return True
    return False


def _has_data(root: Path) -> bool:
    try:
        return (
            (root / "data" / "hymn_index.json").is_file()
            or (root / "data" / "hymns_lyrics.json").is_file()
            or (root / "hymn_assets" / "hymn_index.json").is_file()
            or (root / "hymn_assets" / "hymns_lyrics.json").is_file()
        )
    except OSError:
        return False


def _discover_root() -> Path:
    here = Path(__file__).resolve().parent
    cwd = Path.cwd().resolve()
    candidates: list[Path] = [
        Path("/mount/src"),
        Path("/app"),
        here,
        cwd,
        Path("/workspace"),
    ]
    p = here
    for _ in range(6):
        candidates.append(p)
        if p.parent == p:
            break
        p = p.parent
    p = cwd
    for _ in range(6):
        candidates.append(p)
        if p.parent == p:
            break
        p = p.parent

    seen: set[Path] = set()
    for raw in candidates:
        try:
            cand = raw.resolve()
        except OSError:
            continue
        if cand in seen:
            continue
        seen.add(cand)
        if _has_data(cand):
            return cand

    for start in (cwd, here):
        try:
            hit = next(start.rglob(_MARKER), None)
        except OSError:
            hit = None
        if hit is not None and hit.is_file():
            return hit.parent.parent
    return here


def repo_root() -> Path:
    global _ROOT
    if _ROOT is not None and _has_data(_ROOT):
        return _ROOT
    found = _discover_root()
    if _has_data(found):
        _ROOT = found
    return found


def data_dir() -> Path:
    return repo_root() / "data"


def writable_data_dir() -> Path:
    if is_streamlit_cloud():
        p = Path(tempfile.gettempdir()) / "worship-data"
    else:
        p = data_dir()
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except OSError:
        p = Path(tempfile.gettempdir()) / "worship-data"
        p.mkdir(parents=True, exist_ok=True)
        return p


def read_json(path: Path) -> dict:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError):
        return {}


def app_dir() -> Path:
    """Directory that contains app.py / hymn_catalog.py (repo root on Streamlit)."""
    return Path(__file__).resolve().parent


def hymn_json_paths(filename: str) -> list[Path]:
    """Exact hymn JSON filenames, resolved from this file — not from cwd."""
    root = app_dir()
    cwd = Path.cwd()
    return [
        Path("/mount/src") / "hymn_assets" / filename,
        Path("/mount/src") / "data" / filename,
        root / "hymn_assets" / filename,
        root / "data" / filename,
        cwd / "hymn_assets" / filename,
        cwd / "data" / filename,
        writable_data_dir() / filename,
    ]


def load_local_hymn_json(filename: str) -> dict:
    """Load hymn_index.json or hymns_lyrics.json from paths next to the app."""
    best: dict = {}
    for path in hymn_json_paths(filename):
        data = read_json(path)
        n = sum(1 for k in data if str(k).isdigit())
        if n > sum(1 for k in best if str(k).isdigit()):
            best = data
    return best


def _github_json(name: str) -> dict:
    """Fetch catalog JSON from public GitHub/jsDelivr. Short timeouts for Streamlit."""
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
        f"https://raw.githubusercontent.com/{_GITHUB_REPO}/{branch}/data/{name}"
        for branch in _GITHUB_BRANCHES
    ]
    urls.append(f"https://cdn.jsdelivr.net/gh/{_GITHUB_REPO}@master/data/{name}")
    urls.append(f"https://raw.githubusercontent.com/{_GITHUB_REPO}/master/hymn_assets/{name}")
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
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


def _from_bundled_module(name: str) -> dict:
    try:
        import hymn_catalog
    except Exception:
        return {}
    mapping = {
        "hymn_index.json": "INDEX",
        "hymns_lyrics.json": "LYRICS",
        "responsive_index.json": "RESPONSIVE_INDEX",
        "responsive_readings.json": "RESPONSIVE_READINGS",
    }
    attr = mapping.get(name)
    if not attr:
        return {}
    data = getattr(hymn_catalog, attr, None)
    return data if isinstance(data, dict) and data else {}


def load_bundled_json(name: str) -> dict:
    """Load the fullest copy from embed/disk (never stall on private GitHub raw)."""
    if name in _JSON_MEMO:
        return _JSON_MEMO[name]

    candidates: list[dict] = []
    bundled = _from_bundled_module(name)
    if bundled:
        candidates.append(bundled)

    here = app_dir()
    try:
        import hymn_assets
        packaged = hymn_assets.load_json(name)
        if packaged:
            candidates.append(packaged)
    except Exception:
        pass
    local = load_local_hymn_json(name)
    if local:
        candidates.append(local)
    for path in hymn_json_paths(name):
        data = read_json(path)
        if data:
            candidates.append(data)

    best: dict = {}
    for data in candidates:
        if sum(1 for k in data if str(k).isdigit()) > sum(1 for k in best if str(k).isdigit()):
            best = data
    if best:
        if name in _BUNDLED_JSON:
            _JSON_MEMO[name] = best
        return best

    fetched = _github_json(name) if name in _BUNDLED_JSON else {}
    if fetched:
        _JSON_MEMO[name] = fetched
        try:
            dest = writable_data_dir() / name
            dest.write_text(
                json.dumps(fetched, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        return fetched
    return {}


def load_overlay_json(name: str) -> dict:
    """Bundled catalog plus any locally written overlay (cloud /tmp cache)."""
    base = dict(load_bundled_json(name))
    overlay = read_json(writable_data_dir() / name)
    if overlay:
        base.update(overlay)
    return base


def save_json(name: str, payload: dict) -> None:
    path = writable_data_dir() / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        writable_data_dir().mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            path.write_text(text, encoding="utf-8")
        except OSError:
            return
    _JSON_MEMO.pop(name, None)


def clear_json_cache() -> None:
    global _ROOT
    _JSON_MEMO.clear()
    _ROOT = None


def debug_paths() -> dict[str, str]:
    d = data_dir()
    marker = d / _MARKER
    return {
        "repo": str(repo_root()),
        "data": str(d),
        "marker_exists": str(marker.is_file()),
        "cwd": str(Path.cwd()),
        "cloud": str(is_streamlit_cloud()),
        "writable": str(writable_data_dir()),
        "app_paths": str(Path(__file__).resolve()),
    }
