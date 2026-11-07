"""Grind drills: start on a map, grind its grass for N steps, record the XP gained per step.

The behaviour ``GrindDrill`` (explorer/behaviours/grind_drill.py, asked after heal/restock/items, before the planner): on the drill map, out of battle, it walks to the
nearest grass tile and paces there, so wild fights come at the map's own encounter rate. Battles, healing and the rest stay with the
normal behaviours. ``GrindDrillMonitor`` ends the run after N steps and records the result. The run's meta.json carries
``drill``, so ``grind.observed.fold`` tags its battles goal="drill" and ``grind.refresh`` folds them into the atlas as observed data.
"""
from __future__ import annotations

import time
from pathlib import Path

from pokeagent.legs.drill import append_log, write_meta

GRIND_LOG = Path("runs/legs/grind_drills.jsonl")
DEFAULT_STEPS = 600
class GrindDrillMonitor:
    """Ends the run after ``steps`` and records XP gained per step (party_log's exp total) as drill_result."""

    def __init__(self, map_id: int, steps: int, run_dir: Path, log_path: Path | None = GRIND_LOG, now=time.time, xp_fn=None):
        self.map, self.steps, self.run_dir, self.log_path, self.now = map_id, steps, Path(run_dir), log_path, now
        self.xp_fn = xp_fn or _party_xp
        self.result: dict | None = None
        self.on_map = 0

    def observe(self, ctx, fr) -> bool:
        if self.result is not None:
            return True
        self.on_map += fr.after[0] == self.map
        if ctx.step < self.steps:
            return False
        from pokeagent.grind.atlas import STEPS_PER_MIN
        xp = float(self.xp_fn(ctx))
        per = xp / max(1, ctx.step)
        self.result = {"source": "drill", "kind": "grind", "map": self.map, "steps": ctx.step, "steps_on_map": self.on_map, "xp": xp,
                       "xp_per_step": per, "xp_per_min": per * STEPS_PER_MIN, "battles": ctx.battles, "wins": ctx.battles_won,
                       "lead_level": _level(ctx), "starter": ctx.opts.starter, "run": self.run_dir.name, "t": self.now()}
        try:
            write_meta(self.run_dir, {"drill_result": self.result})
            self.log_path and append_log(self.log_path, self.result)
        except OSError as e:
            ctx.log(f"[grind drill result not written: {e!r}]", "res")
        ctx.done = True
        ctx.log(f"grind drill map {self.map}: {xp:.0f} XP in {ctx.step} steps ({per:.3f}/step), {ctx.battles} battles", "hdr")
        return True


def _party_xp(ctx) -> float:
    from pokeagent.explorer import party_log
    return party_log.of(ctx).exp_total


def _level(ctx) -> int:
    try:
        from pokeagent.explorer.perceive import lead_level
        return lead_level(ctx.emu)
    except Exception:  # noqa: BLE001
        return 0
