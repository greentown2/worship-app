"""Local storage for hymn / other PPT decks, plus this week's ordered set."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIBRARY_ROOT = ROOT / "library" / "ppt"
HYMNS_DIR = LIBRARY_ROOT / "hymns"
OTHER_DIR = LIBRARY_ROOT / "other"
THIS_WEEK_DIR = LIBRARY_ROOT / "this_week"
THIS_WEEK_ORDER = THIS_WEEK_DIR / "order.json"

CATEGORIES = {
    "hymns": ("찬송가 PPT", HYMNS_DIR),
    "other": ("기타 PPT 자료", OTHER_DIR),
}


def ensure_dirs() -> None:
    for _label, path in CATEGORIES.values():
        path.mkdir(parents=True, exist_ok=True)
    THIS_WEEK_DIR.mkdir(parents=True, exist_ok=True)


def category_dir(key: str) -> Path:
    ensure_dirs()
    if key not in CATEGORIES:
        raise KeyError(key)
    return CATEGORIES[key][1]


def _safe_name(name: str) -> str:
    base = Path(name or "deck.pptx").name
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .")
    if not base:
        base = "deck.pptx"
    if not base.lower().endswith(".pptx"):
        base = f"{base}.pptx"
    return base


def unique_path(folder: Path, filename: str) -> Path:
    target = folder / _safe_name(filename)
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    n = 2
    while True:
        cand = folder / f"{stem}_{n}{suffix}"
        if not cand.exists():
            return cand
        n += 1


def save_upload(category: str, filename: str, data: bytes) -> Path:
    folder = category_dir(category)
    path = unique_path(folder, filename)
    path.write_bytes(data)
    return path


def list_files(category: str | None = None) -> list[tuple[str, Path]]:
    """Return (category_key, path) sorted by name."""
    ensure_dirs()
    keys = [category] if category else list(CATEGORIES.keys())
    out: list[tuple[str, Path]] = []
    for key in keys:
        if key not in CATEGORIES:
            continue
        folder = CATEGORIES[key][1]
        for p in sorted(folder.glob("*.pptx"), key=lambda x: x.name.lower()):
            if p.is_file():
                out.append((key, p))
    return out


def delete_file(path: Path) -> bool:
    ensure_dirs()
    path = path.resolve()
    allowed = {HYMNS_DIR.resolve(), OTHER_DIR.resolve(), THIS_WEEK_DIR.resolve()}
    if path.parent not in allowed or path.suffix.lower() != ".pptx":
        return False
    if path.is_file():
        path.unlink()
        _sync_this_week_order_file()
        return True
    return False


def open_folder(category: str | None = None) -> Path:
    ensure_dirs()
    if category == "this_week":
        folder = THIS_WEEK_DIR
    elif category:
        folder = category_dir(category)
    else:
        folder = LIBRARY_ROOT
    import os
    import subprocess
    import sys

    if sys.platform.startswith("win"):
        os.startfile(folder)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=False)
    else:
        subprocess.run(["xdg-open", str(folder)], check=False)
    return folder


# ── This week's ordered PPT set ─────────────────────────────────────────────

_ORDER_PREFIX = re.compile(r"^(\d{2})_(.+)$", re.IGNORECASE)


def _display_name(path: Path) -> str:
    m = _ORDER_PREFIX.match(path.name)
    return m.group(2) if m else path.name


def _load_order_names() -> list[str]:
    ensure_dirs()
    if not THIS_WEEK_ORDER.is_file():
        return []
    try:
        data = json.loads(THIS_WEEK_ORDER.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        pass
    return []


def _write_order_names(names: list[str]) -> None:
    ensure_dirs()
    THIS_WEEK_ORDER.write_text(
        json.dumps(names, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sync_this_week_order_file() -> list[Path]:
    """Renumber files 01_…, 02_… and refresh order.json. Returns ordered paths."""
    ensure_dirs()
    existing = {p.name: p for p in THIS_WEEK_DIR.glob("*.pptx") if p.is_file()}
    ordered_names = _load_order_names()
    # Keep known order, then append any new files not in the list
    paths: list[Path] = []
    seen: set[str] = set()
    for name in ordered_names:
        p = existing.get(name)
        if p and p.is_file():
            paths.append(p)
            seen.add(name)
    for name, p in sorted(existing.items()):
        if name not in seen:
            paths.append(p)

    final: list[Path] = []
    final_names: list[str] = []
    for i, p in enumerate(paths, 1):
        nice = _display_name(p)
        new_name = f"{i:02d}_{_safe_name(nice)}"
        dest = THIS_WEEK_DIR / new_name
        if p.name != new_name:
            # Avoid clobbering: temp rename if needed
            if dest.exists() and dest.resolve() != p.resolve():
                tmp = THIS_WEEK_DIR / f"__tmp_{i:02d}_{p.name}"
                p.rename(tmp)
                p = tmp
            if dest.exists() and dest.resolve() != p.resolve():
                dest.unlink()
            p.rename(dest)
            p = dest
        final.append(p)
        final_names.append(p.name)
    _write_order_names(final_names)
    return final


def list_this_week() -> list[Path]:
    """Ordered list of this week's PPT files."""
    return _sync_this_week_order_file()


def add_to_this_week(filename: str, data: bytes) -> Path:
    """Append a PPT to the end of this week's ordered set."""
    ensure_dirs()
    current = list_this_week()
    next_n = len(current) + 1
    safe = _safe_name(filename)
    # Strip any existing NN_ prefix from upload name
    m = _ORDER_PREFIX.match(safe)
    if m:
        safe = m.group(2)
        if not safe.lower().endswith(".pptx"):
            safe = f"{safe}.pptx"
    dest = THIS_WEEK_DIR / f"{next_n:02d}_{safe}"
    if dest.exists():
        dest = unique_path(THIS_WEEK_DIR, f"{next_n:02d}_{Path(safe).stem}.pptx")
    dest.write_bytes(data)
    names = _load_order_names()
    if dest.name not in names:
        names.append(dest.name)
        _write_order_names(names)
    return _sync_this_week_order_file()[-1]


def add_library_file_to_this_week(path: Path) -> Path:
    """Copy an existing library PPT into this week's set (append)."""
    path = path.resolve()
    if not path.is_file() or path.suffix.lower() != ".pptx":
        raise FileNotFoundError(path)
    return add_to_this_week(path.name, path.read_bytes())


def remove_this_week(path: Path) -> bool:
    path = path.resolve()
    if path.parent != THIS_WEEK_DIR.resolve() or not path.is_file():
        return False
    path.unlink()
    names = [n for n in _load_order_names() if n != path.name]
    _write_order_names(names)
    _sync_this_week_order_file()
    return True


def move_this_week(path: Path, direction: int) -> list[Path]:
    """Move file up (-1) or down (+1) in this week's order."""
    paths = list_this_week()
    names = [p.name for p in paths]
    try:
        i = next(j for j, p in enumerate(paths) if p.resolve() == path.resolve())
    except StopIteration:
        return paths
    j = i + direction
    if j < 0 or j >= len(names):
        return paths
    names[i], names[j] = names[j], names[i]
    _write_order_names(names)
    return _sync_this_week_order_file()


def clear_this_week() -> int:
    """Delete all this-week PPT files. Returns count removed."""
    ensure_dirs()
    n = 0
    for p in THIS_WEEK_DIR.glob("*.pptx"):
        if p.is_file():
            p.unlink()
            n += 1
    _write_order_names([])
    return n


def this_week_label(path: Path) -> str:
    """Human label like '1. 찬송가.pptx'."""
    m = _ORDER_PREFIX.match(path.name)
    if m:
        return f"{int(m.group(1))}. {m.group(2)}"
    return path.name
