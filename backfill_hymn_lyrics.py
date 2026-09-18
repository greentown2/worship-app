# -*- coding: utf-8 -*-
"""
One-time / maintenance backfill: download full 찬송가 lyrics into data/hymns_lyrics.json.

Sunday worship should then run offline from this file — no live scrape required.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from hymn_lookup import (  # noqa: E402
    _fetch_remote_lyrics,
    _finalize_lyrics,
    _looks_like_complete_short_hymn,
    _looks_like_error_lyrics,
    _looks_like_incomplete_stub,
    _lyrics_richness,
    _should_try_remote,
)

HYMN_INDEX_PATH = ROOT / "data" / "hymn_index.json"
HYMN_LYRICS_PATH = ROOT / "data" / "hymns_lyrics.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
            return
        except OSError as exc:
            last_err = exc
            time.sleep(0.4 * (attempt + 1))
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
    # Last resort: direct write
    try:
        path.write_text(payload, encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Failed to save {path}: {exc}") from (last_err or exc)


def _is_solid(lyrics: list[str]) -> bool:
    if not lyrics or _looks_like_error_lyrics(lyrics):
        return False
    if _looks_like_complete_short_hymn(lyrics):
        return True
    if _looks_like_incomplete_stub(lyrics):
        return False
    if _should_try_remote(lyrics) and _lyrics_richness(lyrics) < 200:
        # still accept rich multi-verse even if should_try_remote is conservative
        pass
    return _lyrics_richness(lyrics) >= 80 or (
        len([ln for ln in lyrics if str(ln).strip()]) >= 4
        and not _looks_like_incomplete_stub(lyrics)
    )


def backfill(
    *,
    start: int = 1,
    end: int = 645,
    only_missing: bool = True,
    sleep_s: float = 0.35,
    save_every: int = 5,
) -> dict:
    index = _load_json(HYMN_INDEX_PATH)
    db = _load_json(HYMN_LYRICS_PATH)
    ok = skip = fail = improved = 0

    for num in range(start, end + 1):
        key = str(num)
        title = str(index.get(key) or "").strip() or f"{num}장"
        prev = db.get(key) if isinstance(db.get(key), dict) else None
        prev_lines = list((prev or {}).get("lyrics") or [])

        if only_missing and prev_lines and _is_solid(prev_lines) and not _should_try_remote(prev_lines):
            skip += 1
            continue
        # Also skip solid-enough even if should_try_remote for short doxologies
        if only_missing and prev_lines and _is_solid(prev_lines) and not _looks_like_incomplete_stub(prev_lines):
            # still refresh if very thin numbered hymns
            import re

            verses = len(re.findall(r"(?m)^\s*\d+\s*[\.．、)]\s*", "\n".join(prev_lines)))
            hangul = len(re.findall(r"[가-힣]", "\n".join(prev_lines)))
            if verses >= 3 or (verses == 0 and hangul >= 35) or hangul >= 160:
                skip += 1
                continue

        remote = _fetch_remote_lyrics(num, retries=3)
        time.sleep(sleep_s)
        if not remote:
            fail += 1
            print(f"[{num:03d}] FAIL fetch", flush=True)
            continue

        lyrics = _finalize_lyrics(remote)
        if not _is_solid(lyrics):
            fail += 1
            print(f"[{num:03d}] FAIL quality lines={len(lyrics)}", flush=True)
            continue

        if prev_lines and _lyrics_richness(prev_lines) >= _lyrics_richness(lyrics) and not _looks_like_incomplete_stub(
            prev_lines
        ):
            skip += 1
            continue

        db[key] = {"title": title, "lyrics": lyrics}
        if prev_lines:
            improved += 1
            print(f"[{num:03d}] improved {len(prev_lines)} -> {len(lyrics)}  {title}", flush=True)
        else:
            ok += 1
            print(f"[{num:03d}] saved {len(lyrics)} lines  {title}", flush=True)

        if (ok + improved) % save_every == 0:
            _save_json(HYMN_LYRICS_PATH, db)

    _save_json(HYMN_LYRICS_PATH, db)
    return {"ok": ok, "improved": improved, "skip": skip, "fail": fail, "total": len(db)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Backfill full hymn lyrics into local DB")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=645)
    ap.add_argument("--numbers", type=str, default="", help="Comma-separated hymn numbers to refresh")
    ap.add_argument("--all", action="store_true", help="Re-fetch even if local looks solid")
    ap.add_argument("--sleep", type=float, default=0.35)
    args = ap.parse_args()
    if args.numbers:
        nums = [int(x) for x in re.findall(r"\d+", args.numbers)]
        stats = {"ok": 0, "improved": 0, "skip": 0, "fail": 0, "total": 0}
        for n in nums:
            part = backfill(start=n, end=n, only_missing=False, sleep_s=args.sleep, save_every=1)
            for k in ("ok", "improved", "skip", "fail"):
                stats[k] += part[k]
            stats["total"] = part["total"]
    else:
        stats = backfill(
            start=args.start,
            end=args.end,
            only_missing=not args.all,
            sleep_s=args.sleep,
        )
    print("DONE", stats, flush=True)
    return 0 if stats["fail"] < stats["ok"] + stats["improved"] + stats["skip"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
