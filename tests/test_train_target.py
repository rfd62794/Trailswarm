"""Slice 5 (synthetic fixtures): team_ready and grind episodes train in ONE place - no Cerulean ping-pong."""
from __future__ import annotations

from pokeagent.explorer import grind_episode, train_target
from pokeagent.explorer.planner_east import ROUTE24
from pokeagent.grind import points as gp
from test_grind_episode import make_ctx, use_ledger

VF = 0x33
MAPS = {"3": {"visited": {"20,1": 1, "20,0": 1, "20,2": 1}, "blocked": [], "encounters": {},
              "warps": {"20,0,UP": [ROUTE24, 10, 35]}},
        str(ROUTE24): {"visited": {"10,35": 1, "9,35": 1}, "blocked": [], "warps": {}, "encounters": {"9,35": 3}},
        str(VF): {"visited": {"5,5": 1}, "blocked": [], "warps": {}, "encounters": {"5,5": 3}}}


def _ledger(*maps):
    return gp.GrindLedger({m: gp.GrindPoint(m, f"P{m}", level_band=(0, 100), xp_per_min_prior=70.0 + (m == VF) * 50)
                           for m in maps})


def _cerulean(tmp_path, ledger):
    ctx = use_ledger(make_ctx(tmp_path, m=3, x=20, y=1, lvl=6, need=8, maps=MAPS), ledger)
    ctx.stage_goal, ctx.train_route_live = "beat_misty", True   # team_ready is training
    return ctx


def test_only_maps_is_the_train_target_while_team_ready_trains(tmp_path):
    ctx = _cerulean(tmp_path, _ledger(VF, ROUTE24))
    assert train_target.only_maps(ctx) == frozenset({ROUTE24})
    ctx.train_route_live = False
    assert train_target.only_maps(ctx) is None                   # not training: unrestricted as before
    ctx.gym_hold_seen = (1, True)                                # the gym hold alone does not narrow (review of 376f738)
    assert train_target.only_maps(ctx) is None


def test_pre_brock_hold_keeps_the_full_pre_brock_set(tmp_path):
    from pokeagent.grind import stage_maps
    ctx = _cerulean(tmp_path, _ledger(VF, ROUTE24))
    ctx.stage_goal, ctx.train_route_live, ctx.gym_hold_seen = "beat_brock", False, (1, True)
    assert train_target.only_maps(ctx) == stage_maps.allowed("beat_brock")
    assert VF in (stage_maps.allowed("beat_brock") or {VF})


def test_later_gym_hold_is_not_pinned_to_route24(tmp_path):
    ctx = _cerulean(tmp_path, _ledger(VF, ROUTE24))
    ctx.stage_goal, ctx.train_route_live, ctx.gym_hold_seen = "beat_surge", False, (1, True)
    from pokeagent.grind import stage_maps
    assert train_target.only_maps(ctx) == stage_maps.allowed("beat_surge")   # unchanged by the hold: no Route 24 pin


def test_choose_prefers_the_train_target_even_when_another_point_scores_higher(tmp_path):
    led = _ledger(VF, ROUTE24)                                   # Viridian Forest has the higher xp/min
    free = gp.choose(led, [6], 8, (3, 20, 1), None, only_maps=None)
    assert free.map_id == VF
    ctx = _cerulean(tmp_path, led)
    pt = gp.choose(led, [6], 8, (3, 20, 1), ctx.mem, only_maps=train_target.only_maps(ctx))
    assert pt is not None and pt.map_id == ROUTE24


def test_no_episode_starts_on_a_far_map_while_team_ready_trains(tmp_path, monkeypatch):
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    ctx = _cerulean(tmp_path, _ledger(VF))                       # only the far forest point exists
    assert grind_episode.update(ctx) is None and grind_episode.active(ctx) is None
    ctx = _cerulean(tmp_path, _ledger(VF, ROUTE24))
    assert grind_episode.update(ctx) is not None
    assert grind_episode.active(ctx)["point"].map_id == ROUTE24  # the episode and train_route share Route 24
