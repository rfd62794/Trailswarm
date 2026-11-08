"""GrindDrill behaviour: on the grind-drill map, out of battle, walk to the nearest grass tile and pace there (see grind/drill.py)."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.trainee_gate import trainee_check
from pokeagent.legs.grass import pace_button, to_grass


class GrindDrill(BehaviourBase):
    name = "grind_drill"

    def __init__(self, grids=None) -> None:
        self._grids = grids   # test hook: map id -> Grid

    def _grid(self, ctx, m: int):
        if self._grids is not None:
            return self._grids(m)
        get = ctx.__dict__.get("_grind_grids")
        if get is None:
            from pokeagent.legs.grid import rom_grids
            get = ctx.__dict__["_grind_grids"] = rom_grids() or (lambda _m: None)
        return get(m)

    def applies(self, ctx) -> bool:
        m = getattr(ctx.opts, "drill_grind", None)
        return (m is not None and ctx.view.m == m and not ctx.view.box and not ctx.view.battling
                and trainee_check(ctx).ok)   # a drill never starts with a fainted trainee (pure read; StatusCare acts)

    def step(self, ctx) -> Decision | None:
        g = self._grid(ctx, ctx.view.m)
        if g is None:
            return None
        pos = (ctx.view.x, ctx.view.y)
        st = ctx.__dict__.setdefault("_grind_state", {"heading": "RIGHT"})
        if g.inside(*pos) and g.grass[pos[1], pos[0]]:
            r = pace_button(g, pos, st["heading"])
            if r:
                st["heading"] = r[1]
                return Decision(r[0], "grind_drill", f"grind drill: pacing in the grass at {pos}")
            return None
        route = to_grass(g, pos)
        return Decision(route[0], "grind_drill", f"grind drill: walking to the nearest grass ({len(route)} steps)") if route else None
