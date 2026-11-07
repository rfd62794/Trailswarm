"""Expected HP loss per segment, from battle records (rows [species, level, exp, hp, max_hp] before and after each fight)."""
from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_LOSS = 12        # HP lost per battle when the data is thin
MIN_SAMPLES = 5
BATTLES_PER_SEGMENT = 5  # fights expected between two Marts / Pokecenters
TAIL = 3000              # newest records read


@dataclass
class HpStats:
    by_map: dict = field(default_factory=lambda: defaultdict(list))
    overall: list = field(default_factory=list)


def hp_lost(rec: dict) -> int | None:
    """HP the party lost in one battle; a blackout counts as everything it had (the 'after' row is the healed party)."""
    before, after = rec.get("party_before"), rec.get("party_after")
    if not before or not after:
        return None
    b, a = sum(r[3] for r in before), sum(r[3] for r in after)
    return b if rec.get("won") is False and not rec.get("fled") else max(0, b - a)


def load_hp_loss(path: str | Path = "runs/battles.jsonl", tail: int = TAIL) -> HpStats:
    """Read-only; a missing or damaged file gives empty stats."""
    st = HpStats()
    try:
        with Path(path).open(encoding="utf-8") as fh:
            lines = deque(fh, maxlen=tail)
    except OSError:
        return st
    for ln in lines:
        try:
            rec = json.loads(ln)
            lost = hp_lost(rec)
        except (ValueError, TypeError, IndexError):
            continue
        if lost is not None:
            st.overall.append(lost)
            st.by_map[rec.get("map")].append(lost)
    return st


def expected_battle_loss(stats: HpStats | None, map_id: int | None = None) -> float:
    if stats is not None:
        for sample in (stats.by_map.get(map_id, []), stats.overall):
            if len(sample) >= MIN_SAMPLES:
                return sum(sample) / len(sample)
    return float(DEFAULT_LOSS)


def segment_loss(stats: HpStats | None, party, map_id: int | None = None) -> int:
    """HP the next segment is expected to cost, never more than the party's total max HP (``party`` = battle-record rows)."""
    cap = sum(r[4] for r in party) or 10**9
    return int(min(cap, BATTLES_PER_SEGMENT * expected_battle_loss(stats, map_id)))
