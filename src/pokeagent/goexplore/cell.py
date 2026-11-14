"""The Go-Explore cell key (plan D2): a coarse, hashable form of "a place the agent really stood".

``(map_id, x // 4, y // 4, goals_reached_count, flag_popcount // 4, level_bucket, party_size)`` -
coarse enough that nearby tiles are one cell, fine enough that real progress splits cells. The flag
and party fields are RAM-only: log-derived cells carry ``None`` there until slice 3 measures them live.
"""
from __future__ import annotations

from typing import NamedTuple

from pokeagent.goals import GOALS
from pokeagent.novelty.features import Snapshot

BLOCK = 4          # tile block edge
FLAG_BUCKET = 4    # popcount // 4
LEVEL_BUCKET = 5   # max party level // 5


class Cell(NamedTuple):
    map_id: int
    bx: int                  # x // BLOCK
    by: int                  # y // BLOCK
    goals: int               # goals_reached_count (ladder prefix length)
    flag4: int | None        # flag_popcount // FLAG_BUCKET; None when unknown (logs)
    lvl5: int | None         # max party level // LEVEL_BUCKET; None when unknown
    party_n: int | None      # party size; None when unknown


def flag_popcount(flags: bytes) -> int:
    return sum(b.bit_count() for b in flags)


def party_bucket(party: tuple) -> tuple[int, int]:
    """(max level // LEVEL_BUCKET, party size); an empty party -> (0, 0)."""
    if not party:
        return (0, 0)
    return max(m[1] for m in party) // LEVEL_BUCKET, len(party)


def goals_reached(stage: str) -> int | None:
    """Ladder prefix length at ``stage``: GOALS.index(stage), len(GOALS) for "done", None otherwise."""
    if stage == "done":
        return len(GOALS)
    try:
        return GOALS.index(stage)
    except ValueError:
        return None


def from_snapshot(s: Snapshot, goals: int) -> Cell:
    """All seven fields from one Snapshot; ``goals`` comes from the caller (a Snapshot has no ladder)."""
    lvl5, party_n = party_bucket(s.party)
    return Cell(s.map, s.x // BLOCK, s.y // BLOCK, goals,
                flag_popcount(s.flags) // FLAG_BUCKET, lvl5, party_n)


def from_log_row(row: dict, goals: int) -> Cell:
    """The position x goals part of the key from a decisions.jsonl row; flag/level are not in logs."""
    return Cell(row["map"], row["x"] // BLOCK, row["y"] // BLOCK, goals, None, None, None)


def cell_id(c: Cell) -> str:
    """Filesystem-safe id like "12.2.1.7.5.3.2" (slice 2 uses it as cells/<id>.state); None -> "-"."""
    return ".".join("-" if v is None else str(v) for v in c)


def parse_id(s: str) -> Cell:
    """Exact inverse of cell_id ("-" -> None)."""
    return Cell(*(None if p == "-" else int(p) for p in s.split(".")))
