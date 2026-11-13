"""A game's overlay of the shared maps doc, and the overlay-first read."""
from __future__ import annotations

import copy
import json
from pathlib import Path


def overlay_path(shared: str | Path, game_key: str) -> Path:
    return Path(shared).parent / "overlay" / game_key / "maps.json"


def load_overlay(shared: str | Path, game_key: str) -> dict:
    try:
        d = json.loads(overlay_path(shared, game_key).read_text(encoding="utf-8"))
        return d if isinstance(d.get("maps"), dict) else {"maps": {}}
    except (OSError, ValueError, AttributeError):
        return {"maps": {}}


def save_overlay(shared: str | Path, game_key: str, doc: dict) -> None:
    p = overlay_path(shared, game_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def effective_memory(shared: dict, overlay: dict | None) -> dict:
    """Deep copy of ``shared`` with the overlay applied: warps/jumps/npcs replace; blocked = (shared + overlay
    blocked) minus overlay ``blocked_not``. Empty/None overlay gives an equal copy."""
    out = copy.deepcopy(shared)
    for mid, o in ((overlay or {}).get("maps") or {}).items():
        m = out.setdefault("maps", {}).setdefault(mid, {})
        for sec in ("warps", "jumps", "npcs"):
            if o.get(sec):
                m.setdefault(sec, {}).update(copy.deepcopy(o[sec]))
        if o.get("blocked") or o.get("blocked_not"):
            gone = set(o.get("blocked_not") or [])
            b = list(m.get("blocked") or [])
            b += [e for e in (o.get("blocked") or []) if e not in b]
            m["blocked"] = [e for e in b if e not in gone]
    return out
