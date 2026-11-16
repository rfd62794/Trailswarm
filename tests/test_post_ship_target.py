"""After the S.S. Anne the stage has no TRAIN_MAP pin: the trainee trains at the NEAREST proven grass, not Route 24.

2026-11-15 marathon-2026-11-15h: a beat_surge hold at the Vermilion Pokecenter walked ~215 steps back north to
Route 24 (train_route's default target) although Route 6 (110 proven grass tiles) is one map away."""
from __future__ import annotations

import copy

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
