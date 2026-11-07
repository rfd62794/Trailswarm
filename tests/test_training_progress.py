"""Training counts as progress: the shared predicate, the swarm watchdog, the trainee-level state saves, the route back to grass."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from pokeagent import training_progress as tp
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.explorer import train_route
from pokeagent.legs import states as S
from pokeagent.magikarp import MAGIKARP
from pokeagent.ramstructs import PARTY_COUNT, PARTY_MON1, PARTY_MON_SIZE

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import swarm_watch as sw  # noqa: E402


def row(step, magikarp=(9, 938), lead=(26, 13936)):
    return {"step": step, "party": [[133, magikarp[0], magikarp[1], 23, 23], [179, lead[0], lead[1], 72, 72]]}


def test_predicate_xp_level_and_none():
    assert not tp.training_progress([row(0), row(150)])
    assert tp.training_progress([row(0), row(150, magikarp=(9, 1016))])             # XP only
    assert tp.training_progress([row(0), row(150, magikarp=(10, 1100))])            # level
    assert not tp.training_progress([row(0), row(150, magikarp=(9, 1016))], since_step=150)   # gain is older than the window
    assert not tp.training_progress([row(0), {"step": 9, "party": row(0)["party"] + [[16, 5, 100, 20, 20]]}])  # a mon joining
    assert not tp.training_progress([row(0), {"step": 9, "party": list(reversed(row(0)["party"]))}])  # reorder is not a gain


def _watch(tmp_path):
    d = tmp_path / "runs" / "explore-1-1"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"seed": 7}))
    (d / "transitions.jsonl").write_text("")
    t = [0.0]
    return d, sw.ProgressWatch(tmp_path, 7, since_wall=0, clock=lambda: t[0])


def _moves(d, n):
    with open(d / "transitions.jsonl", "a") as f:
        for i in range(n):
            f.write(json.dumps({"to": [3, i % 3, 0], "button": "A"}) + "\n")


def _levels(d, *rows):
    with open(d / "levels.jsonl", "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_watch_stalls_a_wanderer_but_not_a_grinder(tmp_path):
    d, w = _watch(tmp_path)
    _levels(d, row(0))
    _moves(d, 700)
    assert "only 0 new tiles" in w.check()                       # same tiles, no XP: stalled
    d2, w2 = _watch(tmp_path / "b")
    _levels(d2, row(0))
    _moves(d2, 400)
    w2.check()
    _levels(d2, row(400, magikarp=(9, 1016)))                    # a won battle: XP on the trainee
    w2.check()
    _moves(d2, 500)
    assert w2.check() is None                                    # 500 presses since the gain: inside the window
    _moves(d2, 200)
    assert w2.check() is not None                                # 700 since: grinding stopped, stall again


class _Emu(FakeEmulator):
    def save_state(self, path):
        Path(path).write_bytes(b"s")


def _party(emu, level):
    emu.set(PARTY_COUNT, 1)
    base = PARTY_MON1
    emu.set(base, MAGIKARP)
    emu.set(base + 33, level)   # level byte of a party mon
    emu.set(0xD057, 0)
    emu.set(0xD16C, 0); emu.set(0xD16D, 20); emu.set(0xD18D, 0); emu.set(0xD18E, 20)


def _ctx(emu, tmp_path, gy=1):
    c = SimpleNamespace(emu=emu, run_dir=tmp_path, team_ready_steps=gy, logs=[])
    c.log = lambda t, tag=None: c.logs.append(t)
    return c


def test_trainee_level_gain_saves_named_state(tmp_path):
    emu = _Emu()
    _party(emu, 9)
    sv, ctx = S.LegStateSaver(tmp_path / "s"), _ctx(emu, tmp_path)
    fr = PressFrame("A", "agent", "", before=(3, 1, 1), after=(3, 1, 1), box_after=False)
    assert sv.observe_trainee(ctx, fr) is None                   # the starting level is not a gain
    _party(emu, 10)
    emu.set(0xD057, 1)                                           # level-up happens in battle: wait for calm
    assert sv.observe_trainee(ctx, fr) is None
    emu.set(0xD057, 0)
    p = sv.observe_trainee(ctx, fr)
    assert p == tmp_path / "s" / "gyarados@L10.state" and p.exists()
    assert sv.observe_trainee(ctx, fr) is None                   # once per level
    _party(emu, 11)
    assert sv.observe_trainee(ctx, fr).name == "gyarados@L11.state"
    assert S.LegStateSaver(tmp_path / "s").observe_trainee(_ctx(emu, tmp_path, gy=0), fr) is None  # not the gyarados stage


def test_route_back_to_grass():
    assert train_route.step({}, (train_route.ROUTE24, 1, 1), (), 20, 20) is None   # already on Route 24
    assert train_route.step({}, (3, 1, 1), (), 5, 20) is None                      # hurt: heal logic decides
    assert train_route.step({}, (3, 1, 1), (), 20, 20) is None                     # no learned way


def test_frontier_on_route_24_will_not_leave_for_cerulean_while_training():
    assert train_route.stay_on_route(train_route.ROUTE24, True) == {train_route.CERULEAN}
    assert train_route.stay_on_route(train_route.ROUTE24, False) is None  # not training: roam freely
    assert train_route.stay_on_route(3, True) is None  # elsewhere step() walks back to Route 24


def test_train_route_walks_to_route_24_grass_once_the_map_is_fully_seen():
    maps = {str(train_route.ROUTE24): {"visited": {"1,1": 1, "1,2": 1, "1,3": 1}, "blocked": [], "warps": {}, "encounters": {"1,3": 2}}}
    first = train_route.step(maps, (train_route.ROUTE24, 1, 1), (), 20, 20)
    assert first and first[0] == "DOWN" and "grass" in first[1], first
    assert train_route.step(maps, (train_route.ROUTE24, 1, 3), (), 20, 20) is None   # on the grass: frontier roams it
    assert train_route.step(maps, (train_route.ROUTE24, 1, 1), {(train_route.ROUTE24, 1, 2)}, 20, 20) is None  # a person in the corridor: no way
