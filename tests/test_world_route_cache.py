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
