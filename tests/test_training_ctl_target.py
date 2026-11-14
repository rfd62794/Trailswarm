"""Training controller slice 2 (Target, synthetic fixtures): only a visited, learned-path point may start
a session; an empty ledger or all-phantom points means no episode - Target never invents a point."""
from __future__ import annotations

import inspect
import subprocess
import sys

from pokeagent.explorer import grind_episode, story_blockers, train_target
from pokeagent.explorer.planner_east import ROUTE24
from pokeagent.explorer.training_ctl import target
from pokeagent.grind import points as gp
from test_grind_episode import make_ctx, use_ledger

VF = 0x33
MAPS = {"3": {"visited": {"20,1": 1, "20,0": 1, "20,2": 1}, "blocked": [], "encounters": {},
              "warps": {"20,0,UP": [ROUTE24, 10, 35]}},
        str(ROUTE24): {"visited": {"10,35": 1, "9,35": 1}, "blocked": [], "warps": {}, "encounters": {"9,35": 3}}}
# no "51" entry: Viridian Forest was never stood on. A learned route reaches Route 24 from Cerulean (20,0) UP.


def _pt(map_id, prior):
    return gp.GrindPoint(map_id, f"P{map_id}", level_band=(0, 100), xp_per_min_prior=prior)


def _ledger(*pts):
    return gp.GrindLedger({p.map_id: p for p in pts})


def _cerulean(tmp_path, ledger, maps=None):
    return use_ledger(make_ctx(tmp_path, m=3, x=20, y=1, lvl=6, need=8, maps=maps or MAPS), ledger)


def test_never_visited_map_point_is_rejected(tmp_path):
    led = _ledger(_pt(VF, 500.0), _pt(ROUTE24, 50.0))   # the phantom pin outscores the real point 10:1
    ctx = _cerulean(tmp_path, led)
    assert gp.choose(led, [6], 8, (3, 20, 1), ctx.mem).map_id == VF      # unrestricted choose takes it (the bug)
    pt = target.choose(ctx, led, [6], 8)
    assert pt is not None and pt.map_id == ROUTE24                        # the lower-but-real point wins
    assert target.choose(ctx, _ledger(_pt(VF, 500.0)), [6], 8) is None    # alone it is a phantom pin: None


def test_point_with_no_learned_path_is_rejected(tmp_path):
    maps = {**MAPS, "99": {"visited": {"5,5": 1}, "blocked": [], "warps": {}, "encounters": {}}}
    led = _ledger(_pt(99, 500.0))                                       # visited, but no warp chain reaches it
    ctx = _cerulean(tmp_path, led, maps=maps)
    assert gp.choose(led, [6], 8, (3, 20, 1), ctx.mem) is not None       # unrestricted choose takes it (the bug)
    assert target.choose(ctx, led, [6], 8) is None


def test_empty_ledger_returns_none(tmp_path):
    ctx = _cerulean(tmp_path, gp.GrindLedger({}))
    assert target.choose(ctx, ctx._grind_state["ledger"], [6], 8) is None
    assert target.choose(ctx, gp.GrindLedger(), [6], 8) is None          # a ledger with no points at all
    assert grind_episode.start(ctx) is False                             # never invents a point
    assert ctx._grind_state["no_point_until"] == ctx.step + grind_episode.NO_POINT_RECHECK
    assert grind_episode.active(ctx) is None


def test_known_point_is_chosen_by_the_existing_scorer(tmp_path):
    led = _ledger(_pt(3, 80.0), _pt(ROUTE24, 200.0))                     # both visited and reachable
    ctx = _cerulean(tmp_path, led)
    want = gp.choose(led, [6], 8, (3, 20, 1), ctx.mem,
                     blocked=story_blockers.blocked_tiles(ctx), only_maps=train_target.only_maps(ctx))
    got = target.choose(ctx, led, [6], 8)
    assert got is not None and want is not None
    assert got.map_id == want.map_id == ROUTE24                          # the higher xp/min wins, same scorer


def test_target_module_does_not_import_grind_episode():
    assert "grind_episode" not in inspect.getsource(target)
    assert not hasattr(train_target, "grind_episode")
    assert not hasattr(train_target, "route_kw")


def test_wants_training_matches_the_old_applies_read(tmp_path):
    ctx = make_ctx(tmp_path, m=3, x=20, y=1, lvl=6, need=8, maps=MAPS)
    ctx.train_need = 0
    ctx._grind_state = {"episode": {"maps": {ROUTE24}, "point": _pt(ROUTE24, 50.0)}}
    assert target.wants_training(ctx) is True                            # a live episode
    ctx._grind_state["episode"], ctx.train_need = None, 8
    assert target.wants_training(ctx) is True                            # under-level (6 < 8), no episode
    ctx.train_need = 6
    assert target.wants_training(ctx) is False                           # the trainee is at the need


def test_episode_start_skips_a_phantom_forest_pin(tmp_path):
    """The seed-12 shape end to end: Cerulean (map 3), heal_cerulean stage, train_route_live False - the
    ledger's atlas-seeded 0x33 prior can no longer pin an episode on a map the agent never stood on."""
    ctx = _cerulean(tmp_path, _ledger(_pt(VF, 500.0), _pt(ROUTE24, 50.0)))
    ctx.stage_goal, ctx.train_route_live = "heal_cerulean", False
    assert grind_episode.start(ctx) is True
    ep = grind_episode.active(ctx)
    assert ep is not None and ep["point"].map_id == ROUTE24              # the episode lands on Route 24, never 0x33
    ctx2 = _cerulean(tmp_path, _ledger(_pt(VF, 500.0)))
    ctx2.stage_goal, ctx2.train_route_live = "heal_cerulean", False
    assert grind_episode.start(ctx2) is False and grind_episode.active(ctx2) is None


def test_fresh_process_imports():
    """A fresh interpreter catches an import cycle that a warm test process hides."""
    for code in ("import pokeagent.explorer.grind_episode, pokeagent.explorer.train_target, "
                 "pokeagent.explorer.training_ctl.target, pokeagent.explorer.behaviours.grind_drill",
                 "import pokeagent.explorer.train_target"):
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
