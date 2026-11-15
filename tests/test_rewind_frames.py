"""rewind.frames: frame() carry-forward and clamping, the party join, and track()'s trail."""
from pathlib import Path

from pokeagent.review.load import RunData
from pokeagent.rewind.frames import PartyRow, Rewind
from pokeagent.world.model import TRAIL


def _data(transitions=None, decisions=None, levels=None) -> RunData:
    d = RunData(run_dir=Path("r"), name="r", runs_dir=Path("runs"))
    d.transitions, d.decisions, d.levels = transitions or [], decisions or [], levels or []
    return d


def _t(step, frm, to, **kw):
    row = {"step": step, "from": list(frm), "to": list(to), "button": "A",
           "moved": list(frm) != list(to), "textbox": "none", "text": "", "facing": "DOWN",
           "source": "agent", "battle_flag": 0, "battle_turn": 0}
    row.update(kw)
    return row


def _d(step, **kw):
    row = {"step": step, "behaviour": "frontier", "rule": "walk", "button": "UP", "map": 1,
           "x": 0, "y": 0, "goal_stage": "first_pokemon", "box": False, "battle": False,
           "outcome": "moved", "reversal": False}
    row.update(kw)
    return row


def test_frame_carries_forward_decision_fields():
    data = _data(
        transitions=[_t(0, [1, 0, 0], [1, 0, 1]), _t(1, [1, 0, 1], [1, 0, 2]),
                     _t(5, [1, 0, 2], [1, 0, 3])],
        decisions=[_d(0, behaviour="goto", rule="goto_step", goal_stage="to_route2")],
    )
    f = Rewind.from_run(data).frame(5)
    assert f.behaviour == "goto" and f.rule == "goto_step" and f.goal_stage == "to_route2"
    assert (f.map, f.x, f.y) == (1, 0, 3) and f.step == 5


def test_frame_lookup_is_by_step_not_position():
    rw = Rewind.from_run(_data(transitions=[_t(10, [1, 0, 0], [1, 0, 1]),
                                          _t(20, [1, 0, 1], [2, 0, 0])]))
    assert (rw.first_step, rw.last_step, len(rw)) == (10, 20, 2)
    assert rw.frame(15).y == 1 and rw.frame(15).map == 1
    assert rw.frame(20).map == 2


def test_frame_clamps_below_and_above():
    rw = Rewind.from_run(_data(transitions=[_t(10, [1, 0, 0], [1, 0, 1]),
                                          _t(20, [1, 0, 1], [1, 0, 2])]))
    assert rw.frame(-50) == rw.frame(10)
    assert rw.frame(999) == rw.frame(20) and rw.frame(999).step == 20


def test_transitions_only_run_plays_with_empty_fields():
    rw = Rewind.from_run(_data(transitions=[_t(0, [3, 4, 4], [3, 4, 5]),
                                          _t(1, [3, 4, 5], [3, 4, 5], moved=False)]))
    f = rw.frame(1)
    assert (f.behaviour, f.rule, f.outcome, f.goal_stage, f.party) == ("", "", "", "", ())
    assert (f.map, f.x, f.y) == (3, 4, 5) and not f.moved and f.facing == "DOWN"


def test_frame_party_is_the_latest_levels_row():
    levels = [{"step": 3, "party": [[25, 5, 100, 20, 22]]},
              {"step": 8, "party": [[25, 6, 140, 10, 24], [1, 3, 9, 9, 10]]}]
    rw = Rewind.from_run(_data(transitions=[_t(0, [1, 0, 0], [1, 0, 1]),
                                            _t(9, [1, 0, 1], [1, 0, 2])], levels=levels))
    assert rw.frame(0).party == ()                       # before the first levels row
    assert rw.frame(4).party == (PartyRow(25, 5, 20, 22),)   # [species, level, exp, hp, max_hp]
    assert rw.frame(9).party == (PartyRow(25, 6, 10, 24), PartyRow(1, 3, 9, 10))


def test_frame_battle_fields():
    rw = Rewind.from_run(_data(transitions=[_t(0, [1, 0, 0], [1, 0, 1]),
                                          _t(1, [1, 0, 1], [1, 0, 1], moved=False,
                                             battle_flag=1, battle_turn=4)]))
    assert not rw.frame(0).in_battle
    assert rw.frame(1).in_battle and rw.frame(1).battle_turn == 4


def test_track_path_order_cap_and_prev():
    ts = [_t(s, [1, 0, s], [1, 0, s + 1]) for s in range(5)]
    ts.append(_t(5, [1, 0, 5], [1, 0, 5], moved=False))
    rw = Rewind.from_run(_data(transitions=ts, decisions=[_d(0, goal_stage="beat_brock")]))
    tr = rw.track(5, trail=3)
    assert (tr.id, tr.map, tr.y, tr.step, tr.goal) == ("rewind", 1, 5, 5, "beat_brock")
    assert list(tr.path) == [(1, 0, 3), (1, 0, 4), (1, 0, 5)]   # oldest first, capped
    assert tr.prev == (1, 0, 4)                                 # where the last move came from
    assert tr.path.maxlen == 3


def test_track_defaults_and_unblocked_cap():
    rw = Rewind.from_run(_data(transitions=[_t(0, [1, 0, 0], [1, 0, 1]),
                                          _t(1, [1, 0, 1], [1, 0, 2])]))
    tr = rw.track(1)
    assert tr.path.maxlen == TRAIL and list(tr.path) == [(1, 0, 1), (1, 0, 2)]
    assert tr.prev == (1, 0, 1)
    assert tr.battle is None and not tr.hold and not tr.stalled


def test_track_with_no_moves():
    rw = Rewind.from_run(_data(transitions=[_t(0, [1, 2, 3], [1, 2, 3], moved=False)]))
    tr = rw.track(0)
    assert tr.prev is None and list(tr.path) == [] and (tr.map, tr.x, tr.y) == (1, 2, 3)
