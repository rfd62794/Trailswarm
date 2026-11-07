"""Progress watchdog for swarm agents: spot an agent that is alive but stuck, so its slot can be freed and refilled.

An agent is STALLED when (a) it has made no new transition for HUNG_S seconds (hung; the clock starts at its FIRST transition,
and START_GRACE_S covers the time before one exists), or (b) over its last
WINDOW_PRESSES presses it reached no new goal AND fewer than MIN_NEW_TILES tiles it had not visited before
(a stuck loop, e.g. mashing A on Route 3). Trainers are exempt from (b): standing still to level up is their job. Any run
that gains experience or a level (levels.jsonl, via pokeagent.training_progress) counts that as progress too: the gyarados
stage grinds a Magikarp for thousands of presses with no new tile or goal.
It reads the agent's own runs/explore-*/transitions.jsonl (found by seed), never the agent process.
A run under a Claude lease (``claude_hold.json`` in its run dir, written by the agent) is never stalled: the check is skipped
(``skipped == "claude hold"``, which the swarm logs) and the clocks restart, so it is not killed the moment the lease ends.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.intervene.lease import lease_active  # noqa: E402  (a Claude lease on a run: do not kill it)
from pokeagent import training_progress as tp  # noqa: E402  (XP / level gains count as progress, like a new tile)

WINDOW_PRESSES = 600
DUNGEON_WINDOW_PRESSES = 1500  # caves: long fights and back-tracking between ladders are progress, not a stuck loop
MIN_NEW_TILES = 6
HUNG_S = 120.0
START_GRACE_S = 180.0  # before the first transition: ROM / checkpoint load, run dir not created yet
WATCH_S = 15.0


def find_run_dir(root: Path, seed: int, since_wall: float) -> Path | None:
    """The run dir this agent made: meta.json carries its seed, and it is newer than the slot's start."""
    for d in sorted((Path(root) / "runs").glob("explore-*"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            if d.stat().st_mtime < since_wall - 5 or json.loads((d / "meta.json").read_text()).get("seed") != seed:
                continue
        except (OSError, ValueError):
            continue
        return d
    return None


class ProgressWatch:
    def __init__(self, root: Path, seed: int, trainer: bool = False, since_wall: float | None = None,
                 clock: Callable[[], float] = time.monotonic, window: int = WINDOW_PRESSES,
                 min_new: int = MIN_NEW_TILES, hung_s: float = HUNG_S, grace_s: float = START_GRACE_S):
        self.root, self.seed, self.trainer, self.clock = Path(root), seed, trainer, clock
        self.since = time.time() if since_wall is None else since_wall
        self.window, self.min_new, self.hung_s, self.grace_s = window, min_new, hung_s, grace_s
        self.run_dir: Path | None = None
        self.offset = self.presses = self.goals_seen = self.goal_at = self.train_at = 0
        self.lv_offset = 0
        self.lv_marks: tp.Marks | None = None
        self.first_seen: dict[tuple, int] = {}
        self.last_pos: list | None = None
        self.born = self.last_growth = clock()
        self.skipped = ""  # why the last check() did not judge the run ("" = it did)

    def _read_new(self) -> None:
        path = self.run_dir / "transitions.jsonl"
        try:
            with open(path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except OSError:
            return
        end = chunk.rfind(b"\n") + 1  # only whole lines; a half-written one waits for the next look
        if end == 0:
            return
        self.offset += end
        self.last_growth = self.clock()
        for line in chunk[:end].splitlines():
            try:
                to = json.loads(line)["to"]
            except (ValueError, KeyError, TypeError):
                continue
            self.presses += 1
            self.last_pos = to
            self.first_seen.setdefault(tuple(to), self.presses)

    def _read_levels(self) -> None:
        """New levels.jsonl rows (written on every battle end / level change): an XP or level gain is progress."""
        try:
            with open(self.run_dir / "levels.jsonl", "rb") as f:
                f.seek(self.lv_offset)
                chunk = f.read()
        except OSError:
            return
        end = chunk.rfind(b"\n") + 1
        self.lv_offset += end
        for line in chunk[:end].splitlines():
            try:
                cur = tp.marks(json.loads(line).get("party"))
            except (ValueError, AttributeError):
                continue
            if self.lv_marks is not None and tp.gained(self.lv_marks, cur):
                self.train_at = self.presses
            self.lv_marks = cur

    def _goal_count(self) -> int:
        """Goals this run reached: one line per goal in its own goal_frames.jsonl (written the moment a goal lands)."""
        try:
            with open(self.run_dir / "goal_frames.jsonl", "rb") as f:
                return sum(1 for line in f if line.strip())
        except OSError:
            return self.goals_seen

    def window_now(self) -> int:
        """The stall window for where the agent is now: longer inside dungeons (never shorter than the configured one)."""
        return max(self.window, DUNGEON_WINDOW_PRESSES) if _in_dungeon(self.last_pos) else self.window

    def check(self) -> str | None:
        """None while healthy, else a one-line reason."""
        if self.run_dir is None:
            self.run_dir = find_run_dir(self.root, self.seed, self.since)
        if self.run_dir is not None:
            self._read_new()
            self._read_levels()
            goals = self._goal_count()
            if goals > self.goals_seen:
                self.goals_seen, self.goal_at = goals, self.presses
        self.skipped = ""
        if self.run_dir is not None and lease_active(self.run_dir):
            self.skipped = "claude hold"
            self.born = self.last_growth = self.clock()
            return None
        if self.presses == 0:
            waited = self.clock() - self.born
            if waited > self.grace_s:
                return f"hung: no first transition after {waited:.0f}s"
            return None
        idle = self.clock() - self.last_growth
        if idle > self.hung_s:
            return f"hung: no new transition for {idle:.0f}s"
        window = self.window_now()
        if self.trainer or self.presses < window or self.presses - max(self.goal_at, self.train_at) < window:
            return None
        new = sum(1 for i in self.first_seen.values() if i > self.presses - window)
        if new < self.min_new:
            return f"no new goal and only {new} new tiles in the last {window} presses"
        return None


def _in_dungeon(pos) -> bool:
    try:
        from pokeagent.explorer.world import DUNGEON_MAPS
    except ImportError:  # never let the watchdog crash the supervisor tick: fall back to the normal window
        return False
    return bool(pos) and pos[0] in DUNGEON_MAPS


def record_stall(swarm_dir: Path, slot: int, seed: int, reason: str, watch: ProgressWatch | None) -> None:
    swarm_dir.mkdir(parents=True, exist_ok=True)
    row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "slot": slot, "seed": seed, "reason": reason,
           "pos": watch.last_pos if watch else None, "presses": watch.presses if watch else 0,
           "run": watch.run_dir.name if watch and watch.run_dir else None}
    with open(swarm_dir / "stalls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
