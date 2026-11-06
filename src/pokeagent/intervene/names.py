"""Human names for ids: maps (atlas/map_names.json), items and species (the cartridge KB, when present)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pokeagent.knowledge.kb import ROM_KB

_MAP_NAMES = Path(__file__).resolve().parents[1] / "atlas" / "map_names.json"


@lru_cache(maxsize=1)
def _maps() -> dict[str, str]:
    try:
        return json.loads(_MAP_NAMES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def norm(text) -> str:
    """Names compare without case or punctuation ('MT_MOON_B2F' == 'Mt Moon B2F')."""
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


def pretty(raw: str) -> str:
    """'MT_MOON_B2F' -> 'Mt Moon B2F' (short tokens with a digit, like B2F or 1F, stay upper case)."""
    words = [w if (len(w) <= 3 and any(c.isdigit() for c in w)) else w.capitalize() for w in raw.split("_") if w]
    return " ".join(words)


def map_name(mid) -> str:
    raw = _maps().get(str(mid))
    return pretty(raw) if raw else f"map {mid}"


def map_id(name) -> int | None:
    """A map id from an int, '0x3B', a digit string or a (pretty or raw) name; None when unknown."""
    s = str(name).strip()
    if re.fullmatch(r"0x[0-9a-fA-F]+", s):
        return int(s, 16)
    if s.isdigit():
        return int(s)
    key = norm(s)
    return next((int(i) for i, raw in _maps().items() if norm(raw) == key), None)


def item_name(item_id: int) -> str:
    rec = ((ROM_KB or {}).get("items") or {}).get(str(item_id))
    return str(rec["name"]) if rec else f"item 0x{item_id:02X}"


def item_id(name) -> int | None:
    key = norm(name)
    for i, rec in ((ROM_KB or {}).get("items") or {}).items():
        if norm(rec["name"]) == key or norm(rec["name"].replace("�", "E")) == key:
            return int(i)
    return None


def species_name(internal_id: int) -> str:
    if not internal_id:
        return "?"  # battle data not loaded yet (the first frames of a fight)
    return str(((ROM_KB or {}).get("name_of_internal") or {}).get(str(internal_id), f"#{internal_id}"))
