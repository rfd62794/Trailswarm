"""Pallet Town deliver_parcel ping-pong (2026-11-05) and the momentum review follow-ups."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.frontier import _frontier_move
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.explorer.press_track import track_progress

MAP, PX, PY = 0xD35E, 0xD362, 0xD361
DELIVER = {g: True for g in ("potion", "left_house", "first_pokemon", "won_battle", "to_route1", "to_viridian", "oaks_parcel")}
DELIVER.update({"deliver_parcel": False, "_hp": (30, 30), "_level": 8, "_train_level": 8})


def pallet_mem(tmp_path) -> MapMemory:
    """Pallet column x=9 (y=10..12), a row to the real door tile (12,12); a stale warp (9,11) UP -> the lab."""
    mem = MapMemory(tmp_path / "maps.json")
    d = mem.m(0)
    for x, y in [(9, 10), (9, 11), (9, 12), (10, 12), (11, 12), (12, 12)]:
        d["visited"][f"{x},{y}"] = 1
    d["warps"]["12,12,UP"] = [40, 5, 11]
    d["warps"]["9,11,UP"] = [40, 5, 11]  # learned from a forced walk twice; the game never warps here
    mem.m(40)["visited"]["5,11"] = 1
    mem.m(40)["interactions"] = {"6,2,LEFT": {"text": "OAK BCN, raise your young POKeMON"}}
    return mem


def test_stale_warp_is_forgotten_when_the_press_walks_on_in_the_same_map(tmp_path):
    mem = pallet_mem(tmp_path)
    assert mem.learn((0, 9, 11), "UP", (0, 9, 10), confirmed=False) == "moved"
    assert "9,11,UP" not in mem.m(0)["warps"]
    assert "0:9,11,UP" in mem.data["bad_warps"]
    assert "12,12,UP" in mem.m(0)["warps"]  # the real door is untouched
    # and a later map change from that key is not re-learned as a warp
    mem.learn((0, 9, 11), "UP", (40, 5, 11), confirmed=False)
    mem.learn((0, 9, 11), "UP", (40, 5, 11), confirmed=False)
    assert "9,11,UP" not in mem.m(0)["warps"]


def test_deliver_parcel_route_does_not_ping_pong_after_a_walk(tmp_path):
    mem = pallet_mem(tmp_path)
    maps = mem.data["maps"]
    # before the fix the planner said DOWN at (9,10) and UP at (9,11): a two-tile oscillation
    mem.learn((0, 9, 11), "UP", (0, 9, 10), confirmed=False)  # the press the agent actually makes
    seen = []
    pos = (0, 9, 10)
    for _ in range(12):
        step = plan_step(DELIVER, maps, pos, "UP")
        assert step is not None
        seen.append(step[0])
        nx = {"DOWN": (0, pos[1], pos[2] + 1), "UP": (0, pos[1], pos[2] - 1), "RIGHT": (0, pos[1] + 1, pos[2])}[step[0]]
        pos = nx
        if pos == (0, 12, 12):
            break
    assert seen == ["DOWN", "DOWN", "RIGHT", "RIGHT", "RIGHT"]


def make_ctx(tmp_path, **fields) -> ExplorerContext:
    emu = FakeEmulator({MAP: 1, PX: 4, PY: 5})
    return ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                           run_dir=tmp_path, stable_frames=10, **fields)


def test_map_change_clears_momentum_and_stale_tabu(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.last_dir = "UP"
    ctx.recent_tiles = {2: [(1, 1), (1, 2)]}
    fr = PressFrame(name="UP", source="agent", why="t", before=(1, 4, 0), after=(2, 3, 9))
    track_progress(ctx, fr)
    assert ctx.last_dir is None
    assert ctx.recent_tiles[2] == [(3, 9)]  # the old visit's tiles are gone, the entry tile is the first
    fr = PressFrame(name="LEFT", source="agent", why="t", before=(2, 3, 9), after=(2, 2, 9))
    track_progress(ctx, fr)
    assert ctx.last_dir == "LEFT" and ctx.recent_tiles[2] == [(3, 9), (2, 9)]


def test_frontier_target_on_another_map_is_dropped(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.mem.m(7)["visited"]["3,3"] = 1  # still a frontier over there: only the map mismatch can drop it
    ctx.frontier_target, ctx.frontier_route, ctx.frontier_at = (7, 3, 3), ["UP"], None
    _frontier_move(ctx, 1, 4, 5)
    assert ctx.frontier_target is None and ctx.frontier_route == []
