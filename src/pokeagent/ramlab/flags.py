"""Bit-level analysis of the story-flag block (wEventFlags 0xD747-0xD886): which bit flips where, and what was on screen.

Sources: ram_events records (any record whose diff touches the block) and the 'events' list a run's maps.json
already keeps (per flip: place, tile, text). A flag bit gets a descriptive name from where/what it flipped on.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

FLAG_LO, FLAG_HI = 0xD747, 0xD886
NAMES_PATH = Path(__file__).resolve().parent.parent / "atlas" / "map_names.json"


@dataclass
class FlagBit:
    addr: int
    bit: int
    direction: str                      # "set" | "clear"
    count: int = 0
    places: Counter = field(default_factory=Counter)   # (map, x, y) -> n
    texts: Counter = field(default_factory=Counter)
    runs: set = field(default_factory=set)

    @property
    def key(self) -> str:
        return f"{self.addr:04X}.{self.bit}"


def map_name(mid: int, names: dict | None = None) -> str:
    names = names if names is not None else json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    return names.get(str(mid), f"MAP_{mid:02X}").replace("_", " ").title()


def _bits(before: int, after: int) -> list[tuple[int, str]]:
    return [(b, "set" if after >> b & 1 else "clear") for b in range(8) if (before ^ after) >> b & 1]


def flag_bits(records: list[dict], map_events: list[dict] = ()) -> list[FlagBit]:
    """Aggregate every flipped bit in the block, from records and from maps.json 'events' entries."""
    out: dict[tuple, FlagBit] = {}

    def add(addr: int, before: int, after: int, place: tuple, text: str, run: str) -> None:
        if not FLAG_LO <= addr <= FLAG_HI:
            return
        for bit, direction in _bits(before, after):
            fb = out.setdefault((addr, bit, direction), FlagBit(addr, bit, direction))
            fb.count += 1; fb.places[place] += 1; fb.runs.add(run)
            if text:
                fb.texts[text] += 1

    for r in records:
        for addr, b, a in r["d"]:
            add(addr, b, a, (r["map"], r["x"], r["y"]), r.get("text", ""), r["run"])
    for e in map_events:
        for f in e.get("flags", []):
            add(int(f[0], 16), f[1], f[2], (e["map"], *e.get("at", (0, 0))), e.get("text", ""), str(e.get("run", "maps")))
    return sorted(out.values(), key=lambda f: (f.addr, f.bit, f.direction))


def describe(fb: FlagBit, names: dict | None = None) -> str:
    """'Route 1 (10,12): "Hi! I work at a POKe MART"' from the most common place and text."""
    (mid, x, y), _ = fb.places.most_common(1)[0]
    text = fb.texts.most_common(1)[0][0] if fb.texts else ""
    kind = "trainer beaten" if "for winning" in text else "item/gift" if "received" in text.lower() or " got " in text else ""
    return (f"[{kind}] " if kind else "") + f"{map_name(mid, names)} ({x},{y})" + (f': "{text}"' if text else "")


def by_place(bits: list[FlagBit]) -> dict[tuple, list[str]]:
    """(map, x, y) -> flag keys that flipped there: the Atlas overlay input."""
    out: dict[tuple, list[str]] = {}
    for fb in bits:
        for place in fb.places:
            out.setdefault(place, []).append(f"{fb.key}:{fb.direction}")
    return out
