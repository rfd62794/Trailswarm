"""A talk the retalk veto refused is a failed option for the planner (Viridian Forest loop, Blue marathon): plan_goal
chose A facing an already-memorised beaten Bug Catcher, the engine turned it into B, and the planner chose A again."""
from types import SimpleNamespace as NS

from pokeagent.explorer import retalk_memory
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.planner import plan_step

FOREST = 0x33
POS = (FOREST, 27, 41)
GOALS = {"potion": True, "left_house": True, "first_pokemon": True, "won_battle": True, "to_route1": True, "to_viridian": True, "oaks_parcel": True, "deliver_parcel": True, "to_route2": True}


def forest_maps():
    """A forest whose northernmost frontier is (27,41): a static NPC stands on the unvisited tile (27,40) above it."""
    visited = {f"{x},{y}": 1 for x, y in ((27, 41), (26, 41), (26, 42), (27, 42))}
    npcs = {"slot8:pic4": {"pic": 4, "slot": 8, "positions": {"27,40": 1}, "moves": False, "last": [27, 40]}}
    return {str(FOREST): {"visited": visited, "blocked": [], "warps": {}, "npcs": npcs}}


def test_planner_talks_to_the_person_ahead_when_nothing_vetoed_it():
    press = plan_step(dict(GOALS), forest_maps(), POS, "UP")
    assert press is not None and press[0] == "A" and "person stands ahead" in press[1]  # a genuinely useful first talk goes through


def test_planner_moves_past_a_vetoed_talk_and_never_returns_to_the_spot():
    goals = {**GOALS, "_talk_vetoed": frozenset({POS})}
    here = plan_step(goals, forest_maps(), POS, "UP")
    assert here is None or here[0] != "A"
    away = plan_step(goals, forest_maps(), (FOREST, 26, 41), "UP")  # one tile aside: no walk back to (27,41)
    assert away is None or "(27,41)" not in away[1]


def ctx_at(step=100):
    return NS(step=step, view=NS(m=FOREST, x=27, y=41), talk_vetoed={})


def test_only_a_vetoed_plan_goal_talk_is_noted_and_it_expires():
    c = ctx_at()
    retalk_memory.note(c, Decision("A", "r", behaviour="readiness"))
    retalk_memory.note(c, Decision("UP", "r", behaviour="plan_goal"))
    assert retalk_memory.active(c) == frozenset()
    retalk_memory.note(c, Decision("A", "r", behaviour="plan_goal"))
    assert retalk_memory.active(c) == frozenset({POS})
    c.step += retalk_memory.TALK_VETO_TTL
    assert retalk_memory.active(c) == frozenset() and not c.talk_vetoed


def test_engine_notes_the_vetoed_plan_goal_talk(tmp_path):
    from pokeagent.explorer.engine import Engine
    from pokeagent.explorer.selector import Selector
    from test_loop_veto_engine import Stub, make_ctx

    ctx = make_ctx(tmp_path)
    ctx.facing = "UP"
    ctx.mem.m(0x28).setdefault("interactions", {})["5,6,UP"] = {"type": "info", "pages": ["hi"], "count": 8}
    engine = Engine(ctx, selector=Selector([Stub("plan_goal", "A")]))
    d = engine.step()
    assert d.rule == "retalk_veto" and d.button == "B"
    assert (0x28, 5, 6) in retalk_memory.active(ctx)
