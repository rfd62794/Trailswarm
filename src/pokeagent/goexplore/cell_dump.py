"""Go-Explore slice 3 (plan D5), goexplore/cell_dump.py: harvest mid-run states into the slice-2 archive.

``attach`` wraps ``engine.step`` on the demo's Engine instance (tools/explore_demo.py). Every
``CHECK_EVERY`` ctx steps one ``read_snapshot`` gives the whole cell key - block, goals reached,
flag-popcount bucket, party level bucket, party size - and a new or strictly better cell gets a
``cells/<cid>.state`` plus its ``statefp`` sidecar. An observer never stops a run: a failure inside
``tick`` is logged and swallowed, and with the flag off no code here runs at all.
"""
from __future__ import annotations

from pathlib import Path

from pokeagent import statefp
from pokeagent.explorer.decisions import goal_stage
from pokeagent.goexplore import store
from pokeagent.goexplore.archive import Entry
from pokeagent.goexplore.cell import cell_id, from_snapshot, goals_reached
from pokeagent.novelty.features import read_snapshot

CHECK_EVERY = 10     # steps between cell checks; also the "every K steps" save cadence (a check saves only a new or better cell)


class Harvester:
    """The periodic cell harvest of one run; ``attach`` builds it, the step wrapper calls ``tick``."""

    def __init__(self, ctx, root: Path, every: int = CHECK_EVERY, steps_offset: int = 0,
                 parent: str | None = None) -> None:
        self.ctx, self.root, self.every = ctx, Path(root), every
        self.steps_offset = steps_offset  # steps the driver already spent before this run returned
        self.parent = parent              # cid of the cell this run was returned from (slice 4)
        self.archive = store.load(self.root)
        self.last_check: int | None = None
        self.prev: str | None = None      # last distinct cid this run was checked in

    def tick(self) -> str | None:
        """The cid saved this call, else None. NEVER raises: an observer must not stop a run."""
        ctx = self.ctx
        try:
            if self.last_check is not None and ctx.step - self.last_check < self.every:
                return None
            self.last_check = ctx.step
            snap = read_snapshot(ctx.emu)
            goals = goals_reached(goal_stage(ctx.goals()))
            if goals is None:
                goals = len(ctx.goal_steps)
            cid = cell_id(from_snapshot(snap, goals))
            steps = ctx.step + self.steps_offset
            old = self.archive.entries.get(cid)
            if old is not None and (goals, -steps) <= (old.goals, -old.steps):
                self.prev = cid       # state files are ~175 KB: never write one offer() would reject
                return None
            parent = old.parent if old is not None and cid == self.prev else (self.prev or self.parent)
            self.prev = cid
            rel = store.add_state(ctx.emu, self.root, cid, ctx.run_dir.name,
                                  inherit=ctx.opts.state_path or None)
            state = self.root / rel   # add_state returns "cells/<cid>.state" (forward slashes)
            self.archive.offer(Entry(cid, rel, goals, steps,
                                     statefp.party_hp_fraction(statefp.read(state) or {}),
                                     parent=parent, lineage=statefp.lineage(state)))
            store.evict(self.archive, self.root)
            store.save(self.archive, self.root)
            return cid
        except Exception as exc:  # noqa: BLE001  like Engine._note_novelty: a dump failure never stops a run
            ctx.log(f"[cell dump skipped: {exc!r}]", "res")
            return None


def attach(ctx, engine, root, every: int = CHECK_EVERY, **kw) -> Harvester:
    """Wrap ``engine.step`` with a Harvester over the archive at ``root``; returns the harvester.

    ``store.load`` runs now so a corrupt archive fails loud at start, and a ``synthetic`` start
    state is refused (plan D8; ``promoted`` and ``organic`` are fine, an empty state_path skips
    the check). The wrapper returns exactly what the original ``step`` returned."""
    root = Path(root)
    store.load(root)
    start = getattr(ctx.opts, "state_path", "") or ""
    if start and statefp.lineage(Path(start)) == "synthetic":
        raise ValueError(f"cell dump refuses a synthetic start state: {start}")
    harvester = Harvester(ctx, root, every, **kw)
    orig = engine.step

    def step():
        d = orig()
        harvester.tick()
        return d

    engine.step = step
    return harvester
