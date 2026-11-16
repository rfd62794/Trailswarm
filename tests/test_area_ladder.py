"""Area ladder (synthetic): pick()'s hysteresis, known_rungs and stage_target's ladder/pin."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer import train_target
from pokeagent.explorer.planner_east import ROUTE24
from pokeagent.explorer.training_ctl import release
from pokeagent.grind import area_ladder, atlas
from test_training_ctl_release import SYN, _ctx, _mon, _patch


def _sp(m, xp):
    return SimpleNamespace(map_id=m, xp_per_step=xp)


NO = lambda m: False
T0 = lambda m: 0.0


def test_best_xp_wins_and_a_tie_keeps_current():
    assert area_ladder.pick([_sp(12, 3.1), _sp(13, 4.0)], NO, None, T0, 0) == 13
    assert area_ladder.pick([_sp(12, 4.0), _sp(13, 4.0)], NO, 13, T0, 0) == 13   # a tie keeps current
    assert area_ladder.pick([_sp(12, 4.0), _sp(13, 4.0)], NO, 12, T0, 0) == 12


def test_switch_needs_gain_over_current_and_the_dwell():
    assert area_ladder.pick([_sp(12, 4.0), _sp(13, 4.9)], NO, 12, T0, 600) == 12   # under SWITCH_GAIN
    assert area_ladder.pick([_sp(12, 4.0), _sp(13, 10.0)], NO, 12, T0, 599) == 12  # inside the dwell
    assert area_ladder.pick([_sp(12, 4.0), _sp(13, 10.0)], NO, 12, T0, 600) == 13  # gain AND dwell met


def test_a_far_rung_is_never_picked():
    assert area_ladder.pick([_sp(13, 9.0)], NO, None, lambda m: 321.0, 0) is None
    out = area_ladder.pick([_sp(12, 1.0), _sp(13, 9.0)], NO, None,
                           lambda m: 400.0 if m == 13 else 0.0, 0)
    assert out == 12                                                             # the far one is skipped


def test_empty_spots_returns_none_and_stage_target_pins(monkeypatch):
    assert area_ladder.pick([], NO, None, T0, 0) is None
    ctx = _ctx([_mon("RATTATA", 5)])
    ctx.stage_goal = "beat_brock"
    monkeypatch.setattr(release, "ladder_spots", lambda *a, **k: ([], 0))
    assert train_target.stage_target(ctx) == 0x0C                                # the TRAIN_MAP pin


def test_unvisited_or_unreachable_maps_are_not_rungs():
    maps = {"12": {"visited": {"1,1": 1, "1,0": 1}, "blocked": [], "warps": {"1,0,UP": [13, 1, 1]}},
            "13": {"visited": {"1,1": 1}, "blocked": [], "warps": {}},
            "51": {"visited": {"5,5": 1}, "blocked": [], "warps": {}}}
    assert area_ladder.known_rungs(maps, (12, 1, 1), {12, 13, 33, 51}) == {12, 13}
    # Route 22 (33) was never visited; the Forest (51) was visited but no learned route reaches it.


def test_solo_ok_beats_higher_xp_and_none_solo_ok_beats_overall():
    spots = [_sp(12, 3.0), _sp(13, 5.0)]
    assert area_ladder.pick(spots, lambda m: m == 12, None, T0, 0) == 12
    assert area_ladder.pick(spots, NO, None, T0, 0) == 13


def test_stage_target_without_a_ladder_is_unchanged():
    ctx = _ctx([_mon("RATTATA", 5)])
    for stage in ("beat_surge", "heal_cerulean", None):
        ctx.stage_goal = stage
        assert train_target.stage_target(ctx) == ROUTE24       # no ladder: today's Route 24 pin


def test_forest_loses_to_route1_on_xp_per_step_not_map_order():
    """rate 8 (Viridian Forest) vs rate 25 (Route 1), the 1.1 rows: the pick follows xp/step."""
    tables = {"wild": SYN["wild_by_map"],
              "base_exp": {r["name"]: r["base_exp"] for r in SYN["species_by_dex"].values()}}
    spots = atlas.rank_spots("RATTATA", 5, 12, tables, {}, {}, "MEDIUM_FAST",
                             candidates={12, 13, 33, 51}, top=4)
    assert spots and spots[0].map_id == 12
    assert next(s for s in spots if s.map_id == 12).xp_per_step > \
        next(s for s in spots if s.map_id == 51).xp_per_step


def test_stage_target_picks_route1_and_stamps_the_cache(tmp_path, monkeypatch):
    maps = {"12": {"visited": {"1,1": 1, "1,0": 1, "2,0": 1, "3,0": 1}, "blocked": [],
                   "warps": {"1,0,UP": [13, 1, 1], "2,0,UP": [33, 1, 1], "3,0,UP": [51, 1, 1]}},
            "13": {"visited": {"1,1": 1}, "blocked": [], "warps": {}},
            "33": {"visited": {"1,1": 1}, "blocked": [], "warps": {}},
            "51": {"visited": {"5,5": 1}, "blocked": [], "warps": {}}}
    team = [_mon("RATTATA", 5)]
    ctx = _ctx(team)
    ctx.stage_goal, ctx.mem = "beat_brock", SimpleNamespace(data={"maps": maps})
    _patch(monkeypatch, team)
    monkeypatch.setattr(release, "verdict", lambda c, s, m: False)
    assert train_target.stage_target(ctx) == 0x0C              # Route 1's higher rate wins
    assert ctx.ladder["map"] == 0x0C                           # the pick is cached, one writer
    ctx2 = _ctx(team)
    ctx2.stage_goal, ctx2.mem = "beat_brock", SimpleNamespace(data={"maps": maps})
    monkeypatch.setattr(release, "verdict", lambda c, s, m: m == 51)
    assert train_target.stage_target(ctx2) == 0x33             # a solo-viable rung beats xp/step
    assert any("[ladder]" in ln for ln in ctx2.logs)
