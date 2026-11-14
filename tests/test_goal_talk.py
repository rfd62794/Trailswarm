"""goal_talk: the S.S. Anne captain must be talked to while hm01_cut is unmet; a done goal or another map leaves the behaviour idle."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours import default_behaviours
from pokeagent.explorer.behaviours import goal_talk
from pokeagent.explorer.behaviours.goal_talk import GOAL_TALKS, MAX_TALKS, GoalTalk


def ctx(goals, m=0x65, x=4, y=3, facing="UP", tries=0):
    return SimpleNamespace(goals=lambda: goals, view=SimpleNamespace(m=m, x=x, y=y, box=False, battling=False), proc=None, facing=facing,
                           goal_talk_tries={"hm01_cut": tries} if tries else {}, mem=SimpleNamespace(data={"maps": {}}, temp_blocked=set()),
                           log=lambda *a, **k: None)


def test_talks_to_the_captain_from_the_stand_tile():
    c = ctx({"hm01_cut": False})
    assert GoalTalk().applies(c)
    d = GoalTalk().step(c)
    assert d.button == "A" and c.goal_talk_tries["hm01_cut"] == 1


def test_faces_him_first_when_not_facing_up():
    d = GoalTalk().step(ctx({"hm01_cut": False}, facing="RIGHT"))
    assert d.button == "UP"


def test_idle_when_goal_done_wrong_map_or_out_of_tries():
    assert not GoalTalk().applies(ctx({"hm01_cut": True}))
    assert not GoalTalk().applies(ctx({"hm01_cut": False}, m=0x60))
    assert not GoalTalk().applies(ctx({"hm01_cut": False}, tries=MAX_TALKS))


def test_registered_after_use_items_and_table_names_the_captain_tile():
    names = [getattr(b, "name", "") for b in default_behaviours()]
    assert "goal_talk" in names and names.index("goal_talk") > names.index("use_items")
    assert GOAL_TALKS["hm01_cut"][:4] == (0x65, 4, 3, "UP") and goal_talk.pending(ctx({"hm01_cut": False})) is not None


def test_oak_is_talked_to_only_once_the_parcel_is_in_the_bag():
    lab = dict(m=0x28, x=5, y=3)
    assert not GoalTalk().applies(ctx({"oaks_parcel": False, "deliver_parcel": False}, **lab))   # starter stage: leave the lab flow alone
    assert not GoalTalk().applies(ctx({"oaks_parcel": True, "deliver_parcel": True}, **lab))
    c = ctx({"oaks_parcel": True, "deliver_parcel": False}, **lab)
    assert GoalTalk().applies(c) and GoalTalk().step(c).button == "A"


def _gym(visited, blocked=(), **kw):
    hold = kw.pop("hold", False)
    c = ctx({"beat_brock": False}, m=0x36, **kw)
    c.step = 100
    if hold is not None:
        c.gym_hold_seen = (100, hold)
    c.mem = SimpleNamespace(data={"maps": {"54": {"visited": {k: 1 for k in visited}, "blocked": list(blocked)}}}, temp_blocked=set())
    return c


def test_brock_is_talked_to_from_below_and_never_vetoed():
    from pokeagent.explorer.retalk_veto import veto
    assert GOAL_TALKS["beat_brock"][:4] == (0x36, 4, 2, "UP")
    c = _gym(["4,2"], x=4, y=2)
    d = GoalTalk().step(c)
    assert d.button == "A" and d.rule == "goal_talk"
    d.behaviour = "goal_talk"  # the Selector fills this in
    assert veto(c, d) is None


def test_brock_stand_tile_unmapped_walks_up_the_column_instead_of_idling():
    c = _gym(["4,4", "4,5", "3,5"], x=4, y=4)
    d = GoalTalk().step(c)
    assert d is not None and d.button == "UP"
    c = _gym(["4,4", "4,5", "3,5"], x=3, y=5)
    d = GoalTalk().step(c)
    assert d is not None and d.button in ("RIGHT", "UP")


def test_brock_waits_while_the_gym_hold_is_active_unknown_or_stale():
    assert not GoalTalk().applies(_gym(["4,2"], x=4, y=2, hold=True))
    assert not GoalTalk().applies(_gym(["4,2"], x=4, y=2, hold=None))   # PlanGoal has not judged readiness yet
    c = _gym(["4,2"], x=4, y=2); c.step = 100 + goal_talk.HOLD_FRESH + 1
    assert not GoalTalk().applies(c)
    assert GoalTalk().applies(_gym(["4,2"], x=4, y=2, hold=False))      # ready, or the stall hold was released


def test_approach_gives_up_after_the_cap_and_skips_a_no_move_direction():
    c = _gym(["4,4", "4,5"], x=4, y=4)
    assert GoalTalk().step(c).button == "UP"
    c.step += 1
    d = GoalTalk().step(c)               # still at (4,4): UP moved nothing, so it is not pressed again
    assert d is None or d.button != "UP"
    c = _gym(["4,4", "4,5"], x=4, y=4)
    c.approach_state = {"m": 0x36, "bl": 0, "steps": goal_talk.APPROACH_CAP, "last": None, "bad": {}}
    assert GoalTalk().step(c) is None


def test_approach_budget_resets_on_leaving_the_gym_blackout_and_reaching_the_stand(monkeypatch):
    cap = {"m": 0x36, "bl": 0, "steps": goal_talk.APPROACH_CAP, "last": None, "bad": {}}
    c = _gym(["4,4", "4,5"], x=4, y=4); c.approach_state = dict(cap)
    c.view.m = 0x02
    GoalTalk().applies(c)
    assert "approach_state" not in c.__dict__                      # left the gym
    c = _gym(["4,4", "4,5"], x=4, y=4); c.approach_state = dict(cap)
    monkeypatch.setattr(goal_talk, "_blackouts", lambda ctx: 1)
    assert GoalTalk().step(c).button == "UP"                       # a blackout is a fresh attempt
    c = _gym(["4,2", "4,4"], x=4, y=2); c.approach_state = dict(cap)
    GoalTalk().step(c)
    assert c.approach_state["steps"] == 0                          # reached the stand tile


def test_no_move_is_only_a_wall_after_our_own_press_with_no_text_box_and_expires():
    mk = lambda: _gym(["4,4", "4,5"], x=4, y=4)
    c = mk(); assert GoalTalk().step(c).button == "UP"
    c.step += 10                                                    # someone else acted in between: stale, not evidence
    assert GoalTalk().step(c).button == "UP"
    c = mk(); GoalTalk().step(c); c.step += 1; c.view.box = True
    GoalTalk().step(c)
    c.view.box = False
    assert not c.approach_state["bad"]                              # a dialog tick marked nothing
    c = mk(); GoalTalk().step(c); c.step += 1; GoalTalk().step(c)
    assert (4, 4, "UP") in c.approach_state["bad"]
    c.step += goal_talk.BAD_TTL + 1; c.gym_hold_seen = (c.step, False)
    assert GoalTalk().step(c).button == "UP"                        # expired


def test_fainted_trainee_early_return_marks_the_gym_hold_held():
    import inspect
    from pokeagent.explorer.behaviours import plan_goal
    src = inspect.getsource(plan_goal)
    i = src.index("never train a fainted trainee")
    assert "exit_rule.publish_hold(ctx, True)" in src[i - 300:i + 200]


def _misty(visited, goals=None, **kw):
    hold = kw.pop("hold", False)
    c = ctx(goals or {"beat_misty": False}, m=0x41, **kw)
    c.step = 100
    c.gym_hold_seen = (100, hold)
    c.mem = SimpleNamespace(data={"maps": {"65": {"visited": {k: 1 for k in visited}, "blocked": []}}}, temp_blocked=set())
    return c


def test_misty_is_talked_to_from_below_and_is_a_gym_goal():
    assert GOAL_TALKS["beat_misty"] == (0x41, 4, 3, "UP", "Misty") and "beat_misty" in goal_talk.APPROACH
    c = _misty(["4,3"], x=4, y=3)
    assert GoalTalk().applies(c)
    d = GoalTalk().step(c)
    assert d.button == "A" and d.rule == "goal_talk"
    assert not GoalTalk().applies(_misty(["4,3"], {"beat_misty": True}, x=4, y=3))   # beaten: idle
    assert not GoalTalk().applies(_misty(["4,3"], x=4, y=3, hold=True))              # the gym hold applies to every gym goal
    c = _misty(["4,5", "4,4"], x=4, y=5)                                             # stand tile unmapped: walk up the column
    assert GoalTalk().step(c).button == "UP"


def test_a_temp_block_on_the_stand_tile_does_not_shut_the_path():
    c = _misty(["4,3", "4,4", "4,5"], x=4, y=5)
    c.mem.temp_blocked = {(0x41, 4, 3): 10**9}   # block_sight's sight line covered the tile in front of the leader
    d = GoalTalk().step(c)
    assert d.rule == "goal_talk_walk" and d.button == "UP"
