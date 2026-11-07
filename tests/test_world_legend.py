"""World legend: tile-kind classify + precedence, both renderers, ledge-aware BFS, trainer marking,
goal-keyed tile outcomes (World_Legend_And_Ledges_Directive)."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import MapMemory, legend, tilekind
from pokeagent.explorer.behaviours.battle import Battle
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.decisions import DecisionLog
from pokeagent.explorer.engine import Engine
from pokeagent.explorer.perceive import ascii_vision
from pokeagent.navigation import shortest_path

TM = 0xC3A0
MAP, PX, PY, BATTLE, PARTY = 0xD35E, 0xD362, 0xD361, 0xD057, 0xD163


def synth_map() -> dict:
    """A per-map memory dict exercising every classify branch."""
    return {
        "visited": {"1,1": 3, "2,2": 1},
        "blocked": ["0,0,RIGHT", "5,7,UP"],  # targets (1,0) and (5,6)
        "warps": {"3,3,DOWN": [9, 0, 0]},
        "jumps": {"4,4,UP": [4, 2]},          # ledge tile (4,3), jump direction UP -> '^'
        "interactions": {
            "5,5,UP": {"count": 1, "text": "A SIGN"},    # spot (5,5); aims at (5,4)
            "6,6,LEFT": {"count": 1, "text": "PC"},      # aims at (5,6)
            "7,7,RIGHT": {"count": 1, "text": ""},       # no text: creates neither 'o' nor 'i'
        },
        "npcs": {
            "slot1:pic7": {"pic": 7, "slot": 1, "positions": {"8,8": 1}, "last": [8, 8],
                           "text": "", "talked": 0, "trainer": True},
            "slot2:pic9": {"pic": 9, "slot": 2, "positions": {"8,9": 1}, "last": [8, 9],
                           "text": "", "talked": 0, "trainer": True, "beaten": True},
        },
        "encounters": {"7,7": 3},
    }


def kind_at(d, x, y, block=None, npcs_here=(), trainers=None, tile_types=None, grass_ids=None):
    return tilekind.classify(d, tile_types or {}, grass_ids or {}, 1, x, y, block,
                             npcs_here, trainers if trainers is not None else tilekind.trainer_tiles(d))


def test_classify_kinds_and_precedence():
    d = synth_map()
    trainers = tilekind.trainer_tiles(d)
    # npc/trainer family first
    assert kind_at(d, 8, 8, trainers=trainers) == "trainer"
    assert kind_at(d, 8, 9, trainers=trainers) == "trainer_beaten"
    assert kind_at(d, 6, 6, npcs_here={(6, 6)}) == "npc"          # npc beats the 'i' spot it stands on
    assert kind_at(d, 3, 3, npcs_here={(3, 3)}) == "npc"          # npc beats warp
    # warp, ledge
    assert kind_at(d, 3, 3) == "warp"
    assert kind_at(d, 4, 3) == "ledge"                            # (4,4) jumped UP to (4,2): ledge at (4,3)
    # object beats wall: (5,6) is BOTH an interaction target and a blocked-edge target
    assert kind_at(d, 5, 6) == "object"
    assert kind_at(d, 5, 4) == "object"                           # sign target, never walked on
    assert kind_at(d, 8, 7) == "unknown"                          # the text-less interaction aimed here: nothing
    # wall from a blocked edge, and from learned-solid tile ids
    assert kind_at(d, 1, 0) == "wall"
    solid = {"1": {"20,20,20,20": {"solid": 5, "walkable": 0}}}
    assert kind_at(d, 2, 9, block=[0x20] * 4, tile_types=solid) == "wall"
    # encounter, grass, interaction, walkable, unknown - grass needs the live block ids
    assert kind_at(d, 7, 7) == "encounter"
    grass = {"1": {"10,10,10,10": 4}}
    assert kind_at(d, 9, 8, block=[0x10] * 4, grass_ids=grass) == "grass"
    assert kind_at(d, 3, 3, block=[0x10] * 4, grass_ids=grass) == "warp"  # warp beats grass
    assert kind_at(d, 5, 5) == "interaction"
    assert kind_at(d, 1, 1) == "walkable"
    walk = {"1": {"30,30,30,30": {"solid": 0, "walkable": 5}}}
    assert kind_at(d, 3, 9, block=[0x30] * 4, tile_types=walk) == "walkable"  # learned walkable, unvisited
    assert kind_at(d, 9, 9) == "unknown"


def test_legend_glyph_and_line():
    assert legend.glyph("ledge", "DOWN") == "v" and legend.glyph("ledge", "UP") == "^"
    assert legend.glyph("ledge", "LEFT") == "<" and legend.glyph("ledge", "RIGHT") == ">"
    assert legend.glyph("trainer_beaten") == "t" and legend.glyph("you") == "@"
    assert legend.line({"walkable", "unknown"}) == ". visited / learned walkable  ? never tried"
    assert "~" not in legend.line({"walkable"}) and "grass" not in legend.line({"walkable"})


def _block_offsets(c: int, r: int) -> list[int]:
    """Tilemap byte offsets of screen tile (c,r)'s four block ids."""
    return [(2 * r) * 20 + 2 * c, (2 * r) * 20 + 2 * c + 1, (2 * r + 1) * 20 + 2 * c, (2 * r + 1) * 20 + 2 * c + 1]


def _set_block(emu, c: int, r: int, val: int) -> None:
    for off in _block_offsets(c, r):
        emu.set(TM + off, val)


def test_ascii_vision_renders_legend(tmp_path):
    """Player at map (5,5) on map 1: screen tile (c,r) shows map tile (c+1, r+1)."""
    emu = FakeEmulator({TM + i: 0x10 for i in range(360)} | {MAP: 1, PX: 5, PY: 5})
    for c, r, val in [(5, 4, 0x30), (4, 3, 0x30), (8, 4, 0x20), (8, 8, 0x30)]:
        _set_block(emu, c, r, val)  # non-grass blocks: interaction spot, walkable, wall, unknown
    # live NPC sprites: slot1 trainer-ish at (8,8), slot2 at (8,9), slot3 plain at (7,7)
    emu.set(0xC110, 7); emu.set(0xC215, 12); emu.set(0xC214, 12)
    emu.set(0xC120, 9); emu.set(0xC225, 12); emu.set(0xC224, 13)
    emu.set(0xC130, 5); emu.set(0xC235, 11); emu.set(0xC234, 11)
    mem = MapMemory(tmp_path / "maps.json")
    mem.data["maps"]["1"] = {
        "visited": {"5,4": 1},
        "blocked": [], "warps": {"6,6,DOWN": [1, 0, 0]}, "jumps": {"4,4,DOWN": [4, 6]},
        "interactions": {"6,5,LEFT": {"count": 1, "text": "HI"}, "7,4,DOWN": {"count": 1, "text": "SIGN"}},
        "npcs": {
            "slot1:pic7": {"pic": 7, "slot": 1, "positions": {"8,8": 1}, "last": [8, 8],
                           "text": "", "talked": 0, "trainer": True},
            "slot2:pic9": {"pic": 9, "slot": 2, "positions": {"8,9": 1}, "last": [8, 9],
                           "text": "", "talked": 0, "trainer": True, "beaten": True},
        },
        "encounters": {"5,7": 2}, "last_seen": 0,
    }
    mem.data["tile_types"] = {"1": {"20,20,20,20": {"solid": 5, "walkable": 0}}}
    mem.data["grass_ids"] = {"1": {"10,10,10,10": 9}}
    sees = ascii_vision(emu, mem, 1)
    assert isinstance(sees, list) and len(sees) == 9 and "\n".join(sees)
    assert sees[4][4] == "@"    # (5,5) you
    assert sees[5][5] == "W"    # (6,6) warp
    assert sees[4][3] == "v"    # (4,5) ledge, jump DOWN
    assert sees[6][4] == "!"    # (5,7) encounter
    assert sees[4][6] == "o"    # (7,5) object (sign target)
    assert sees[4][5] == "i"    # (6,5) interaction spot
    assert sees[3][4] == "."    # (5,4) visited walkable
    assert sees[4][8] == "#"    # (9,5) learned-solid wall
    assert sees[8][8] == "?"    # (9,9) unknown
    assert sees[7][7] == "T"    # (8,8) trainer
    assert sees[8][7] == "t"    # (8,9) beaten trainer
    assert sees[6][6] == "N"    # (7,7) plain NPC (live sprite, no memory entry)
    assert sees[2][2] == "~"    # (3,3) grass
    assert isinstance(sees.legend, str) and "~" in sees.legend and "v^<>" in sees.legend and "@" in sees.legend


def test_render_memory_renders_legend(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    mem.data["maps"]["1"] = {
        "visited": {"5,4": 1, "1,1": 3},
        "blocked": ["3,3,RIGHT"],                     # target (4,3) -> '#'
        "warps": {"6,6,DOWN": [1, 0, 0]},
        "jumps": {"4,4,DOWN": [4, 6]},                # ledge tile (4,5) -> 'v'
        "interactions": {
            "4,6,UP": {"count": 1, "text": "sign"},   # spot (4,6) -> 'i'; aims at the ledge tile (4,5)
            "7,4,DOWN": {"count": 1, "text": "pc"},   # aims at (7,5) -> 'o'
        },
        "npcs": {
            "slot1:pic7": {"pic": 7, "slot": 1, "positions": {"8,8": 1}, "last": [8, 8],
                           "text": "", "talked": 0, "trainer": True},
            "slot2:pic9": {"pic": 9, "slot": 2, "positions": {"8,9": 1}, "last": [8, 9],
                           "text": "", "talked": 0, "trainer": True, "beaten": True},
        },
        "encounters": {"5,7": 2}, "last_seen": 0,
    }
    rows = mem.render_memory(1, 5, 5, {(7, 7)})  # 13x13 around (5,5): tile (tx,ty) at row ty+1, col tx+1
    assert isinstance(rows, list) and len(rows) == 13 and "\n".join(rows)
    assert rows[6][6] == "@"     # (5,5) you
    assert rows[8][8] == "N"     # (7,7) npc
    assert rows[9][9] == "T"     # (8,8) trainer
    assert rows[10][9] == "t"    # (8,9) beaten trainer
    assert rows[7][7] == "W"     # (6,6) warp
    assert rows[6][5] == "v"     # (4,5) ledge
    assert rows[7][5] == "i"     # (4,6) interaction spot
    assert rows[6][8] == "o"     # (7,5) object
    assert rows[4][5] == "#"     # (4,3) wall (blocked-edge target)
    assert rows[8][6] == "!"     # (5,7) encounter
    assert rows[5][6] == "."     # (5,4) visited
    assert rows[2][2] == "."     # (1,1) visited
    assert rows[10][10] == "?"   # (9,9) unknown
    # Remembers has no live tilemap: grass (~) cannot be classified per-tile, so its legend row is absent
    # (the word "grass" itself still appears inside the encounter kind's meaning).
    assert "~" not in rows.legend and "block id is in grass_ids" not in rows.legend
    assert "v^<>" in rows.legend and "?" in rows.legend


def test_shortest_path_uses_one_way_ledge_jumps():
    memory = {"maps": {"1": {
        "visited": {"0,0": 1, "1,0": 1, "2,0": 1},
        "blocked": ["2,2,UP"],       # learn() adds a jump's reverse edge to blocked
        "warps": {},
        "jumps": {"2,0,DOWN": [2, 2]},
        "last_seen": 0}}}
    # (0,0) -> (1,0) -> (2,0) -> jump DOWN -> (2,2): RIGHT, RIGHT, DOWN
    assert shortest_path(memory, 1, 0, 0, 2, 2) == [3, 3, 1]
    assert shortest_path(memory, 1, 2, 2, 0, 0) is None  # the ledge cannot be climbed back up
    no_jump = {"maps": {"1": {"visited": {"0,0": 1, "1,0": 1, "2,0": 1}, "blocked": [], "warps": {},
                               "jumps": {}, "last_seen": 0}}}
    assert shortest_path(no_jump, 1, 0, 0, 2, 2) is None


def test_trainer_marked_on_flag2_and_beaten_on_win(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    mem.m(0x28).setdefault("npcs", {})["slot1:pic7"] = {"pic": 7, "slot": 1, "positions": {"6,6": 1},
                                                       "last": [6, 6], "text": "", "talked": 1}
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6, BATTLE: 2, PARTY: 1})
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10)
    ctx.refresh()
    assert Battle().step(ctx) is None
    npc = mem.m(0x28)["npcs"]["slot1:pic7"]
    assert npc["trainer"] is True and "beaten" not in npc
    emu.set(BATTLE, 0)
    ctx.refresh()
    Battle().step(ctx)  # battle over, still standing, party alive -> won -> beaten
    assert npc["beaten"] is True


def test_record_outcome_aggregates_n_progress_best(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    mem.record_outcome(1, 3, 4, "UP", "potion", True, 12)
    mem.record_outcome(1, 3, 4, "UP", "potion", True, 9)
    mem.record_outcome(1, 3, 4, "UP", "potion", False, None)
    mem.record_outcome(1, 3, 4, "UP", "left_house", True, 30)
    e = mem.m(1)["outcomes"]["3,4,UP"]
    assert e["potion"] == {"n": 3, "progress": 2, "best": 9}
    assert e["left_house"] == {"n": 1, "progress": 1, "best": 30}


def test_engine_backfills_goal_keyed_outcomes(tmp_path):
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6})
    mem = MapMemory(tmp_path / "maps.json")
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10)
    ctx.trans = (tmp_path / "t.jsonl").open("a", encoding="utf-8")
    engine = Engine(ctx, decision_log=DecisionLog(tmp_path / "decisions.jsonl"))
    engine.step()  # a real press: the record lands in the pending segment
    assert engine._pending_outcomes
    engine._pending_outcomes = [
        {"map": 1, "x": 2, "y": 3, "button": "UP", "goal_stage": "potion", "outcome": "moved", "step": 10},
        {"map": 1, "x": 2, "y": 3, "button": "UP", "goal_stage": "potion", "outcome": "blocked", "step": 12},
    ]
    engine._flush_outcomes(20)  # goal reached at step 20: presses_to_goal 10 and 8
    assert mem.m(1)["outcomes"]["2,3,UP"]["potion"] == {"n": 2, "progress": 1, "best": 8}
    assert engine._pending_outcomes == []
    engine.decision_log.close()
    ctx.trans.close()


def test_stop_at_goal_final_segment_outcomes_are_saved(tmp_path):
    """The goal press sets ctx.done and saves inside the press; the outcomes must still reach maps.json."""
    import json
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6})
    mem = MapMemory(tmp_path / "maps.json")
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(stop_at_goal="potion"), run_dir=tmp_path, stable_frames=10)
    ctx.trans = (tmp_path / "t.jsonl").open("a", encoding="utf-8")

    class GoalPresser:
        def press(self, button, who, why):
            ctx.step += 1
            ctx.goal_steps["potion"] = ctx.step
            ctx.done = True
            ctx.mem.save()  # what shutdown() does inside the goal press

    engine = Engine(ctx, presser=GoalPresser(), decision_log=DecisionLog(tmp_path / "decisions.jsonl"))
    engine._pending_outcomes = [
        {"map": 1, "x": 2, "y": 3, "button": "UP", "goal_stage": "potion", "outcome": "moved", "step": 0}]
    engine.step()
    saved = json.loads((tmp_path / "maps.json").read_text())
    assert any(e.get("potion") for m in saved["maps"].values() for e in m.get("outcomes", {}).values())
    engine.decision_log.close()
    ctx.trans.close()


def test_pending_outcomes_are_capped(tmp_path):
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10)
    ctx.trans = (tmp_path / "t.jsonl").open("a", encoding="utf-8")
    engine = Engine(ctx)
    engine._pending_outcomes = [{"step": i} for i in range(2000)]
    engine.step()  # a real press appends one more
    assert len(engine._pending_outcomes) == 2000
    assert engine._pending_outcomes[0]["step"] == 1  # the oldest was dropped
    ctx.trans.close()


def test_classify_strict_flag_controls_wall_rule():
    d = synth_map()
    block = [0x20] * 4
    weak = {"1": {"20,20,20,20": {"solid": 2, "walkable": 1}}}
    # old Sees rule: solid > walkable draws a wall; strict (Remembers) needs solid>=3 and walkable==0
    assert kind_at(d, 40, 40, block, tile_types=weak) != "wall"
    args = (d, weak, {}, 1, 40, 40, block, (), tilekind.trainer_tiles(d))
    assert tilekind.classify(*args, strict=False) == "wall"
    assert tilekind.classify(*args, strict=True) != "wall"
