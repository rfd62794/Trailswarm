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


def disprove(mem, n=1):
    for _ in range(n):
        mem.learn((0, 9, 11), "UP", (0, 9, 10), confirmed=False)


def test_push_back_in_the_opposite_direction_is_not_a_disproof(tmp_path):
    mem = pallet_mem(tmp_path)
    for _ in range(5):
        mem.learn((0, 9, 11), "UP", (0, 9, 12), confirmed=False)  # a guard walks us back DOWN
        mem.learn((0, 9, 11), "UP", (0, 9, 11), confirmed=False)  # or does not let us move at all
    assert "9,11,UP" in mem.m(0)["warps"] and not mem.m(0).get("warp_disproof")


def test_one_disproof_keeps_the_warp(tmp_path):
    mem = pallet_mem(tmp_path)
    disprove(mem)
    assert "9,11,UP" in mem.m(0)["warps"] and mem.m(0)["warp_disproof"]["9,11,UP"] == 1


def test_two_disproofs_pop_the_warp_without_a_tombstone(tmp_path):
    mem = pallet_mem(tmp_path)
    mem.m(0)["warp_cand"] = {"9,11,UP": 2}; mem.m(0)["warp_taken"] = {"9,11,UP": 8}
    disprove(mem, 2)
    d = mem.m(0)
    assert "9,11,UP" not in d["warps"] and "9,11,UP" not in d["warp_cand"] and "9,11,UP" not in d["warp_taken"]
    assert not mem.data.get("bad_warps") and "12,12,UP" in d["warps"]
    mem.learn((0, 9, 11), "UP", (40, 5, 11), confirmed=False)  # recoverable: two real sightings bring it back
    mem.learn((0, 9, 11), "UP", (40, 5, 11), confirmed=False)
    assert "9,11,UP" in d["warps"]


def forced_walk(mem, n=2):
    for _ in range(n):
        mem.learn((0, 9, 11), "UP", (40, 5, 11), confirmed=False)


def test_disproven_again_after_relearning_is_tombstoned(tmp_path):
    mem = pallet_mem(tmp_path)
    del mem.m(0)["warps"]["9,11,UP"]
    forced_walk(mem)                                   # learned from a forced walk
    assert "9,11,UP" in mem.m(0)["warps"]
    disprove(mem, 2)                                   # popped, recoverable
    assert "9,11,UP" not in mem.m(0)["warps"] and not mem.data.get("bad_warps")
    forced_walk(mem)                                   # re-learned (the real-warp reset zeroes the per-cycle count)
    assert "9,11,UP" in mem.m(0)["warps"]
    disprove(mem, 1)
    assert "9,11,UP" in mem.m(0)["warps"] and not mem.data.get("bad_warps")  # 3 in all: still a doubt
    disprove(mem, 1)
    assert "9,11,UP" not in mem.m(0)["warps"] and "0:9,11,UP" in mem.data["bad_warps"]
    forced_walk(mem)
    assert "9,11,UP" not in mem.m(0)["warps"]


def test_a_real_warp_resets_the_disproof_count(tmp_path):
    mem = pallet_mem(tmp_path)
    disprove(mem)
    mem.learn((0, 9, 11), "UP", (40, 5, 11), confirmed=False)
    assert "9,11,UP" not in mem.m(0).get("warp_disproof", {})
    disprove(mem)
    assert "9,11,UP" in mem.m(0)["warps"]


def test_deliver_parcel_route_does_not_ping_pong_after_a_walk(tmp_path):
    mem = pallet_mem(tmp_path)
    maps = mem.data["maps"]
    # before the fix the planner said DOWN at (9,10) and UP at (9,11): a two-tile oscillation
    disprove(mem, 2)  # the presses the agent actually makes
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


def ledge_mem(tmp_path) -> MapMemory:
    """Route 3 shape: a walkable row y=10 with a learned ledge DOWN from (14,10) to (14,12); (14,11) never stood on."""
    mem = MapMemory(tmp_path / "maps.json")
    d = mem.m(14)
    for x in (13, 14, 15):
        d["visited"][f"{x},10"] = 5
        d["visited"][f"{x},12"] = 5
    d.setdefault("jumps", {})["14,10,DOWN"] = [14, 12]
    for x in (13, 14, 15):  # close every other side so the ledge is the only candidate
        for n in ("UP",):
            d["blocked"].append(f"{x},10,{n}")
        d["blocked"].append(f"{x},12,DOWN")
        d["blocked"].append(f"{x},12,UP")
    for k in ("13,10,DOWN", "15,10,DOWN"):
        d["blocked"].append(k)
    for k in ("12,10", "16,10", "12,12", "16,12"):
        d["visited"][k] = 5
        d["blocked"] += [f"{k},UP", f"{k},DOWN", f"{k},LEFT", f"{k},RIGHT"]
    return mem


def test_ledge_side_counts_as_explored(tmp_path):
    mem = ledge_mem(tmp_path)
    assert not mem.is_frontier((14, 14, 10))  # (14,11) is hopped over; before the fix it stayed a 'frontier' forever
    assert mem.frontier_plan(14, 14, 10) is None


def test_choose_local_scores_a_ledge_by_its_landing(tmp_path):
    mem = ledge_mem(tmp_path)
    mem.m(14)["blocked"] += ["14,10,LEFT", "14,10,RIGHT"]
    name, why, want_frontier = mem.choose_local(14, 14, 10, "DOWN")
    assert name == "DOWN" and want_frontier  # landing seen 5x -> explored, not a fresh tile


# --- goals after Brock: east road -------------------------------------------------------------------------------

from pokeagent.goals import GOALS, check_goals  # noqa: E402

AFTER_BROCK = {g: True for g in GOALS[:GOALS.index("beat_brock") + 1]}
AFTER_BROCK.update({"to_route3": False, "to_route4": False, "to_mt_moon": False, "to_cerulean": False,
                    "_hp": (30, 30), "_level": 20, "_train_level": 8})


def test_east_road_goals_follow_seen_maps():
    emu = FakeEmulator({MAP: 0x0E, 0xD356: 1})
    st: dict = {}
    g = check_goals(emu, st)
    assert g["to_route3"] and not g["to_mt_moon"] and not g["to_route4"] and not g["to_cerulean"]
    for m, k in ((0x3B, "to_mt_moon"), (0x0F, "to_route4"), (0x03, "to_cerulean")):
        emu.set(MAP, m)
        assert check_goals(emu, st)[k]
    assert GOALS[-4:] == ["to_route3", "to_route4", "to_mt_moon", "to_cerulean"]


def test_east_road_uses_the_learned_world_then_pushes_to_the_edge(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    d = mem.m(2)  # Pewter: a row to a learned east connection into Route 3
    for x in range(5, 9):
        d["visited"][f"{x},10"] = 1
    d["warps"]["8,10,RIGHT"] = [14, 0, 10]
    r3 = mem.m(14)["visited"]
    for x, y in ((0, 10), (1, 10), (2, 10), (2, 9)):
        r3[f"{x},{y}"] = 1
    maps = mem.data["maps"]
    step = plan_step(AFTER_BROCK, maps, (2, 5, 10), "RIGHT")
    assert step[0] == "RIGHT" and "to_route3" in step[1]
    # Route 3 seen, Route 4 unmapped: go to the northernmost tile with an unknown UP, then push UP
    goals = {**AFTER_BROCK, "to_route3": True}
    step = plan_step(goals, maps, (14, 0, 10), "RIGHT")
    assert step[0] == "RIGHT" and "to_route4" in step[1] and "northernmost" in step[1]
    step = plan_step(goals, maps, (14, 2, 9), "UP")
    assert step == ("UP", "goal to_route4: at the northernmost open tile, pushing UP for the map edge")
    # from Pewter, go back through the learned connection to Route 3 first
    assert plan_step(goals, maps, (2, 5, 10), "RIGHT")[1].startswith("goal to_route4: ")
    # Route 4 seen: Mt Moon is a warp found by exploration
    assert plan_step({**goals, "to_route4": True}, maps, (0x0F, 3, 3), "UP") is None
