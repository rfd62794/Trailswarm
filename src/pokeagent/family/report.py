"""The disagreement report: JSON lines in family_disagreements.jsonl, de-duplicated."""
from __future__ import annotations

import json
import time
from pathlib import Path


def report_path(shared: str | Path) -> Path:
    return Path(shared).parent / "family_disagreements.jsonl"


def _ident(r: dict) -> tuple:
    return (r["game"], r["map"], r["section"], r["key"], json.dumps(r["overlay"], sort_keys=True))


def append_new(shared: str | Path, rows: list[dict]) -> int:
    """Append rows not already on file (keyed on game, map, section, key, overlay value); returns how many."""
    p = report_path(shared)
    seen = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(_ident(json.loads(line)))
            except (ValueError, KeyError):
                pass
    fresh = []
    for r in rows:
        if _ident(r) not in seen:
            seen.add(_ident(r))
            fresh.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **r})
    if fresh:
        with p.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(r, sort_keys=True) + "\n" for r in fresh)
    return len(fresh)
