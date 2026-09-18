"""Packaged hymn/responsive JSON — loaded via the Python package path (Streamlit-safe)."""

from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def load_json(name: str) -> dict:
    path = _HERE / name
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError):
        return {}


def lyrics() -> dict:
    return load_json("hymns_lyrics.json")


def index() -> dict:
    return load_json("hymn_index.json")
