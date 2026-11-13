"""Provenance sidecar: which games OBSERVED each fact. Absent entry = the founding game, Red."""
from __future__ import annotations

import json
from pathlib import Path

FOUNDER = "pokemon-red"
SECTIONS = ("visited", "warps", "blocked", "jumps", "npcs")


def provenance_path(shared: str | Path) -> Path:
    return Path(shared).parent / "family_provenance.json"


def load(shared: str | Path) -> dict:
    try:
        doc = json.loads(provenance_path(shared).read_text(encoding="utf-8"))
        if isinstance(doc.get("facts"), dict):
            return doc
    except (OSError, ValueError, AttributeError):
        pass
    return {"version": 1, "facts": {}}


def save(shared: str | Path, doc: dict) -> None:
    p = provenance_path(shared)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def observers(doc: dict, fact: str) -> list[str]:
    """Games that observed ``fact`` ("<map>/<section>/<key>"); an unrecorded fact is Red's."""
    return list(doc["facts"].get(fact) or [FOUNDER])


def fact_keys(map_doc: dict) -> list[tuple[str, str]]:
    """(section, key) for every provenance-tracked fact of one map record."""
    out = []
    for sec in SECTIONS:
        v = map_doc.get(sec) or []
        out += [(sec, str(k)) for k in v]
    return out


def record(doc: dict, mid: str, sec: str, key: str, game_key: str, was_in_shared: bool) -> bool:
    """Add ``game_key`` as an observer; True when the entry changed."""
    f = f"{mid}/{sec}/{key}"
    cur = doc["facts"].get(f)
    if cur is None:
        new = [FOUNDER] if was_in_shared else []
        new = new + [game_key] if game_key not in new else new
    elif game_key in cur:
        return False
    else:
        new = cur + [game_key]
    doc["facts"][f] = new
    return True
