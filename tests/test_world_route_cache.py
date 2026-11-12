"""Route-search caching: one search per goal while the committed path holds; a memory, temp-block
or NPC change re-runs it. Counts fresh searches by wrapping WorldGraph._bfs_walk."""
from __future__ import annotations

import pokeagent.explorer.world as world
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.world import WorldGraph, maps_version


def _maps() -> dict:
    """A 5x3 room on map 1 (all tiles visited), and map 2's one tile - unreachable from map 1."""
    return {"1": {"visited": {f"{x},{y}": 1 for x in range(5) for y in range(3)},
                  "blocked": [], "warps": {}, "jumps": {}, "npcs": {}},
            "2": {"visited": {"0,0": 1}, "blocked": [], "warps": {}, "jumps": {}, "npcs": {}}}


def _mem(tmp_path, maps=None) -> MapMemory:
    mem = MapMemory(tmp_path / "maps.json")
    mem.data["maps"].update(maps or _maps())
    return mem


def _count_walks(monkeypatch) -> list:
    calls = []
    orig = WorldGraph._bfs_walk

    def counted(self, start, goal_fn, limit):
        calls.append(start)
        return orig(self, start, goal_fn, limit)

    monkeypatch.setattr(WorldGraph, "_bfs_walk", counted)
    return calls


DELTA = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def test_route_to_serves_the_cached_path_suffix(tmp_path, monkeypatch):
    mem = _mem(tmp_path)
    walks = _count_walks(monkeypatch)
    r1 = mem.route_to(1, 0, 0, (1, 4, 0))
    assert r1 is not None and r1[0] == (1, 4, 0)
    goal, buttons = r1
    x, y = 0, 0
    for b in buttons[:2]:  # walk two steps along the committed route
        dx, dy = DELTA[b]
        x, y = x + dx, y + dy
    before = len(walks)
    r2 = mem.route_to(1, x, y, (1, 4, 0))
    assert r2 is not None and r2[0] == goal
    assert r2[1] == buttons[2:]  # the remaining suffix, answered without a new search
    assert len(walks) == before


def test_cached_route_matches_fresh_bfs(tmp_path):
    mem = _mem(tmp_path)
    fresh = WorldGraph(mem.data["maps"])._bfs_node((1, 0, 0), lambda n: n == (1, 4, 2), 4000)
    cached = mem.route_to(1, 0, 0, (1, 4, 2))
    assert cached == fresh  # same goal node AND the same buttons the uncached search returns


def test_wall_warp_and_temp_block_roll_the_route_version(tmp_path, monkeypatch):
    mem = _mem(tmp_path)
    walks = _count_walks(monkeypatch)
    mem.route_to(1, 0, 0, (1, 4, 0))
    walks.clear()
    mem.data["maps"]["1"]["blocked"].append("1,0,RIGHT")  # a learned wall
    assert mem.route_to(1, 0, 0, (1, 4, 0)) is not None
    assert len(walks) == 1
    walks.clear()
    mem.temp_blocked[(1, 1, 0)] = 999  # a wanderer NPC's tile until step 999: skipped, never learned
    assert mem.route_to(1, 0, 0, (1, 4, 0)) is not None
    assert len(walks) == 1


def test_cached_miss_only_answers_the_same_start(tmp_path, monkeypatch):
    mem = _mem(tmp_path)
    walks = _count_walks(monkeypatch)
    assert mem.route_to(1, 0, 0, (2, 0, 0)) is None  # map 2 is unreachable from map 1
    n = len(walks)
    assert mem.route_to(1, 0, 0, (2, 0, 0)) is None
    assert len(walks) == n  # the miss is cached
    assert mem.route_to(1, 1, 0, (2, 0, 0)) is None
    assert len(walks) == n + 1  # a new start re-searches once


def test_neighbour_memo_shared_across_graphs(tmp_path):
    maps = _maps()
    g1, g2 = WorldGraph(maps), WorldGraph(maps)
    assert list(g1.neighbours((1, 2, 1))) == list(g2.neighbours((1, 2, 1)))
    key = (id(maps), maps_version(maps), True, frozenset(), None)
    assert key in world._NEIGH  # one shared memo entry served both graphs
    maps["1"]["blocked"].append("2,1,UP")
    g3 = WorldGraph(maps)
    assert list(g3.neighbours((1, 2, 1))) == list(g3.neighbours((1, 2, 1)))
    key3 = (id(maps), maps_version(maps), True, frozenset(), None)
    assert key3 != key and key3 in world._NEIGH  # the learned wall rolled the memo key


def test_frontier_plan_cached_per_map(tmp_path, monkeypatch):
    maps = _maps()
    maps["1"]["blocked"] += ["0,0,UP", "0,0,LEFT"]  # start itself is no frontier; (0,1) is the nearest
    mem = _mem(tmp_path, maps)
    walks = _count_walks(monkeypatch)
    p1 = mem.frontier_plan(1, 0, 0)
    assert p1 is not None and p1[0] == (1, 0, 1) and p1[1] == ["DOWN"]
    before = len(walks)
    p2 = mem.frontier_plan(1, 0, 1)  # on the committed path: the suffix answers without a search
    assert p2 is not None and p2[0] == (1, 0, 1) and p2[1] == []
    assert len(walks) == before


def test_goal_closing_over_mutable_state_gets_no_cache_entry(tmp_path, monkeypatch):
    """A goal whose closure holds a mutable object can change under any cached key, so
    _goal_sig returns None and every path() re-searches."""
    mem = _mem(tmp_path)
    walks = _count_walks(monkeypatch)
    box = {"target": (1, 4, 0)}

    def goal(n):
        return n == box["target"]

    g = WorldGraph(mem.data["maps"])
    assert g.path((1, 0, 0), goal) is not None
    assert g.path((1, 0, 0), goal) is not None
    assert len(walks) == 2  # no cache entry: the second call ran the search again


def test_goal_closing_over_immutable_values_still_caches(tmp_path, monkeypatch):
    """Ints/tuples/frozensets in the closure keep the last-result cache: the repeat call is
    answered by the committed path's suffix, not a fresh search."""
    mem = _mem(tmp_path)
    walks = _count_walks(monkeypatch)
    target, bound = (1, 4, 0), frozenset({1})

    def goal(n):
        return n == target and n[0] in bound

    g = WorldGraph(mem.data["maps"])
    r1 = g.path((1, 0, 0), goal)
    assert r1 is not None
    assert g.path((1, 0, 0), goal) == r1
    assert len(walks) == 1  # the repeat was served from the cached route


def test_visits_and_a_far_wall_keep_the_route_a_hit(tmp_path, monkeypatch):
    """New tiles on either map and a wall nowhere near the route must not re-search: ``visited``
    only grows the graph, and the route cache checks the path's own edges, not the whole wall set."""
    mem = _mem(tmp_path)
    walks = _count_walks(monkeypatch)
    r1 = mem.route_to(1, 0, 0, (1, 4, 0))
    assert r1 is not None
    mem.data["maps"]["1"]["visited"]["0,0"] = 7          # a revisit count bump on this map
    mem.data["maps"]["2"]["visited"]["9,9"] = 1          # a brand-new tile on another map
    mem.data["maps"]["2"]["blocked"].append("0,0,RIGHT")  # a wall on the other map
    mem.data["maps"]["1"]["blocked"].append("0,2,LEFT")   # and map-1 walls off every route edge
    mem.data["maps"]["1"]["blocked"].append("4,2,DOWN")
    before = len(walks)
    assert mem.route_to(1, 0, 0, (1, 4, 0)) == r1
    assert len(walks) == before


def test_a_wall_on_the_cached_path_forces_a_research(tmp_path, monkeypatch):
    """A learned wall ON a cached path edge invalidates just that route: one fresh search finds a
    path that does not repeat the walled step."""
    mem = _mem(tmp_path)
    walks = _count_walks(monkeypatch)
    r1 = mem.route_to(1, 0, 0, (1, 4, 0))
    assert r1 is not None
    first_btn = r1[1][0]
    mem.data["maps"]["1"]["blocked"].append(f"0,0,{first_btn}")
    walks.clear()
    r2 = mem.route_to(1, 0, 0, (1, 4, 0))
    assert len(walks) == 1
    assert r2 is not None and r2[0] == (1, 4, 0)
    assert r2[1][0] != first_btn


def test_a_goal_reading_visited_stays_correct(tmp_path, monkeypatch):
    """cached_route re-asks the CURRENT goal_fn about the cached target: a side the goal reads as
    unexplored that just got visited drops the route exactly like a fresh search would."""
    mem = _mem(tmp_path)
    visited = mem.data["maps"]["1"]["visited"]
    del visited["4,1"]  # (4,1) unexplored: the goal holds only while it stays unvisited
    walks = _count_walks(monkeypatch)
    goal = lambda n: n == (1, 4, 0) and "4,1" not in visited
    assert mem.cached_route((1, 0, 0), "g", goal) is not None
    mem.data["maps"]["2"]["visited"]["9,9"] = 1  # an unrelated visit: still a hit
    before = len(walks)
    got = mem.cached_route((1, 0, 0), "g", goal)
    assert len(walks) == before
    assert got == WorldGraph(mem.data["maps"])._bfs_node((1, 0, 0), goal, 4000)
    visited["4,1"] = 1  # the side the goal reads is now visited: the cached target went stale
    before = len(walks)
    got2 = mem.cached_route((1, 0, 0), "g", goal)
    assert len(walks) == before + 1  # the stale entry was dropped and re-searched once
    assert got2 is None
    assert WorldGraph(mem.data["maps"])._bfs_node((1, 0, 0), goal, 4000) is None


def test_warp_jump_temp_npc_and_beaten_each_roll_the_route(tmp_path, monkeypatch):
    """Every routing-relevant change still invalidates the cached plan - only ``visited`` stopped."""
    walks = _count_walks(monkeypatch)
    cases = [
        ("warp", lambda m: m.data["maps"]["1"]["warps"].update({"4,0,UP": [2, 0, 0]})),
        ("jump", lambda m: m.data["maps"]["1"]["jumps"].update({"4,0,UP": [4, 2]})),
        ("temp", lambda m: m.temp_blocked.update({(1, 0, 1): 999})),
        ("npc", lambda m: m.data["maps"]["1"]["npcs"].update(
            {"e1": {"positions": {"2,1": 1}, "moves": False, "last": [2, 1]}})),
        ("beaten", lambda m: setattr(m, "beaten_tiles", {(1, 0, 1)})),
    ]
    for i, (name, mutate) in enumerate(cases):
        maps = _maps()
        maps["1"]["blocked"] += ["0,0,UP", "0,0,LEFT"]  # (0,1) is the nearest frontier
        mem = MapMemory(tmp_path / f"{name}.json")
        mem.data["maps"].update(maps)
        assert mem.frontier_plan(1, 0, 0) is not None  # caches the plan
        walks.clear()
        mutate(mem)  # the routing-relevant change lands
        assert mem.frontier_plan(1, 0, 0) is not None
        assert len(walks) == 1, f"{name} did not force a re-search"


def test_walks_per_step_stays_under_point_three(tmp_path, monkeypatch):
    """N steps of walking a corridor while exploration adds fresh tiles elsewhere: real searches
    per step stay under 0.3 (every step used to re-search when ``len(visited)`` rolled the key)."""
    maps = {"1": {"visited": {f"{x},1": 1 for x in range(10)},
                  "blocked": [], "warps": {}, "jumps": {}, "npcs": {}},
            "2": {"visited": {"0,0": 1}, "blocked": [], "warps": {}, "jumps": {}, "npcs": {}}}
    mem = _mem(tmp_path, maps)
    walks = _count_walks(monkeypatch)
    n = 20
    for i in range(n):
        mem.data["maps"]["2"]["visited"][f"{i},0"] = i + 1  # the step's own exploration, off-route
        mem.route_to(1, i % 10, 1, (1, 9, 1))
    assert len(walks) / n < 0.3
