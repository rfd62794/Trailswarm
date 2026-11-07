"""Training progress: the one rule for "the party is getting stronger", shared by every stall decision.

A run that is grinding (the gyarados stage raises a Magikarp for thousands of presses) reaches no new goal and no new
tile, so the tile/goal stall rule alone would kill it. An experience gain or a level gain is progress the same way a new
tile is. Pure: it reads ``levels.jsonl`` rows (``party`` = ``[[species, level, exp, hp, max_hp], ...]``).
"""
from __future__ import annotations

Marks = dict[int, tuple[int, int]]  # species -> best (level, exp) in the party


def marks(party) -> Marks:
    out: Marks = {}
    for m in party or ():
        try:
            sp, level, exp = int(m[0]), int(m[1]), int(m[2])
        except (IndexError, TypeError, ValueError):
            continue
        out[sp] = max(out.get(sp, (0, 0)), (level, exp))
    return out


def gained(before: Marks, after: Marks) -> bool:
    """A species that was already in the party now has more experience or a higher level (a mon joining is not training)."""
    return any(sp in before and after[sp] > before[sp] for sp in after)


def training_progress(rows: list[dict], since_step: int = -1) -> bool:
    """True when a levels row after ``since_step`` shows an XP or level gain over the row before it."""
    prev: Marks | None = None
    for r in rows:
        cur = marks(r.get("party"))
        if prev is not None and (r.get("step") or 0) > since_step and gained(prev, cur):
            return True
        prev = cur
    return False
