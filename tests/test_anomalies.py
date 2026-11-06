"""Anomaly detectors on synthetic sequences, rate limit, record + state writing, mitigation routing."""
from __future__ import annotations

import json

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import anomaly_detectors as ad
from pokeagent.explorer.anomalies import TEMP_BLOCK_FRAMES, WAIT_FRAMES, AnomalyMonitor
from pokeagent.explorer.anomaly_ram import bad_bcd, impossible_state
from pokeagent.explorer.anomaly_record import RATE_PRESSES, AnomalyLog, cause_hint
from pokeagent.explorer.anomaly_sprites import doorway_tiles, read_sprites
from pokeagent.explorer.behaviours import AnomalyWait, default_behaviours
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.press_frame import PressFrame

DOORS = doorway_tiles({"5,6,UP": [37, 2, 7]})   # (5,6) and the door tile (5,5)
WALK = {(5, 5), (5, 6), (5, 7), (4, 7), (6, 7)}


def obs(step=1, pos=(0, 5, 6), button="UP", prev=None, **kw) -> ad.Obs:
    return ad.Obs(step=step, frame=step * 10, map=pos[0], x=pos[1], y=pos[2], button=button,
                  prev=pos if prev is None else prev, wanderers={2}, doors=DOORS, walkable=WALK, **kw)


def run(det, n, **kw):
    out = []
    for i in range(n):
        out += det.update(obs(step=i, **kw))
    return out


def kinds(findings):
    return [f.type for f in findings]


def test_npc_in_doorway_fires_after_threshold_only():
    d = ad.Detectors()
    sprites = {2: (13, 5, 5)}
    assert "npc_in_doorway" not in kinds(run(d, ad.DOORWAY_PRESSES - 1, sprites=sprites, button="A"))
    out = d.update(obs(step=99, sprites=sprites, button="A"))
    f = next(f for f in out if f.type == "npc_in_doorway")
    assert f.details["npc_slot"] == 2 and f.details["npc_at"] == [5, 5] and (f.x, f.y) == (5, 5)


def test_npc_in_doorway_resets_when_it_steps_off_or_is_static():
    d = ad.Detectors()
    run(d, ad.DOORWAY_PRESSES - 1, sprites={2: (13, 5, 5)})
    d.update(obs(sprites={2: (13, 4, 5)}))  # moved away: the count restarts
    assert "npc_in_doorway" not in kinds(run(d, ad.DOORWAY_PRESSES - 1, sprites={2: (13, 5, 5)}))
    d2 = ad.Detectors()  # a guard that never moves (not in wanderers) is not trapped
    o = obs(sprites={2: (13, 5, 5)})
    o.wanderers = set()
    assert not [f for _ in range(40) for f in d2.update(o)]


def test_npc_blocking_path_needs_repeated_pressing_into_a_wanderer():
    d = ad.Detectors()
    sprites = {2: (13, 5, 5)}  # directly UP of the player at (5,6)
    assert "npc_blocking_path" not in kinds(run(d, ad.BLOCKING_PRESSES - 1, sprites=sprites))
    assert "npc_blocking_path" in kinds(d.update(obs(sprites=sprites)))
    d2 = ad.Detectors()  # pressing a direction the NPC is not in
    assert "npc_blocking_path" not in kinds(run(d2, 30, sprites=sprites, button="LEFT"))


def test_player_blocking_npc_when_standing_on_its_only_exit():
    d = ad.Detectors()
    sprites = {2: (13, 5, 5)}  # neighbours of (5,5): (5,6) is the player, (4,5)/(6,5)/(5,4) are not walkable
    out = run(d, ad.PLAYER_BLOCK_PRESSES + 1, sprites=sprites, button="A")
    assert "player_blocking_npc" in kinds(out)
    d2 = ad.Detectors()  # the NPC has another exit: not blocked
    out = []
    for i in range(30):
        o = obs(step=i, sprites=sprites, button="A")
        o.walkable = set(WALK) | {(4, 5)}
        out += d2.update(o)
    assert "player_blocking_npc" not in kinds(out)


def tp(det, **kw):
    """A teleport is held one observation; the next quiet press releases it."""
    return det.update(obs(pos=(0, kw.pop("to", 9), 6), prev=(0, 5, 6), **kw)) + det.update(obs(pos=(0, 9, 6)))


def test_teleport_flags_unexplained_jump_but_not_warps_ledges_or_map_changes():
    d = ad.Detectors()
    f = tp(d, button="RIGHT")
    assert kinds(f) == ["teleport"] and f[0].details["jump"] == 4
    assert not tp(ad.Detectors(), to=6)                                            # one tile
    d = ad.Detectors()
    assert not d.update(obs(pos=(1, 9, 6), prev=(0, 5, 6))) + d.update(obs())      # map change
    d = ad.Detectors()
    o = obs(pos=(0, 9, 6), prev=(0, 5, 6))
    o.warps = {"5,6,RIGHT": [0, 9, 6]}
    assert not d.update(o) + d.update(obs())                                       # warp inside the map
    o = obs(pos=(0, 5, 8), prev=(0, 5, 6), button="DOWN")
    o.jumps = {"5,6,DOWN": [5, 8]}
    assert not d.update(o) + d.update(obs())                                       # ledge
    assert not d.update(obs(pos=(0xC7, 5, 10), prev=(0xC7, 5, 6), button="DOWN")) + d.update(obs())  # spinner map


def test_teleport_suppressed_by_joypad_lock_or_text_box_around_it():
    assert not tp(ad.Detectors(), joy_ignore=0x30)                                 # forced walk
    assert not tp(ad.Detectors(), box_before=True)                                 # cutscene after a dialog
    d = ad.Detectors()
    d.update(obs(pos=(0, 9, 6), prev=(0, 5, 6)))
    assert not d.update(obs(box=True))                                             # a box opens next: whiteout / script


def test_impossible_state_is_debounced_and_checks_ram():
    d = ad.Detectors()
    assert not d.update(obs(broken=["hp_over_max slot0 30>20"]))
    assert kinds(d.update(obs(broken=["hp_over_max slot0 30>20"]))) == ["impossible_state"]
    d.update(obs(broken=[]))
    assert not d.update(obs(broken=["hp_over_max slot0 30>20"]))  # a one-off read during a fade is forgotten
    emu = FakeEmulator({0xD163: 7, 0xD16B: 0x99, 0xD16C: 0, 0xD16D: 30, 0xD18C: 0, 0xD18D: 0, 0xD18E: 20, 0xD347: 0x1A, 0xD35E: 0x77})
    got = impossible_state(emu, frozenset({0, 1}))
    assert any(g.startswith("party_count") for g in got) and any(g.startswith("hp_over_max") for g in got)
    assert any(g.startswith("level0") for g in got) and any(g.startswith("money") for g in got)
    assert any(g.startswith("map_id") for g in got)
    assert bad_bcd(b"\x1a\x00\x00") and not bad_bcd(b"\x09\x99\x00")
    assert impossible_state(FakeEmulator({0xD35E: 5}), None) == []


def test_frozen_screen_needs_varied_buttons_unchanged_screen_and_no_box():
    d, seq = ad.Detectors(), ["UP", "A", "B"]
    out = []
    for i in range(ad.FROZEN_PRESSES):
        out += d.update(obs(step=i, button=seq[i % 3], screen_sig=5))
    assert kinds(out) == ["frozen_screen"]
    d = ad.Detectors()  # bumping one wall repeatedly is just a wall
    assert not run(d, 80, button="UP", screen_sig=5)
    d = ad.Detectors()  # screen changes
    assert not [f for i in range(80) for f in d.update(obs(step=i, button=seq[i % 3], screen_sig=i))]
    d = ad.Detectors()  # joypad ignored (cutscene): presses are not accepted
    assert not [f for i in range(80) for f in d.update(obs(step=i, button=seq[i % 3], screen_sig=5, joy_ignore=0x30))]


def test_endless_battle_and_text():
    d = ad.Detectors()
    assert not run(d, ad.BATTLE_MAX_PRESSES - 1, battle=True, button="A", screen_sig=1)
    assert "endless_battle" in kinds(d.update(obs(battle=True, screen_sig=1)))
    d = ad.Detectors()
    assert not run(d, ad.TEXT_MAX_PRESSES - 1, box=True, button="A")
    assert "endless_text" in kinds(d.update(obs(box=True, button="A")))


def test_sprites_read_skips_player_empty_and_hidden_slots():
    emu = FakeEmulator({0xC110: 7, 0xC215: 22, 0xC214: 14, 0xC120: 9, 0xC122: 0xFF, 0xC100: 1})
    assert read_sprites(emu) == {1: (7, 18, 10)}


def test_rate_limit_one_record_per_type_map_tile_per_window(tmp_path):
    log = AnomalyLog(tmp_path, "r")
    assert log.allow("npc_in_doorway", 0, (5, 5), 100)
    assert not log.allow("npc_in_doorway", 0, (5, 5), 100 + RATE_PRESSES - 1)
    assert log.allow("npc_in_doorway", 0, (5, 5), 100 + RATE_PRESSES)
    assert log.allow("npc_in_doorway", 0, (6, 5), 101)       # other tile
    assert log.allow("npc_blocking_path", 0, (5, 5), 101)    # other type
    assert log.allow("npc_in_doorway", 1, (5, 5), 101)       # other map


def test_cause_hint():
    walked = [{"outcome": "moved"}]
    assert cause_hint("npc_in_doorway", (2, 13, 5, 5), (5, 6), walked) == "agent"
    assert cause_hint("npc_in_doorway", (2, 13, 5, 5), (5, 6), [{"outcome": "blocked"}]) == "unknown"
    assert cause_hint("npc_in_doorway", (2, 13, 5, 5), (9, 9), walked) == "game"
    assert cause_hint("teleport", None, (1, 1), []) == "game"
    assert cause_hint("frozen_screen", None, (1, 1), walked) == "unknown"


NPC = {"pic": 13, "slot": 1, "positions": {"5,5": 1, "4,5": 1}, "moves": True, "last": [5, 5], "talked": 1, "text": ""}


def make_ctx(tmp_path, extra=None):
    emu = FakeEmulator({0xD35E: 0, 0xD362: 5, 0xD361: 6, **(extra or {})})
    mem = MapMemory(tmp_path / "runs" / "maps.json")
    run_dir = tmp_path / "runs" / "explore-test"
    run_dir.mkdir(parents=True)
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=run_dir, stable_frames=10)
    ctx.anomalies = AnomalyMonitor.for_ctx(ctx)
    ctx.mem.m(0).setdefault("npcs", {})["slot1:pic13"] = dict(NPC)
    return ctx


SLOT1_AT_5_5 = {0xC110: 13, 0xC215: 9, 0xC214: 9}


def press_in_place(ctx, button="UP"):
    ctx.step += 1
    pos = ctx.pos()
    fr = PressFrame(button, "agent", "t", before=pos, after=pos)
    ctx.mem.observe_npcs(pos[0], ctx.emu, ctx.step)
    return ctx.anomalies.observe(ctx, fr)


def test_monitor_records_doorway_npc_with_state_png_and_decisions(tmp_path):
    ctx = make_ctx(tmp_path, SLOT1_AT_5_5)
    ctx.mem.m(0)["warps"]["5,6,UP"] = [37, 2, 7]
    for i in range(3):
        ctx.anomalies.note_decision({"step": i, "outcome": "moved", "button": "UP"})
    recs = []
    for _ in range(ad.DOORWAY_PRESSES + 5):
        recs += press_in_place(ctx)
    assert {"npc_in_doorway", "npc_blocking_path"} <= {r["type"] for r in recs}
    rec = next(r for r in recs if r["type"] == "npc_in_doorway")
    assert rec["cause_hint"] == "agent" and rec["map"] == 0 and rec["details"]["npc_at"] == [5, 5]
    assert len(rec["decisions"]) == 3
    stem = tmp_path / "runs" / "anomalies" / f"explore-test-{rec['step']}-npc_in_doorway"
    assert stem.with_suffix(".state").exists() and stem.with_suffix(".png").exists()
    lines = (tmp_path / "runs" / "anomalies.jsonl").read_text().splitlines()
    assert sum(json.loads(ln)["type"] == "npc_in_doorway" for ln in lines) == 1  # rate limited to one


def test_mitigation_waits_without_pressing_then_reroutes_with_temporary_block_not_a_wall(tmp_path):
    ctx = make_ctx(tmp_path, SLOT1_AT_5_5)
    md = ctx.mem.m(0)
    press_in_place(ctx)  # the blocked press creates the block
    mon = ctx.anomalies
    assert mon.block and mon.block.tile == (5, 5)
    ctx.refresh()
    wait = AnomalyWait()
    assert wait.applies(ctx)
    rules = []
    for _ in range(WAIT_FRAMES // 10 + 2):
        d = wait.step(ctx)
        assert d.button == ""  # nothing is pressed
        rules.append(d.rule)
        if d.rule == "reroute_npc":
            break
        ctx.frame += 10
    assert rules[-1] == "reroute_npc" and set(rules[:-1]) == {"wait_for_npc"} and len(rules) > 2
    assert (0, 5, 5) in ctx.mem.temp_blocked and mon.block is None
    assert "5,6,UP" not in md["blocked"]
    md["visited"].update({"5,6": 1, "5,5": 1, "5,7": 1})
    g = ctx.mem._frontier_graph()
    assert (0, 5, 5) not in {n for n, _ in g.neighbours((0, 5, 6))}
    name, _, _ = ctx.mem.choose_local(0, 5, 6, "UP")
    assert name != "UP"
    ctx.frame += TEMP_BLOCK_FRAMES
    press_in_place(ctx, "B")
    assert not ctx.mem.temp_blocked  # expired: the NPC tile is walkable again


def test_goto_keeps_its_goal_while_the_only_route_is_temporarily_blocked(tmp_path):
    from pokeagent.explorer.behaviours import Goto
    ctx = make_ctx(tmp_path)
    md = ctx.mem.m(0)
    md["visited"].update({"5,6": 1, "5,5": 1})
    ctx.goto = [0, 5, 5]
    ctx.mem.temp_blocked[(0, 5, 5)] = ctx.frame + TEMP_BLOCK_FRAMES
    ctx.refresh()
    d = Goto().step(ctx)
    assert d.button == "" and d.rule == "goto_wait" and ctx.goto == [0, 5, 5]
    ctx.frame += TEMP_BLOCK_FRAMES
    assert Goto().step(ctx).button == "UP" and ctx.goto == [0, 5, 5]


def test_failed_moves_into_a_person_are_not_walls_and_old_false_walls_are_purged(tmp_path):
    from pokeagent.explorer.memory_purge import purge_npc_walls
    mem = MapMemory(tmp_path / "m.json")
    for _ in range(5):
        assert "not a wall" in mem.learn((0, 5, 6), "UP", (0, 5, 6), confirmed=True, npc_ahead=True)
    assert "5,6,UP" not in mem.m(0)["blocked"] and not mem.m(0).get("fails")
    mem.learn((0, 5, 6), "UP", (0, 5, 6), confirmed=True)  # a real wall
    assert "5,6,UP" in mem.m(0)["blocked"]
    data = {"maps": {"0": {"blocked": ["5,6,UP", "9,9,LEFT", "bad"], "fails": {"5,6,UP": 3}, "npcs": {
        "slot2:pic13": {"moves": True, "positions": {"5,5": 970, "3,8": 5}},
        "slot3:pic9": {"moves": False, "positions": {"9,8": 50}}}}}}
    assert purge_npc_walls(data) == 1
    assert data["maps"]["0"]["blocked"] == ["9,9,LEFT", "bad"] and not data["maps"]["0"]["fails"]


def test_anomaly_files_are_capped_per_run(tmp_path):
    from pokeagent.explorer import anomaly_record as ar
    log = ar.AnomalyLog(tmp_path, "r")
    emu = FakeEmulator()
    f = ad.Finding("teleport", 0, 1, 1, (1, 1))
    for i in range(ar.MAX_FILES // 2 + 10):
        log.write(f, step=i, frame=i, emu=emu, decisions=[], player=(1, 1))
    assert len(list((tmp_path / "anomalies").glob("r-*"))) == ar.MAX_FILES
    assert not (tmp_path / "anomalies" / "r-0-teleport.state").exists()
    assert (tmp_path / "anomalies" / f"r-{ar.MAX_FILES // 2 + 9}-teleport.png").exists()


def test_wait_ends_early_when_the_npc_leaves(tmp_path):
    ctx = make_ctx(tmp_path, SLOT1_AT_5_5)
    press_in_place(ctx)
    assert ctx.anomalies.block
    ctx.emu.set(0xC215, 8)  # NPC steps to (4,5)
    ctx.refresh()
    assert AnomalyWait().step(ctx) is None  # the no-press wait notices and ends
    assert ctx.anomalies.block is None and not ctx.mem.temp_blocked


def test_anomaly_wait_is_registered_and_idle_without_a_monitor(tmp_path):
    assert any(isinstance(b, AnomalyWait) for b in default_behaviours())
    ctx = ExplorerContext(emu=FakeEmulator(), mem=MapMemory(tmp_path / "m.json"), opts=ExplorerOptions(), run_dir=tmp_path)
    ctx.refresh()
    assert not AnomalyWait().applies(ctx)
