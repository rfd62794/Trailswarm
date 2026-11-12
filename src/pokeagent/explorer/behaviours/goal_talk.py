"""goal_talk: a goal that is only met by talking to one known person (the S.S. Anne captain's HM01, a gym leader) walks there and talks.

Exploration only presses A at a person it has never talked to, so once the captain's text is memorised (``talked`` > 0, shared maps.json)
nobody ever rubs his back again and the HM is never given (2026-11-07: Cut left on the table, goal "captain done" fired on entering the
cabin). ``GOAL_TALKS`` maps an unmet goal to (map, stand x, stand y, facing, person label); while the goal is unmet and the agent is on
that map, it walks the learned graph to the stand tile, faces the person and presses A. The dialog behaviours finish the text.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.world import WorldGraph

# goal -> (map id, stand x, stand y, facing, who). The captain sits at (4,2) in SS_ANNE_CAPTAINS_ROOM (0x65); his back is rubbed from below.
# Oak stands static at (5,2) in his lab (0x28): the parcel is delivered from below, once it is in the bag (REQUIRES).
GOAL_TALKS = {"hm01_cut": (0x65, 4, 3, "UP", "the S.S. Anne captain"),
              "deliver_parcel": (0x28, 5, 3, "UP", "Prof. Oak"),
              # Brock stands static at (4,1) in Pewter Gym (0x36; after_victory logs "next BROCK p1 (4,1)"): fought from (4,2) facing up.
              "beat_brock": (0x36, 4, 2, "UP", "Brock"),
              # Misty stands static at (4,2) in Cerulean Gym (0x41; run log "next MISTY p1 (4,2)"): fought from (4,3) facing up.
              "beat_misty": (0x41, 4, 3, "UP", "Misty")}
APPROACH = ("beat_brock", "beat_misty")  # gym-leader goals: goals whose stand tile may be unmapped on arrival: walk to the nearest known tile and push towards it
REQUIRES = {"deliver_parcel": "oaks_parcel"}  # goal -> the goal that must already be met before the talk is wanted
HOLD_FRESH = 30  # steps a PlanGoal readiness verdict stays good; GoalTalk preempts PlanGoal, so a stale one lets PlanGoal run and refresh it
BAD_TTL = 50  # steps a no-move direction stays ruled out (an NPC or a dialog tick is not a wall)
APPROACH_CAP = 60  # approach steps per run before giving up on walking towards an unmapped stand tile
MAX_TALKS = 8  # A presses at the person per run before giving up on the goal (a dialog box in between resets nothing: counted per press)


def pending(ctx: ExplorerContext) -> tuple[str, tuple] | None:
    goals = ctx.goals()
    for goal, spec in GOAL_TALKS.items():
        if not goals.get(goal) and ctx.view.m == spec[0] and (goal not in REQUIRES or goals.get(REQUIRES[goal])):
            if goal in APPROACH and not _hold_clear(ctx):
                continue  # an unready team inside the gym is pulled out by PlanGoal's hold (or the hold is unknown): not the leader's to walk to
            return goal, spec
    return None


def _blackouts(ctx) -> int:
    try:
        from pokeagent.explorer import party_log
        return int(party_log.of(ctx).blackouts)
    except Exception:
        return 0


def _approach_state(ctx, m: int, at_stand: bool = False) -> dict:
    """Per-attempt approach bookkeeping; a map change, a blackout or reaching the stand tile starts it afresh."""
    st = ctx.__dict__.setdefault("approach_state", {})
    bl = _blackouts(ctx)
    if not st or st.get("m") != m or st.get("bl") != bl or at_stand:
        st.clear()
        st.update(m=m, bl=bl, steps=0, last=None, bad={})
    return st


def _hold_clear(ctx: ExplorerContext) -> bool:
    """True only when PlanGoal recently judged the gym hold NOT active (team ready, or its stall hold was released by cap/blackout)."""
    seen = getattr(ctx, "gym_hold_seen", None)
    return bool(seen) and seen[1] is False and ctx.step - seen[0] <= HOLD_FRESH


class GoalTalk(BehaviourBase):
    name = "goal_talk"

    def applies(self, ctx: ExplorerContext) -> bool:
        if ctx.view.m not in {spec[0] for g, spec in GOAL_TALKS.items() if g in APPROACH}:
            ctx.__dict__.pop("approach_state", None)  # left the gym: the next visit gets a fresh attempt
        if ctx.view.box or ctx.view.battling or ctx.proc is not None:
            return False
        hit = pending(ctx)
        return hit is not None and ctx.goal_talk_tries.get(hit[0], 0) < MAX_TALKS

    def step(self, ctx: ExplorerContext) -> Decision | None:
        goal, (m, sx, sy, facing, who) = pending(ctx)
        v = ctx.view
        if (v.x, v.y) == (sx, sy):
            if goal in APPROACH:
                _approach_state(ctx, m, at_stand=True)
            if ctx.facing != facing:
                return Decision(facing, "goal_talk_face", f"goal {goal}: facing {who} ({facing})")
            ctx.goal_talk_tries[goal] = ctx.goal_talk_tries.get(goal, 0) + 1
            return Decision("A", "goal_talk", f"goal {goal} is only met by talking to {who}: A (try {ctx.goal_talk_tries[goal]}/{MAX_TALKS})")
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked) - {(m, sx, sy)}  # a temp block on our own stand tile must never shut the path
        p = g.path((m, v.x, v.y), lambda n: n == (m, sx, sy))
        if p:
            return Decision(p[0], "goal_talk_walk", f"goal {goal}: {len(p)} steps to ({sx},{sy}) to talk to {who}")
        if goal in APPROACH:
            return _approach(ctx, g, goal, m, sx, sy, who)
        return None  # the stand tile is not in the learned map yet: exploration finds it


def _approach(ctx, g, goal, m, sx, sy, who) -> Decision | None:
    """Stand tile unmapped (the planner's generic 'road north / map edge' target sat 1,500 steps at the gym's south end): head for
    the known tile nearest to it and step on towards it, instead of leaving the leader to exploration."""
    d = ctx.mem.data["maps"].get(str(m), {})
    v = ctx.view
    st = _approach_state(ctx, m)
    last, step = st["last"], ctx.step
    if last and last[0] >= step - 2 and last[1:4] == (m, v.x, v.y) and not v.box:
        st["bad"][last[2:]] = step  # our own approach press from the previous step moved nothing here: treat the direction as shut
    st["last"] = None  # anything else acted in between: not evidence
    st["bad"] = {k: t for k, t in st["bad"].items() if step - t <= BAD_TTL}
    if st["steps"] >= APPROACH_CAP:
        return None
    blocked = set(d.get("blocked", [])) | {f"{x},{y},{b}" for x, y, b in st["bad"]}
    tiles = [tuple(map(int, k.split(","))) for k in d.get("visited", {})]
    if not tiles:
        return None
    tx, ty = min(tiles, key=lambda t: (abs(t[0] - sx) + abs(t[1] - sy), abs(t[0] - v.x) + abs(t[1] - v.y)))
    if (v.x, v.y) == (tx, ty):
        for b, dx, dy in (("UP", 0, -1), ("LEFT", -1, 0), ("RIGHT", 1, 0), ("DOWN", 0, 1)):
            if abs(tx + dx - sx) + abs(ty + dy - sy) < abs(tx - sx) + abs(ty - sy) and f"{tx},{ty},{b}" not in blocked:
                st["steps"] += 1; st["last"] = (step, m, tx, ty, b)
                return Decision(b, "goal_talk_approach", f"goal {goal}: stepping {b} from ({tx},{ty}) towards {who}'s tile ({sx},{sy})")
        return None
    p = g.path((m, v.x, v.y), lambda n: n == (m, tx, ty))
    if not p:
        return None
    st["steps"] += 1
    return Decision(p[0], "goal_talk_approach", f"goal {goal}: {len(p)} steps to ({tx},{ty}), nearest known tile to {who}")
