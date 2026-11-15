"""rewind.moments: each kind fires on a fixture built for it; results sort by step."""
from pathlib import Path

from pokeagent.review.load import RunData
from pokeagent.rewind.frames import Rewind
from pokeagent.rewind.moments import moments


def _data(transitions=None, decisions=None, levels=None) -> RunData:
    d = RunData(run_dir=Path("r"), name="r", runs_dir=Path("runs"))
    d.transitions, d.decisions, d.levels = transitions or [], decisions or [], levels or []
    return d


def _t(step, frm=(1, 0, 0), to=(1, 0, 1), battle_flag=0):
    return {"step": step, "from": list(frm), "to": list(to), "button": "A",
            "moved": list(frm) != list(to), "textbox": "none", "text": "", "facing": "UP",
            "source": "agent", "battle_flag": battle_flag, "battle_turn": 0}


def _d(step, outcome="moved", goal_stage="first_pokemon"):
    return {"step": step, "behaviour": "frontier", "rule": "walk", "button": "A", "map": 1,
            "x": 0, "y": 0, "goal_stage": goal_stage, "box": False, "battle": False,
            "outcome": outcome, "reversal": False}


def _rw(data):
    return Rewind.from_run(data)


def test_map_change_moment():
    data = _data(transitions=[_t(0), _t(1, (1, 0, 1), (5, 0, 0)), _t(2, (5, 0, 0), (5, 0, 1))])
    got = [(m.step, m.kind, m.label) for m in moments(_rw(data), data)]
    assert (1, "map_change", "map 1 -> 5") in got
    assert [m.kind for m in moments(_rw(data), data)].count("map_change") == 1


def test_battle_start_and_end_each_once():
    data = _data(transitions=[_t(s, battle_flag=1 if 2 <= s <= 3 else 0) for s in range(6)])
    got = moments(_rw(data), data)
    starts = [m for m in got if m.kind == "battle_start"]
    ends = [m for m in got if m.kind == "battle_end"]
    assert [m.step for m in starts] == [2] and [m.step for m in ends] == [4]


def test_goal_moment_uses_goal_stage_label():
    data = _data(transitions=[_t(s) for s in range(5)],
                 decisions=[_d(3, outcome="goal", goal_stage="beat_brock")])
    got = moments(_rw(data), data)
    assert [(m.step, m.kind, m.label) for m in got if m.kind == "goal"] == [
        (3, "goal", "beat_brock")]


def test_level_up_survives_a_party_reorder():
    levels = [{"step": 2, "party": [[25, 5, 100, 20, 22], [1, 3, 9, 9, 10]]},
              {"step": 6, "party": [[1, 3, 9, 9, 10], [25, 7, 180, 30, 34]]}]  # swapped slots
    data = _data(transitions=[_t(s) for s in range(8)], levels=levels)
    got = [m for m in moments(_rw(data), data) if m.kind == "level_up"]
    assert [(m.step, m.label) for m in got] == [(6, "species 25: L5 -> L7")]


def test_moments_sorted_by_step():
    data = _data(
        transitions=[_t(0), _t(4, (1, 0, 1), (2, 0, 0), battle_flag=0),
                     _t(8, (2, 0, 0), (2, 0, 1), battle_flag=1)],
        decisions=[_d(6, outcome="goal", goal_stage="first_pokemon")],
        levels=[{"step": 1, "party": [[25, 5, 0, 20, 22]]},
                {"step": 9, "party": [[25, 6, 0, 24, 26]]}],
    )
    got = moments(_rw(data), data)
    assert [m.step for m in got] == sorted(m.step for m in got)
    assert {m.kind for m in got} == {"map_change", "battle_start", "goal", "level_up"}
