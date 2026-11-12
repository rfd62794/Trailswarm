"""train_route (synthetic learned maps): the route-to-point step and stay_on_route's episode set."""
from __future__ import annotations

from pokeagent.explorer import train_route
from pokeagent.explorer.memory import MapMemory

MAPS = {"3": {"visited": {"10,35": 1, "10,36": 1}, "blocked": [],
              "warps": {"10,35,UP": [35, 10, 35]}, "encounters": {}},
        "35": {"visited": {"10,35": 1, "9,35": 1}, "blocked": [], "warps": {}, "encounters": {"9,35": 2}}}


def test_step_routes_to_the_point_map_and_its_grass():
    r = train_route.step(MAPS, (3, 10, 36), (), 20, 20, target=35)
    assert r and r[0] == "UP" and "Route 24" in r[1]                    # off the target: toward the warp
    r = train_route.step(MAPS, (35, 10, 35), (), 20, 20, target=35)
    assert r and r[0] == "LEFT"                                      # on it: toward the encounter tile
    assert train_route.step(MAPS, (35, 9, 35), (), 20, 20, target=35) is None       # on the grass: roam it
    assert train_route.step(MAPS, (7, 1, 1), (), 20, 20, target=35) is None       # no learned way on
    assert train_route.step(MAPS, (3, 10, 36), (), 9, 20, target=35) is None      # too hurt to walk out
    assert train_route.step(MAPS, (3, 10, 36), {(3, 10, 35)}, 20, 20, target=35) is None  # the way is blocked


def test_step_on_target_with_an_explicit_patch():
    maps = {"35": {"visited": {"10,35": 1, "11,35": 1}, "blocked": [], "warps": {}, "encounters": {}}}
    r = train_route.step(maps, (35, 10, 35), (), 20, 20, target=35, patch={(11, 35)})
    assert r and r[0] == "RIGHT"                                     # the patch tile is the goal, not encounters
    assert train_route.step(maps, (35, 11, 35), (), 20, 20, target=35, patch={(11, 35)}) is None


def test_step_accepts_a_grind_point_patch_of_json_lists():
    # GrindPoint.patch is [[x, y]] from JSON; set(patch) raised "unhashable type: 'list'" on every grind step
    maps = {"35": {"visited": {"10,35": 1, "11,35": 1}, "blocked": [], "warps": {}, "encounters": {}}}
    r = train_route.step(maps, (35, 10, 35), (), 20, 20, target=35, patch=[[11, 35]])
    assert r and r[0] == "RIGHT"


def test_stay_on_route_episode_set_covers_edge_exits():
    """OutsideSet: every map not in `allowed` plus the recorded presses that leave it - learned warps,
    one-sighting map changes (warp_cand), and paths edges where a run recorded them (PR #165)."""
    maps = {"35": {"visited": {"10,35": 1}, "blocked": [],
                   "warps": {"10,35,UP": [3, 10, 35], "5,5,UP": [64, 5, 5]},
                   "warp_cand": {"9,35,DOWN": 1},
                   "paths": {"8,35,LEFT": {"to": [4, 8, 35]}}}}
    s = train_route.stay_on_route(35, False, {"maps": {35, 64}}, maps)
    assert 3 in s and 4 in s and 35 not in s and 64 not in s          # every map outside the set
    for key in ("10,35,UP", "9,35,DOWN", "8,35,LEFT"):
        assert s.leads_out(35, key)                                   # warp, one-sighting cand, paths edge
    assert not s.leads_out(35, "5,5,UP")                              # a warp INTO the set is not an exit
    assert train_route.stay_on_route(train_route.ROUTE24, True) == {train_route.CERULEAN}
    assert train_route.stay_on_route(3, False) is None


def test_choose_local_marks_a_one_sighting_edge_as_tried(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    mem.data["maps"]["35"] = {"visited": {"10,35": 1, "10,36": 1}, "blocked": [],
                              "warps": {}, "warp_cand": {"10,35,UP": 1}, "encounters": {}}
    s = train_route.OutsideSet({35, 64}, mem.data["maps"])
    name, _why, _want = mem.choose_local(35, 10, 35, "DOWN", avoid_maps=s)
    assert name != "UP"                                              # the unconfirmed edge counts as leaving


def test_survives_replaces_the_hp_fraction_test_when_given():
    assert train_route.step(MAPS, (3, 10, 36), (), 1, 20, target=35, survives=True) is not None   # 5% HP but the party survives
    assert train_route.step(MAPS, (3, 10, 36), (), 20, 20, target=35, survives=False) is None     # full HP but nobody survives
    assert train_route.step(MAPS, (3, 10, 36), (), 0, 0, target=35, survives=True) is None        # mx == 0 still stops
    assert train_route.step(MAPS, (3, 10, 36), (), 9, 20, target=35) is None                      # legacy: the 0.5 fraction
