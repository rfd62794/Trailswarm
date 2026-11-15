"""rewind.segments: the ACTIVITY table, per-frame activity, exact coverage and shares."""
from pathlib import Path

from pokeagent.explorer.behaviours import default_behaviours
from pokeagent.review.load import RunData
from pokeagent.rewind.frames import Rewind
from pokeagent.rewind.segments import ACTIVITY, Segment, activity, segments, shares

ACTIVITIES = {"move", "battle", "text", "menu", "heal", "shop", "catch", "wait", "other"}


def _data(transitions, decisions):
    d = RunData(run_dir=Path("r"), name="r", runs_dir=Path("runs"))
    d.transitions, d.decisions = transitions, decisions
    return d


def _t(step, battle_flag=0):
    return {"step": step, "from": [1, 0, step], "to": [1, 0, step + 1], "button": "UP",
            "moved": True, "textbox": "none", "text": "", "facing": "UP",
            "source": "agent", "battle_flag": battle_flag, "battle_turn": 0}


def _d(step, behaviour):
    return {"step": step, "behaviour": behaviour, "rule": "r", "button": "UP", "map": 1,
            "x": 0, "y": step, "goal_stage": "g", "box": False, "battle": False,
            "outcome": "moved", "reversal": False}


def _fixture():
    # steps 0-2 frontier, 3-4 menu, 5-7 a battle, 8-9 frontier again
    ts = [_t(s, battle_flag=1 if 5 <= s <= 7 else 0) for s in range(10)]
    ds = [_d(0, "frontier"), _d(3, "menu"), _d(5, "battle_moves"), _d(8, "frontier")]
    return Rewind.from_run(_data(ts, ds))


def test_every_default_behaviour_has_an_activity():
    names = {b.name for b in default_behaviours()}
    assert names and names <= ACTIVITY.keys()
    assert set(ACTIVITY.values()) <= ACTIVITIES
    assert "training" not in ACTIVITY.values()   # needs state that is not logged per step


def test_activity_battle_flag_wins_and_unknown_is_other():
    f = _fixture().frame(5)
    assert f.behaviour == "battle_moves" and activity(f) == "battle"
    unknown = _fixture().frame(0)
    assert activity(unknown) == "move"
    other = Rewind.from_run(_data([_t(0)], [_d(0, "no_such_behaviour")])).frame(0)
    assert activity(other) == "other"


def test_segments_cover_the_range_exactly_once():
    segs = segments(_fixture())
    assert [(s.start, s.end, s.activity) for s in segs] == [
        (0, 2, "move"), (3, 4, "menu"), (5, 7, "battle"), (8, 9, "move")]
    covered = [step for s in segs for step in range(s.start, s.end + 1)]
    assert covered == list(range(10))


def test_shares_sum_to_one_and_empty_is_empty():
    assert shares(segments(_fixture())) == {"move": 0.5, "menu": 0.2, "battle": 0.3}
    assert abs(sum(shares(segments(_fixture())).values()) - 1.0) < 1e-9
    assert shares([]) == {}
    assert shares([Segment(0, 0, "move")]) == {"move": 1.0}
