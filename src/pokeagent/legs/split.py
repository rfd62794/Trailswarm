"""split: cut a run's transitions into legs (consecutive presses on one map, ending in the press that changes the map).

Frames: transitions carry no frame counts, so a press that moved costs FRAME_WALK per tile (capped at a 2-tile ledge hop) and
an idle press (turn, menu, text, battle) costs IDLE_FRAMES. On the 2026-11-06 runs (44% of presses move) that averages
~10.5 frames per press, matching the calibration in tools/seg_store.FRAMES_PER_STEP.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from pokeagent.legs.grid import FRAME_WALK

IDLE_FRAMES = 6.0


@dataclass
class Leg:
    run: str
    map: int
    entry: tuple                 # (x, y) first tile on the map
    exit: tuple                  # (x, y) tile of the press that leaves (or the last tile when incomplete)
    button: str                  # the press that leaves the map
    dest: tuple | None           # (map, x, y) arrived at; None when the leg is incomplete
    step0: int                   # transition step number of the first press
    step1: int = 0               # ... and of the last press of the leg
    buttons: list = field(default_factory=list)
    moved: int = 0
    frames: float = 0.0
    complete: bool = False

    @property
    def presses(self) -> int:
        return len(self.buttons)

    @property
    def key(self) -> str:
        return f"{self.map}:{self.entry[0]},{self.entry[1]}>{self.exit[0]},{self.exit[1]}:{self.button}"


def press_frames(row: dict) -> float:
    if not row.get("moved"):
        return IDLE_FRAMES
    a, b = row["from"], row["to"]
    return FRAME_WALK * (min(abs(a[1] - b[1]) + abs(a[2] - b[2]), 2) if a[0] == b[0] else 1) or FRAME_WALK


def split_legs(rows, run: str = "") -> list[Leg]:
    """Legs of one run in order. A leg closes complete on the press that changes the map, or incomplete on a jump in position."""
    legs, cur, prev_to = [], None, None
    for r in rows:
        f, t = r["from"], r["to"]
        if cur is not None and (f[0] != cur.map or tuple(f) != prev_to):
            cur.complete = False
            legs.append(cur)
            cur = None
        if cur is None:
            cur = Leg(run, f[0], (f[1], f[2]), (f[1], f[2]), r["button"], None, int(r.get("step", 0)))
        cur.buttons.append(r["button"])
        cur.step1 = int(r.get("step", cur.step0))
        cur.moved += bool(r.get("moved"))
        cur.frames += press_frames(r)
        cur.exit, cur.button, prev_to = (f[1], f[2]), r["button"], tuple(t)
        if t[0] != f[0]:
            cur.dest, cur.complete = tuple(t), True
            legs.append(cur)
            cur = None
    if cur is not None:
        legs.append(cur)
    return legs


def load_rows(path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # a half-written last line of a live run
    return rows


def efficiency(par_frames: float | None, actual: list[float]) -> float | None:
    """par / best actual (1.0 = perfect; below 1 = wasted frames)."""
    if par_frames is None or not actual or min(actual) <= 0:
        return None
    return par_frames / min(actual)


def median(actual: list[float]) -> float:
    return statistics.median(actual)
