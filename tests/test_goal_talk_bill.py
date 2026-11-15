"""ss_ticket: Bill's house is three stages read from the RAM sprite table (synthetic: no ROM, no window)."""
from __future__ import annotations

from types import SimpleNamespace

import pokeagent.explorer.anomaly_sprites as anomaly_sprites
from pokeagent.explorer.behaviours import goal_talk_bill as bill
from pokeagent.explorer.behaviours.goal_talk import MAX_TALKS, GoalTalk
from pokeagent.explorer.planner_east import LADDER, TARGETS, east_road_step
from pokeagent.explorer.retalk_veto import veto
from pokeagent.explorer.world import WorldGraph

ROOM = {"visited": {f"{x},{y}": 1 for x in range(0, 8) for y in range(2, 8)}, "blocked": []}


def ctx(sprites, x=6, y=6, facing="UP", goal=False, tries=0, emu=True, box=False):
    c = SimpleNamespace(goals=lambda: {"ss_ticket": goal}, view=SimpleNamespace(m=0x58, x=x, y=y, box=box, battling=False), proc=None,
                        facing=facing, goal_talk_tries={"ss_ticket": tries} if tries else {}, step=10,
                        mem=SimpleNamespace(data={"maps": {"88": ROOM}}, temp_blocked=set()), log=lambda *a, **k: None)
    c.emu = SimpleNamespace(sprites=sprites) if emu else None
    return c


def run(monkeypatch, sprites, **kw):
    monkeypatch.setattr(anomaly_sprites, "read_sprites", lambda emu: {i: (5, x, y) for i, (x, y) in enumerate(emu.sprites)})
    c = ctx(sprites, **kw)
    return c, GoalTalk().step(c)


def test_stage_one_talks_to_the_monster_from_below(monkeypatch):
    c, d = run(monkeypatch, [(6, 5)])
    assert d.button == "A" and c.goal_talk_tries["ss_ticket"] == 1


def test_stage_one_walks_to_the_talk_tile_and_faces_him(monkeypatch):
    _, d = run(monkeypatch, [(6, 5)], x=2, y=7)
    assert d.rule == "goal_talk_walk"
    _, d = run(monkeypatch, [(6, 5)], facing="LEFT")
    assert d.button == "UP" and d.rule == "goal_talk_face"


def test_stage_two_uses_the_console_when_no_sprite_is_left(monkeypatch):
    _, d = run(monkeypatch, [], x=6, y=6)
    assert d.rule == "goal_talk_walk" and "console" in d.why
    c, d = run(monkeypatch, [], x=1, y=5)
    assert d.button == "A" and "console" in d.why and c.goal_talk_tries["ss_ticket"] == 1


def test_stage_three_talks_to_human_bill_from_below(monkeypatch):
    c, d = run(monkeypatch, [(4, 4)], x=4, y=5)
    assert d.button == "A" and "Bill" in d.why and "monster" not in d.why
    _, d = run(monkeypatch, [(4, 4)], x=1, y=5)
    assert d.rule == "goal_talk_walk"


def test_stages_do_not_run_when_the_ticket_is_held_or_a_box_is_open(monkeypatch):
    monkeypatch.setattr(anomaly_sprites, "read_sprites", lambda emu: {})
    assert not GoalTalk().applies(ctx([], goal=True))
    assert not GoalTalk().applies(ctx([], box=True))


def test_bounded_attempts_then_hand_back_to_the_planner(monkeypatch):
    monkeypatch.setattr(anomaly_sprites, "read_sprites", lambda emu: {})
    assert GoalTalk().applies(ctx([], tries=bill.TALK_CAP - 1))
    assert not GoalTalk().applies(ctx([], tries=bill.TALK_CAP)) and bill.TALK_CAP > MAX_TALKS


def test_no_emulator_assumes_the_first_stage():
    assert bill.stage(ctx([], emu=False)) == "monster"


def test_a_failing_sprite_read_assumes_the_first_stage(monkeypatch):
    monkeypatch.setattr(anomaly_sprites, "read_sprites", lambda emu: 1 / 0)
    assert bill.stage(ctx([(1, 1)])) == "monster"


def test_retalk_memory_never_vetoes_the_console_or_bill_presses():
    from pokeagent.explorer.behaviours.base import Decision
    from pokeagent.explorer.retalk_veto import _at_unmet_goal_stand
    assert all(_at_unmet_goal_stand(ctx([], x=t[1], y=t[2])) for t in bill.STAND_TILES)
    assert veto(ctx([], x=1, y=5), Decision("A", "goal_talk", "x")) is None


def test_planner_targets_bills_house_for_the_ticket_stage():
    assert TARGETS["ss_ticket"] is not None and TARGETS["ss_ticket"]((0x58, 4, 5)) and not TARGETS["ss_ticket"]((0x24, 1, 1))

    class Everywhere(WorldGraph):
        def path(self, *a, **k):
            return ["LEFT"]

    done = {s: True for s in LADDER[:LADDER.index("ss_ticket")]}
    step = east_road_step(Everywhere({}), {}, {**done, "_level": 20, "_train_level": 8}, (0x24, 5, 5))
    assert step is not None and "ss_ticket" in step[1]
