"""abra_hunt: while catch_abra is open under --build abra, walk to the grass where Abra lives.

Sibling of learner_hunt.py (same applies/step shape over the learned world graph). The target is the
nearest grass map whose table holds ABRA - Route 24 (0x23, 15.2%/encounter) over Route 25 (0x24) at
equal distance. On the target map it arms ``ctx.hunt_grass`` so frontier seeks grass; the Catch
behaviour throws on turn 1 (knowledge.flee_catch) and catch_wanted's build want keeps the target
wanted. Fewer than BALLS_MIN balls in the bag sends it shopping first: it arms a restock trip
(want=Balls) and yields - the Restock behaviour does the Mart walk, the purchase (shopping's
ball_need sees the open goal), and the leave. It also publishes the resolved result of the last
Abra encounter (caught / fled) that catch.py recorded at the battle's start. The goal never
blocks: the ABRA_STEP_CAP bookkeeping lives in plan_goal.
"""
from __future__ import annotations

from pokeagent.abra_goal import BALLS_MIN, ball_count, can_afford_ball
from pokeagent.explorer import grind_episode
from pokeagent.explorer import restock as rs
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.world import WorldGraph
from pokeagent.knowledge.cut_learner import LearnerTarget
from pokeagent.knowledge.encounters import map_name, slot_chances
from pokeagent.knowledge.flee_catch import ABRA_LINE
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import our_party

FAR = 1_000_000  # the learned graph cannot reach the map: treat it as farthest, not impossible
ABRA_SPECIES = "ABRA"
ABRA_WANT = "catch_abra goal (build abra)"


def abra_target(here_map: int, known_maps, wild_by_map: dict, distance=None) -> LearnerTarget | None:
    """The nearest grass map holding an ABRA slot (pick_target's sort: known world first, then
    distance, then encounter weight). Route 24 wins its tie with Route 25 on grass rate."""
    dist = distance or (lambda a, b: abs(a - b))
    known = {int(m) for m in (known_maps or ())}
    chances = slot_chances()
    cands = []
    for m, row in (wild_by_map or {}).items():
        row = row or {}
        grass = row.get("grass") or []
        idx = [i for i, (_, n) in enumerate(grass) if n == ABRA_SPECIES]
        if idx and row.get("grass_rate"):
            lv = (min(grass[i][0] for i in idx), max(grass[i][0] for i in idx))
            m = int(m)
            cands.append(LearnerTarget(m, map_name(m), ABRA_SPECIES, lv,
                                       round(sum(chances[i] for i in idx), 3), row["grass_rate"]))
    cands.sort(key=lambda t: (t.map not in known, dist(here_map, t.map), -t.chance * t.rate, t.map))
    return cands[0] if cands else None


class AbraHunt(BehaviourBase):
    name = "abra_hunt"

    def __init__(self) -> None:
        self._armed = False      # we set ctx.hunt_grass (only then may we clear and re-arm it)
        self._target = None      # the LearnerTarget being walked to

    def applies(self, ctx: ExplorerContext) -> bool:
        pend = ctx.abra_pending  # a wild Abra's fight is over: report how it ended (once per encounter)
        if pend is not None and not ctx.view.battling:
            ctx.abra_pending = None
            caught = any(c.name in ABRA_LINE for c in our_party(ctx.emu))
            ctx.log(f"[abra: {pend['species']} L{pend['level']} - {'caught' if caught else 'fled'}]", "res")
        if self._armed:
            ctx.hunt_grass = False
            self._armed = False
        if getattr(getattr(ctx, "opts", None), "build", "") != "abra" or ctx.goals().get("catch_abra"):
            return False
        ok = not ctx.view.battling and not ctx.view.box and ctx.proc is None \
            and grind_episode.active(ctx) is None   # a live episode pins the run to its map set
        if ok:
            ctx.team_wants = {ABRA_SPECIES: ABRA_WANT}
        return ok

    def _graph_dist(self, ctx: ExplorerContext, target_map: int) -> float:
        """Graph-path length from where we stand to any tile of ``target_map``."""
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((ctx.view.m, ctx.view.x, ctx.view.y), lambda n: n[0] == target_map)
        return len(p) if p is not None else FAR

    def _pick(self, ctx: ExplorerContext):
        return abra_target(ctx.view.m, ctx.mem.data["maps"], table(None, "wild_by_map"),
                           distance=lambda _a, b: self._graph_dist(ctx, b))

    def _announce(self, ctx: ExplorerContext, t) -> None:
        ctx.log(f"[catch_abra: {t.species} on {t.name} (0x{t.map:02X}), L{t.levels[0]}-{t.levels[1]}, "
                f"{t.chance * 100:.0f}%/encounter]", "res")

    def _ball_errand(self, ctx: ExplorerContext) -> bool:
        """Fewer than BALLS_MIN balls: the hunt needs throws in the bag - arm a restock trip and
        yield while Restock runs it (its own Mart walk, purchase, and leave; ``want`` picks a Mart
        that sells Balls). "0 balls AND no money for one" is the only settle the goal knows - short
        of balls with money in the purse never gives up, it shops first."""
        st = ctx.restock
        if st.get("intent") or st.get("leave"):
            return True  # a trip is armed or underway: Restock owns these steps
        if (ball_count(ctx.emu) >= BALLS_MIN or not can_afford_ball(ctx.emu, ROM_KB)
                or st.get("tries", 0) >= rs.MAX_TRIES or ctx.step < st.get("next_check", 0)):
            return False  # stocked, broke, spent, or a trip that found no route is in its recheck window
        st.update(intent=True, want=(rs.BALL_ID,), steps=0)
        ctx.shop_intent = ("mart", None)
        ctx.log(f"[catch_abra: {ball_count(ctx.emu)} balls under {BALLS_MIN} - buying Poke Balls at a Mart first]", "res")
        return True

    def step(self, ctx: ExplorerContext) -> Decision | None:
        if self._ball_errand(ctx):
            return None  # a Mart errand is armed: Restock's walk wins the next steps
        t = self._target
        if t is None:
            t = self._target = self._pick(ctx)
            if t is None:
                return None  # no grass table entry: exploration goes on (the step cap will settle the goal)
            self._announce(ctx, t)
        v = ctx.view
        if v.m == t.map:
            ctx.hunt_grass = self._armed = True
            return None  # on the grass map: frontier seeks grass and Catch throws on turn 1
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((v.m, v.x, v.y), lambda n: n[0] == t.map)
        if not p:
            # No known route: the cached pick may be a poor early one. Re-pick; a reachable candidate replaces it.
            t2 = self._pick(ctx)
            if t2 is None or t2.map == t.map:
                return None
            t = self._target = t2
            self._announce(ctx, t)
            p = g.path((v.m, v.x, v.y), lambda n: n[0] == t.map)
            if not p:
                return None
        return Decision(p[0], "abra_hunt_walk", f"catch_abra: {len(p)} steps to {t.species} grass on {t.name}")
