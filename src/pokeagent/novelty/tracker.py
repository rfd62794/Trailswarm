"""NoveltyTracker: one per run. Reads the game state after each press, scores features nobody (or few) found, keeps this
run's delta on disk, and runs the discovery detectors. The returned bonus only reaches the explorer-role policies."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from pokeagent.novelty import features as ft
from pokeagent.novelty.discoveries import DiscoveryLog
from pokeagent.novelty.store import load_table, write_delta

STEER_ROLE = "explorer"
TILE_LOG_EVERY = 50  # tiles are logged in batches; every other feature type is logged when found


class NoveltyTracker:
    def __init__(self, shared_path: Path | str, delta_path: Path | str, role: str, run_id: str, *, runs_dir: Path | str = "runs",
                 stage_fn: Callable[[], int | None] | None = None, log: Callable[..., None] | None = None,
                 clock: Callable[[], float] = time.time, read: Callable = ft.read_snapshot) -> None:
        table = load_table(shared_path)
        self.counts, self.stage_table = table["counts"], table["stage"]
        self.maps_known = any(k.startswith("m:") for k in self.counts)
        self.delta_path, self.role, self.run_id = Path(delta_path), role, run_id
        self.found: dict[str, float] = {}
        self.stage: dict[str, int] = {}
        self.seen: set[str] = set()
        self.prev: ft.Snapshot | None = None
        self.stage_fn, self.log, self.clock, self.read = stage_fn, log or (lambda *a, **k: None), clock, read
        self.disc = DiscoveryLog(runs_dir, run_id, role, clock)
        self.total_bonus = 0.0
        self.tiles_new = 0

    @property
    def rewarding(self) -> bool:
        return self.role == STEER_ROLE

    def rarity(self, key: str) -> float:
        """1 for a feature no run has found, falling as 1/sqrt(1 + runs that found it)."""
        return 1.0 / (1 + self.counts.get(key, 0)) ** 0.5

    def bonus(self, key: str) -> float:
        return ft.bonus(key, self.counts.get(key, 0))

    def observe(self, emu, step: int) -> float:
        """Read the state, record new features, flush the delta, run the detectors. Returns this step's novelty bonus
        (0 for a non-explorer role: it still counts and discovers, it is just never paid)."""
        cur = self.read(emu)
        prev, self.prev = self.prev, cur
        keys = ft.features(cur, prev)
        if prev is None:
            self.seen.update(keys)  # the start state is the baseline: nothing in it is a find
            return 0.0
        new = [k for k in dict.fromkeys(keys) if k not in self.seen]
        gain = 0.0
        stage_now = self._stage_now() if prev.flags != cur.flags else None
        if new:
            self.seen.update(new)
            now = self.clock()
            if stage_now is not None:
                for k in (k for k in new if k.startswith("f:")):
                    self.stage[k] = min(stage_now, self.stage.get(k, stage_now))
            for k in new:
                self.found[k] = now
                gain += self.bonus(k)
                self._announce(k)
            write_delta(self.delta_path, self.run_id, self.role, self.found, self.stage)  # flushed per find: a kill loses nothing
        ctx = {"counts": self.counts, "maps_known": self.maps_known, "stage": self.stage_table,
               "seen_species": {int(k[3:]) for k in self.seen if k.startswith("ss:")}, "stage_now": stage_now}
        self.disc.check(prev, cur, step, emu, ctx)
        if not self.rewarding:
            return 0.0
        self.total_bonus += gain
        return gain

    def _stage_now(self):
        if self.stage_fn is None:
            return None
        try:
            return self.stage_fn()
        except Exception:  # noqa: BLE001
            return None

    def _announce(self, key: str) -> None:
        if key.startswith("t:"):
            self.tiles_new += 1
            if self.tiles_new % TILE_LOG_EVERY == 0:
                self.log(f"[novelty: {self.tiles_new} new tiles this run]", "res")
            return
        n = self.counts.get(key, 0)
        self.log(f"[novelty +{self.bonus(key):.2f} {key} ({self.role}; found by {n} earlier run{'' if n == 1 else 's'})]", "res")


def goal_stage(ctx) -> int | None:
    """Index of the furthest campaign goal reached (-1 before the first)."""
    from pokeagent.goals import GOALS
    reached = ctx.goals()
    return max((GOALS.index(g) for g, ok in reached.items() if ok and g in GOALS), default=-1)


def attach(ctx, runs_dir: Path | str = "runs") -> NoveltyTracker:
    """Turn novelty on for this context (the tools call this when --novelty is given)."""
    o = ctx.opts
    ctx.novelty = NoveltyTracker(o.novelty_path, o.novelty_delta or Path(ctx.run_dir) / "novelty_delta.json", o.role, Path(ctx.run_dir).name,
                                 runs_dir=runs_dir, stage_fn=lambda: goal_stage(ctx), log=ctx.log)
    return ctx.novelty
