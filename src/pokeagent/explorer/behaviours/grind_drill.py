"""GrindDrill behaviour: on a grind map, out of battle, walk to the nearest grass tile and pace there.

Two drivers (see grind/drill.py and explorer/grind_episode.py): a human ``--drill-grind MAP`` drill, and a
self-started grind episode - the training gate says the trainee is under level and the grind-point ledger
(grind/points.py) names a point. An episode routes to the point's map over the learned world graph, paces its
patch on the ROM grid when one exists (else walks between the encounter-proven tiles), and holds the run on the
episode's map set while it lives."""
from __future__ import annotations

from pokeagent.explorer import grind_episode, story_blockers, train_route
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.perceive import heal_gate_hp, lead_level
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
        if m is not None:
            return (ctx.view.m == m and not ctx.view.box and not ctx.view.battling
                    and trainee_check(ctx).ok)   # a drill never starts with a fainted trainee (pure read; StatusCare acts)
        if ctx.view.box or ctx.view.battling:
            return False
        # Pure read (PR #165 review): the episode's start/finish/save work lives in the engine tick
        # (grind_episode.update), never in applies() - here we only look: an episode is live, or the
        # cheap under-level flag says one could start this step.
        return (grind_episode.active(ctx) is not None
                or 0 < lead_level(ctx.emu) < getattr(ctx, "train_need", 0))

    def step(self, ctx) -> Decision | None:
        ep = grind_episode.active(ctx)
        if getattr(ctx.opts, "drill_grind", None) is None:
            return self._episode_step(ctx, ep) if ep is not None else None  # under-level but no live
            # episode (cooldown, no point, gated): pass through to the rest of the selector
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

    def _episode_step(self, ctx, ep: dict) -> Decision | None:
        """Route to the episode's point, then pace its grass. The boundary guard (train_route.stay_on_route
        on the episode's map set) keeps every other behaviour inside it meanwhile."""
        pt, pos = ep["point"], (ctx.view.m, ctx.view.x, ctx.view.y)
        hp, mx = heal_gate_hp(ctx.emu)
        if pos[0] != pt.map_id:
            r = train_route.step(ctx.mem.data["maps"], pos, frozenset(ctx.mem.temp_blocked) | story_blockers.blocked_tiles(ctx), hp, mx, target=pt.map_id, patch=pt.patch)
            return Decision(r[0], "grind_drill", f"grind episode: {r[1]}") if r else None
        g = self._grid(ctx, pt.map_id)
        if g is not None:
            xy = (ctx.view.x, ctx.view.y)
            st = ctx.__dict__.setdefault("_grind_state", {"heading": "RIGHT"})
            if g.inside(*xy) and g.grass[xy[1], xy[0]]:
                r = pace_button(g, xy, st["heading"])
                if r:
                    st["heading"] = r[1]
                    return Decision(r[0], "grind_drill", f"grind episode: pacing the patch at {xy}")
                return None
            route = to_grass(g, xy)
            if route:
                return Decision(route[0], "grind_drill", f"grind episode: walking to the patch ({len(route)} steps)")
        return self._patch_step(ctx, pt)

    def _patch_step(self, ctx, pt) -> Decision | None:
        """No ROM grid (or none needed): walk to the least-visited encounter-proven grass tile of the patch."""
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        tiles = [(t[0], t[1]) for t in pt.patch if (t[0], t[1]) != (x, y)]
        if not tiles:
            return None
        visited = ctx.mem.m(m).get("visited", {})
        tx, ty = min(tiles, key=lambda t: (visited.get(f"{t[0]},{t[1]}", 0), abs(t[0] - x) + abs(t[1] - y)))
        r = ctx.mem.route_to(m, x, y, (m, tx, ty))
        return Decision(r[1][0], "grind_drill", f"grind episode: to the patch tile ({tx},{ty})") if r and r[1] else None
