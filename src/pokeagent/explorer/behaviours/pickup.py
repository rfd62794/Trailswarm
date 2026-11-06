"""pickup: grab a nearby item ball (pic 61) while no goal route is more important.

Sits after ``plan_goal`` and before ``frontier``: it only fires while the planner has no
goal-critical route, detours at most ``PICKUP_DETOUR`` tiles to a ball's side, faces it and
presses A; ``advance_dialog`` (earlier in the order) closes the box. A ball that gave no
item text twice in a run is skipped for the rest of that run (``ctx.pickup_tries``, in-memory).

Sits BEFORE ``plan_goal`` in the order: the planner always has a route to the next goal on a known map, so
behind it pickup never got a turn (0 decisions on the ROM). Its own gates keep it off goal-critical moments.
Success is decided from the dialog of THIS press (``ctx.ball_result``, set by press_interact when the box
closes), never from maps.json: Gen 1 hides a collected ball by setting its image index 0xFF (pic 61 and the
position stay), so a ball still live after a "success" counts as a try.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pokeagent.explorer import items
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.behaviours.pickup_approach import approach_plan
from pokeagent.explorer.decisions import goal_stage
from pokeagent.explorer.perceive import DIRS, TILEMAP, TILEMAP_LEN, box_open, box_text

if TYPE_CHECKING:
    from pokeagent.explorer.context import ExplorerContext

PICKUP_DETOUR = 20  # most steps a pickup may cost from here (the named detour budget)
_LAB = 0x28         # Oak's lab: the starter planner owns the balls, and the two left over are not for us
_BOX_WAIT = 160     # frames after the A press to wait for the dialog box (it opens ~50 frames late on the ROM)
_ITEM_WAIT = 64     # more frames, once the box is open, for the "found ITEM!" line to finish printing
_MAX_TRIES = 2      # presses facing a ball that gave no item text before it is skipped this run


def read_box(ctx: "ExplorerContext") -> str | None:
    """The dialog text on screen, or None while no box is open."""
    tm = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
    return box_text(tm) if box_open(tm) else None


def await_item_dialog(ctx: "ExplorerContext", ball: tuple) -> None:
    """Right after the A press: let the game open its box and print the line, then record THIS press's outcome.
    The press returns before the box exists (settle_position only waits for the position), so without this
    the result was read one step too early and a real pickup looked like 'no item text'."""
    waited, item, done = 0, None, False
    while waited < _BOX_WAIT + _ITEM_WAIT and not done:
        text = read_box(ctx)
        if text is None and waited >= _BOX_WAIT:
            break
        item = items.parse_item_text(text) if text else item
        done = bool(text) and "!" in text and item is not None  # the line finished printing ("... found POTION!")
        if not done:
            ctx.emu.tick(8); waited += 8
    ctx.ball_result = (*ball, item) if item else None


class Pickup(BehaviourBase):
    name = "pickup"

    def applies(self, ctx: "ExplorerContext") -> bool:
        if ctx.view.box or ctx.view.battling:
            return False  # dialog/battle behaviours earlier in the order own those steps
        if ctx.pickup_await is not None:
            return True  # a pressed ball owes a result check
        return self._choose(ctx) is not None

    def step(self, ctx: "ExplorerContext") -> Decision | None:
        self._resolve(ctx)
        m = ctx.view.m
        ctx.pickup_gone.update((m, bx, by) for _slot, bx, by in items.hidden_balls(ctx.emu))
        live = {(bx, by) for _slot, bx, by in items.item_balls(ctx.emu)}
        if ctx.pickup_ball is not None and ctx.pickup_ball[1:] not in live:
            ctx.pickup_ball = None  # the committed ball is gone from the sprite table: re-pick below
        plan = self._plan(ctx, ctx.pickup_ball) if ctx.pickup_ball is not None else None
        if plan is None:
            ctx.pickup_ball = None  # the committed ball is gone or unreachable: re-pick below
            plan = self._choose(ctx)
            if plan is None:
                return None
            ctx.pickup_ball = plan["ball"]
        return self._act(ctx, plan)

    def _gated(self, ctx: "ExplorerContext") -> bool:
        """Goals/scenes where a pickup detour is forbidden."""
        goals = ctx.goals()
        if goal_stage(goals) == "deliver_parcel":
            return True  # carrying Oak's parcel: no detours (the planner's rule for training too)
        return ctx.view.m == _LAB  # the whole run: after first_pokemon two starter balls are still on the table

    def _choose(self, ctx: "ExplorerContext") -> dict | None:
        """The cheapest reachable ball on this map: {"ball", "spot", "face", "route", "steps"} or None."""
        if self._gated(ctx):
            return None
        m = ctx.view.m
        best = None
        for _slot, bx, by in items.item_balls(ctx.emu):  # the sprite table is the current map's
            ball = (m, bx, by)
            if ctx.pickup_tries.get(ball, 0) >= _MAX_TRIES or ball in ctx.pickup_gone:
                continue
            plan = self._plan(ctx, ball) or approach_plan(ctx, ball, PICKUP_DETOUR)
            if plan is not None and (best is None or plan["steps"] < best["steps"]):
                best = plan
        return best

    def _plan(self, ctx: "ExplorerContext", ball: tuple) -> dict | None:
        """Route to a tile beside ``ball`` and the facing that looks at it, within PICKUP_DETOUR."""
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        if ball[0] != m:
            return None
        _m, bx, by = ball
        best = None
        for face, (ddx, ddy) in DIRS.items():
            spot = (bx - ddx, by - ddy)  # stand here facing `face`: pos + DIRS[face] == the ball
            route = ctx.mem.route_to(m, x, y, (m, spot[0], spot[1]))
            if route is None:
                continue
            _node, buttons = route
            if len(buttons) > PICKUP_DETOUR:
                continue
            if best is None or len(buttons) < best["steps"]:
                best = {"ball": ball, "spot": spot, "face": face, "route": buttons, "steps": len(buttons)}
        return best

    def _act(self, ctx: "ExplorerContext", plan: dict) -> Decision:
        if "approach" in plan:  # the ball's side tiles are not on the map yet: explore toward it
            ball = plan["ball"]
            ctx.pickup_approach[ball] = ctx.pickup_approach.get(ball, 0) + 1
            return Decision(plan["approach"], "pickup",
                            f"item ball at ({ball[1]},{ball[2]}): exploring toward it (~{plan['steps']} steps)")
        if (ctx.view.x, ctx.view.y) == plan["spot"]:
            if ctx.facing != plan["face"]:
                return Decision(plan["face"], "pickup",
                                f"item ball at ({plan['ball'][1]},{plan['ball'][2]}): turn to face it")
            ctx.pickup_await = plan["ball"]
            ctx.ball_result = None  # only this press's dialog may decide its outcome
            ball = plan["ball"]
            return Decision("A", "pickup", f"item ball at ({ball[1]},{ball[2]}): pressing A to pick it up",
                            after=lambda c, b=ball: await_item_dialog(c, b))
        return Decision(plan["route"][0], "pickup",
                        f"item ball at ({plan['ball'][1]},{plan['ball'][2]}): {len(plan['route'])} steps to its side")

    def _resolve(self, ctx: "ExplorerContext") -> None:
        """The awaited A press is done (the box closed): did THIS press's dialog name an item?"""
        ball = ctx.pickup_await
        if ball is None:
            return
        ctx.pickup_await = None
        ctx.pickup_ball = None
        result, ctx.ball_result = ctx.ball_result, None
        m, bx, by = ball
        item = result[3] if result and result[:3] == ball else None
        still_live = (bx, by) in {(x, y) for _slot, x, y in items.item_balls(ctx.emu)}
        if item and not still_live:
            ctx.pickup_gone.add(ball)
            ctx.log(f"[pickup: the ball at ({bx},{by}) gave {item}]", "res")
            return
        ctx.pickup_tries[ball] = ctx.pickup_tries.get(ball, 0) + 1
        why = f"gave {item} but the sprite is still live" if item else "no item text"
        ctx.log(f"[pickup: {why} from the ball at ({bx},{by}) ({ctx.pickup_tries[ball]}/{_MAX_TRIES})]", "res")
