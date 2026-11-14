"""The Go-Explore cell archive (plan D3): which saved state represents each cell.

Pure metadata: no I/O here. ``score`` ranks two states of one cell - more goals reached, then fewer
total emulator steps, then higher party HP. A strictly better offer replaces the stored entry and
keeps ``n_seen``; equal or worse is rejected. Eviction lives in ``store`` (it deletes files).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass
class Entry:
    cid: str                    # cell_id(...) of the cell
    state: str                  # path relative to the archive root, e.g. "cells/<cid>.state"
    goals: int                  # goals reached when the state was written
    steps: int                  # total emulator steps to get here
    hp: float = 0.0             # party HP fraction (statefp.party_hp_fraction)
    n_seen: int = 0             # times select chose this cell
    novelty: float = 0.0        # sum of features.weight() of keys first seen in the producing run (D3); NOT capped
    parent: str | None = None   # cid of the cell this state was reached from
    lineage: str = "organic"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Entry":
        """Unknown keys are ignored; missing optional fields take their defaults."""
        known = {f.name for f in fields(Entry)}
        return Entry(**{k: v for k, v in d.items() if k in known})


def score(e: Entry) -> tuple[int, int, float]:
    """Bigger is better: more goals, then FEWER steps, then higher HP."""
    return (e.goals, -e.steps, e.hp)


class Archive:
    def __init__(self, cap: int = 1000) -> None:
        self.cap = cap
        self.entries: dict[str, Entry] = {}

    def __len__(self) -> int:
        return len(self.entries)

    def offer(self, e: Entry) -> bool:
        """Insert a new cell, or replace the stored state iff ``score(new) > score(old)`` (strict).

        The replacement keeps the old ``n_seen``. Never evicts, never raises on a full archive."""
        old = self.entries.get(e.cid)
        if old is None:
            self.entries[e.cid] = e
            return True
        if score(e) <= score(old):
            return False
        e.n_seen = old.n_seen
        self.entries[e.cid] = e
        return True

    def mark_seen(self, cid: str) -> None:
        """n_seen += 1; an unknown cid is ignored."""
        e = self.entries.get(cid)
        if e is not None:
            e.n_seen += 1

    def children_of(self, cid: str) -> list[str]:
        """Sorted cids whose entry's parent is ``cid``."""
        return sorted(c for c, e in self.entries.items() if e.parent == cid)

    def best_per_goals(self) -> set[str]:
        """For each distinct ``goals`` count, the cid with the max score (ties: the smaller cid)."""
        best: dict[int, tuple[tuple[int, int, float], str]] = {}
        for cid, e in self.entries.items():
            cur = best.get(e.goals)
            if cur is None or score(e) > cur[0] or (score(e) == cur[0] and cid < cur[1]):
                best[e.goals] = (score(e), cid)
        return {cid for _, cid in best.values()}
