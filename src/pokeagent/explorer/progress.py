"""Progress, not just success: the per-step signal that a press changed something worth changing.

A stall guard can only count presses; it cannot tell "the agent is grinding usefully" from "it is bumping
the same NPC forever". ``progress_reasons`` is the one rule for "this press made progress": a new tile, a new
map, a story flag, XP/level, a goal, money, a bag change, a battle that ended, or a party heal (a nurse visit
is useful work with no other trace, so ``hp`` joined the coordinator's list). Pure, no pixels: the signals
come from ``novelty.features`` snapshots and the map memory's visited table.

``ProgressTracker`` counts presses since the last progress (``ctx.steps_since_progress`` mirrors it).
``ProgressLog`` writes ``progress.jsonl`` in the run dir: one row per progress event plus a heartbeat every
PROGRESS_LOG_EVERY steps while nothing happens. Write failures are swallowed once; a run never dies of logging.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.novelty import features
from pokeagent.novelty.features import Snapshot
from pokeagent.training_progress import gained, marks

PROGRESS_LOG_EVERY = 100        # untuned first value: steps between heartbeat rows when nothing new happened

REASONS = ("tile", "map", "flag", "xp", "level", "goal", "money", "item", "battle", "hp")


def progress_reasons(prev: Snapshot | None, cur: Snapshot, new_tile: bool, goals_before: int, goals_after: int,
                     battle_ended: bool) -> list[str]:
    """Every reason this press made progress ([] = none). Order follows REASONS."""
    out: list[str] = []
    if new_tile:
        out.append("tile")
    if prev is not None:
        if cur.map != prev.map:
            out.append("map")
        if features.flag_bits(cur.flags, prev.flags):
            out.append("flag")
        before, after = marks(prev.party), marks(cur.party)
        if gained(before, after):
            out.append("xp")
            if any(sp in before and after[sp][0] > before[sp][0] for sp in after):
                out.append("level")
        if cur.money != prev.money:
            out.append("money")
        if dict(cur.bag) != dict(prev.bag):
            out.append("item")
        if cur.hp > prev.hp:
            out.append("hp")
    if goals_after > goals_before:
        out.append("goal")
    if battle_ended:
        out.append("battle")
    return out


class ProgressTracker:
    """Counts presses since the last progress; resets on any reason."""

    def __init__(self) -> None:
        self.steps_since = 0

    def observe(self, step: int, prev: Snapshot | None, cur: Snapshot, new_tile: bool, goals_before: int,
                goals_after: int, battle_ended: bool) -> list[str]:
        reasons = progress_reasons(prev, cur, new_tile, goals_before, goals_after, battle_ended)
        self.steps_since = 0 if reasons else self.steps_since + 1
        return reasons


class ProgressLog:
    """``<run_dir>/progress.jsonl``: a row per progress event plus a heartbeat while barren. Never raises."""

    def __init__(self, path: Path | str, log=lambda text, tag=None: None) -> None:
        self.path, self.log = Path(path), log
        self._fh = None
        self._failed = False

    def event(self, step: int, frame: int | None, reasons: list[str], since: int) -> None:
        self._write({"step": step, "frame": frame, "reasons": list(reasons), "since": since})

    def heartbeat(self, step: int, since: int) -> None:
        self._write({"step": step, "reasons": [], "since": since})

    def _write(self, row: dict) -> None:
        if self._failed:
            return
        try:
            if self._fh is None:
                self._fh = self.path.open("a", encoding="utf-8")
            self._fh.write(json.dumps(row) + "\n")
            self._fh.flush()
        except OSError as exc:
            self._failed = True  # one log line, then silence: a run must never stop for its own telemetry
            self.log(f"[progress log off: {exc!r}]", "res")

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
