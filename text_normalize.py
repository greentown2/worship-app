"""Normalize soft-break / OOXML escape codes to real newlines across the backend."""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Sequence

_SOFT_BREAK_RE = re.compile(
    r"(?:_x000[Bb]_|_x000[Aa]_|\u000b|\u000c|\r\n|\r|\v)+"
)


def normalize_breaks(text: str | None) -> str:
    """Force _x000B_ / vertical-tab / CR soft breaks into real Enter newlines."""
    if text is None:
        return ""
    out = str(text)
    if not out:
        return ""
    out = _SOFT_BREAK_RE.sub("\n", out)
    out = out.replace("\u2028", "\n").replace("\u2029", "\n")
    out = out.replace("\xa0", " ")
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def normalize_line_list(lines: Sequence[str] | None) -> List[str]:
    """Normalize each line; expand embedded soft breaks into multiple lines."""
    if not lines:
        return []
    out: list[str] = []
    for ln in lines:
        chunk = normalize_breaks(ln)
        if "\n" in chunk:
            parts = chunk.split("\n")
        else:
            parts = [chunk]
        for p in parts:
            t = p.strip()
            if t:
                out.append(t)
            elif out and out[-1] != "":
                out.append("")
    while out and out[-1] == "":
        out.pop()
    return out


def normalize_tree(value: Any) -> Any:
    """Recursively normalize strings in nested dict/list structures."""
    if isinstance(value, str):
        return normalize_breaks(value)
    if isinstance(value, list):
        return [normalize_tree(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize_tree(v) for k, v in value.items()}
    return value
