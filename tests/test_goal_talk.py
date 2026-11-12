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
