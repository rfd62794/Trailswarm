"""After the S.S. Anne the stage has no TRAIN_MAP pin: the trainee trains at the NEAREST proven grass, not Route 24.

2026-11-15 marathon-2026-11-15h: a beat_surge hold at the Vermilion Pokecenter walked ~215 steps back north to
Route 24 (train_route's default target) although Route 6 (110 proven grass tiles) is one map away."""
from __future__ import annotations

import copy

import pytest

from pokeagent.explorer import train_target
from pokeagent.explorer.behaviours.plan_goal import PlanGoal
from pokeagent.explorer.planner_east import ROUTE24
from test_grind_episode import make_ctx

VERMILION, ROUTE6, CERULEAN = 0x05, 0x11, 0x03
GRASS = {f"{x},1": 3 for x in range(8)}
MAPS = {
    str(VERMILION): {"visited": {"5,0": 1, "5,1": 1}, "blocked": [], "encounters": {}, "warps": {"5,0,UP": [ROUTE6, 5, 3]}},
    str(ROUTE6): {"visited": {"5,3": 1, "4,3": 1}, "blocked": [], "encounters": dict(GRASS),
                  "warps": {"5,3,UP": [CERULEAN, 20, 1], "5,3,DOWN": [VERMILION, 5, 0]}},
    str(CERULEAN): {"visited": {"20,1": 1}, "blocked": [], "encounters": {}, "warps": {"20,1,UP": [ROUTE24, 10, 35]}},
    str(ROUTE24): {"visited": {"10,35": 1, "9,35": 1}, "blocked": [], "encounters": dict(GRASS), "warps": {}},
}


WILD = {ROUTE6: {"RATTATA": (13, 17, 1.0)}, ROUTE24: {"ODDISH": (7, 12, 1.0)}}


@pytest.fixture(autouse=True)
def _wild(monkeypatch):
    monkeypatch.setattr(train_target, "species_on", lambda m, kb=None: WILD.get(m, {}))


def _ctx(tmp_path, stage):
    ctx = make_ctx(tmp_path, m=VERMILION, x=5, y=0, lvl=5, need=22, maps=copy.deepcopy(MAPS))
    ctx.stage_goal = stage
    return ctx


def test_stage_without_a_pin_trains_at_the_nearest_grass(tmp_path):
    assert train_target.stage_target(_ctx(tmp_path, "beat_surge")) == ROUTE6


def test_pinned_stage_keeps_route24(tmp_path):
    assert train_target.stage_target(_ctx(tmp_path, "beat_misty")) == ROUTE24


def test_no_proven_grass_falls_back_to_route24(tmp_path):
    ctx = _ctx(tmp_path, "beat_surge")
    for m in (ROUTE6, ROUTE24):
        ctx.mem.data["maps"][str(m)]["encounters"] = {}
    assert train_target.stage_target(ctx) == ROUTE24


def test_pick_is_sticky_within_a_stage(tmp_path):
    ctx = _ctx(tmp_path, "beat_surge")
    assert train_target.stage_target(ctx) == ROUTE6
    ctx.view.m, ctx.view.x, ctx.view.y = ROUTE24, 10, 35      # standing on a farther patch changes nothing
    assert train_target.stage_target(ctx) == ROUTE6


def test_hold_grind_step_walks_to_route6_not_route24(tmp_path):
    ctx = _ctx(tmp_path, "beat_surge")
    ctx.mem.temp_blocked = set()
    ctx.view.battling = False
    step = PlanGoal._grind_step(ctx, VERMILION, 5, 0, 20, 20)
    assert step is not None and step[0] == "UP" and "Route 24" not in step[1]


def test_too_hard_grass_is_skipped_for_a_suitable_farther_map(tmp_path):
    WILD_BAK = dict(WILD)
    try:
        WILD[ROUTE6] = {"ONIX": (30, 35, 1.0)}        # weakest L30: far above a L5 trainee
        assert train_target.stage_target(_ctx(tmp_path, "beat_surge")) == ROUTE24
    finally:
        WILD.clear(); WILD.update(WILD_BAK)


def test_no_suitable_map_falls_back_and_logs_why(tmp_path):
    ctx = _ctx(tmp_path, "beat_surge")
    WILD_BAK = dict(WILD)
    try:
        WILD[ROUTE6] = {"ONIX": (30, 35, 1.0)}
        WILD[ROUTE24] = {"ONIX": (30, 35, 1.0)}
        assert train_target.nearest_grass(ctx) is None and train_target.stage_target(ctx) == ROUTE24
        assert any("do not suit" in t for t in ctx.logs)
    finally:
        WILD.clear(); WILD.update(WILD_BAK)


def test_pick_dropped_when_the_route_is_cut_off(tmp_path):
    ctx = _ctx(tmp_path, "beat_surge")
    assert train_target.stage_target(ctx) == ROUTE6
    ctx.mem.data["maps"][str(VERMILION)]["warps"] = {}          # Vermilion -> Route 6 forgotten
    ctx.mem.data["maps"][str(VERMILION)]["visited"] = {"5,0": 1}
    ctx.step += train_target.REVALIDATE_STEPS
    assert train_target.nearest_grass(ctx) is None               # unreachable now: no stale pick, nothing else reachable


def test_zero_battle_window_drops_and_bars_the_pick(tmp_path):
    ctx = _ctx(tmp_path, "beat_surge")
    assert train_target.stage_target(ctx) == ROUTE6
    ctx.step += train_target.NO_BATTLE_WINDOW                    # no new battle in the window
    assert train_target.stage_target(ctx) == ROUTE24             # Route 6 barred for this stage: the next suitable map
    ctx.step += 1
    ctx.battles += 1
    assert train_target.stage_target(ctx) == ROUTE24             # and it stays barred


def test_battles_keep_the_pick_alive(tmp_path):
    ctx = _ctx(tmp_path, "beat_surge")
    assert train_target.stage_target(ctx) == ROUTE6
    for _ in range(3):
        ctx.step += train_target.NO_BATTLE_WINDOW - 1
        ctx.battles += 1
        assert train_target.stage_target(ctx) == ROUTE6


def test_to_grass_passes_the_stage_target(monkeypatch):
    from types import SimpleNamespace
    from pokeagent.explorer.training_ctl import sustain
    seen = {}
    monkeypatch.setattr(sustain, "heal_gate_hp", lambda e: (10, 30))
    monkeypatch.setattr(sustain, "party_survives", lambda e, m: True)
    monkeypatch.setattr(sustain.train_target, "stage_target", lambda c: ROUTE6)
    monkeypatch.setattr(sustain.train_route, "step", lambda *a, **k: seen.update(k) or ("UP", "x"))
    ctx = SimpleNamespace(mem=SimpleNamespace(data={"maps": {}}, temp_blocked=set()), emu=object(),
                          view=SimpleNamespace(m=VERMILION), facing="UP", train_route_live=False)
    sustain.to_grass(ctx, None, (VERMILION, 5, 0), True)
    assert seen.get("target") == ROUTE6
