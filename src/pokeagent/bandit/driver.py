"""BanditDriver: the per-run state. Chooses an arm at a decision point, tracks open episodes, owns the run's delta.

``ctx.bandit`` is None unless the run was started with the flag; every hook returns the Explorer's own answer then.
"""
from __future__ import annotations

import random
import uuid
from pathlib import Path
from typing import Callable

from pokeagent.bandit import reward as rw
from pokeagent.bandit.points import ARMS
from pokeagent.bandit.store import load_cells, write_delta
from pokeagent.bandit.table import choose, record



class BanditDriver:
    def __init__(self, shared_path: Path | str, delta_path: Path | str, seed: int | None = None) -> None:
        self.cells = load_cells(shared_path)  # shared table at start; this run's episodes are added as they close
        self.delta: dict = {}
        self.delta_path = Path(delta_path)
        self.run_id = uuid.uuid4().hex
        self.rng = random.Random(seed)  # its own stream: the Explorer's random draws are untouched
        self.open: list[rw.Episode] = []
        self.sticky: dict[str, tuple[object, str, rw.Episode]] = {}  # point -> (situation tag, arm, episode)
        self.notes: list[tuple[str, str, bool]] = []  # (point, arm, deviated) consulted this step
        self.closed = 0
        self._blackouts = 0

    def decide(self, point: str, tag: object, key: Callable[[], str], default: str) -> str:
        """The arm for this situation: the same one while ``tag`` holds, a fresh Thompson draw (and a new episode) otherwise."""
        held = self.sticky.get(point)
        if held is not None and held[0] == tag:
            arm, ep = held[1], held[2]
        else:
            k = key()
            arm = choose(self.cells, k, ARMS[point], default, self.rng)
            ep = rw.Episode(point, k, arm, default)
            self.open.append(ep)
            self.sticky[point] = (tag, arm, ep)
        self.notes.append((point, arm, arm != ep.default))
        return arm

    def clear(self, point: str) -> None:
        self.sticky.pop(point, None)

    def begin_step(self) -> None:
        self.notes.clear()

    def tag(self, rec: dict) -> dict:
        """The decision line with driver (bandit when it deviated from the Explorer's default) and arm."""
        dev = any(d for _, _, d in self.notes)
        arm = ",".join(f"{p}={a}" for p, a, _ in self.notes) or None
        return {**rec, "driver": "bandit" if dev else "explorer", "arm": arm}

    def after_press(self, ctx, rec: dict, tossed: bool) -> list[dict]:
        """Feed one press (and what it caused) to the open episodes; returns extra event lines for the log."""
        events: list[dict] = []
        if tossed:
            events.append({**rec, "event": "item_tossed", "outcome": "item_tossed"})
        if ctx.blackouts_row > self._blackouts:
            events.append({"event": "blackout", "step": ctx.step, "map": rec["map"]})
        self._blackouts = ctx.blackouts_row
        for r in [rec, *events]:
            for ep in list(self.open):
                if ep.add(r):
                    self._close(ep)
        return [e for e in events if e.get("event") == "blackout"]  # the engine already writes item_tossed itself

    def _close(self, ep: rw.Episode) -> None:
        self.open.remove(ep)
        record(self.cells, ep.key, ep.arm, ep.reward)
        record(self.delta, ep.key, ep.arm, ep.reward)
        held = self.sticky.get(ep.point)
        if held is not None and held[2] is ep:
            del self.sticky[ep.point]
        self.closed += 1
        self.save()  # every close: the swarm kills stalled agents, so a kill must lose only the open episodes

    def save(self) -> None:
        """Write this run's delta (cumulative for the run, written atomically; the merge replaces the run's earlier contribution). Unfinished episodes are dropped."""
        write_delta(self.delta_path, self.run_id, self.delta)


def attach(ctx, shared_path: str, delta_path: str | None = None, seed: int | None = None) -> BanditDriver:
    """Turn the bandit on for this context (the tools call this when --bandit is given)."""
    ctx.bandit = BanditDriver(shared_path, delta_path or Path(ctx.run_dir) / "bandit_delta.json", seed)
    return ctx.bandit
