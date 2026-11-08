"""The explorer as behaviours: start conditions on scripted RAM, selector order, decision log, memory round-trip."""
from __future__ import annotations

import json

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours import (
    AdvanceDialog, Battle, BattleMoves, Catch, ExploreBurst, Frontier, Goto, Heal, LoopGuard, Menu, NamingKeyboard,
    Pickup, PlanGoal, Procedures, Readiness, ReplayBeat, ReplayInterrupt, SettleWait, StallGuard, default_behaviours,
)
from pokeagent.explorer.behaviours.base import Decision, no_press
from pokeagent.explorer.mash_skill import BOUND_FRAMES, WAIT, MashSkill, signature
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.decisions import FIELDS, DecisionLog, classify_outcome, goal_stage, make_record
from pokeagent.explorer.engine import Engine
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.selector import Selector

TM = 0xC3A0
MAP, PX, PY, BATTLE = 0xD35E, 0xD362, 0xD361, 0xD057


def make_ctx(tmp_path, memory=None, **fields) -> ExplorerContext:
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6, **(memory or {})})
    mem = MapMemory(tmp_path / "maps.json")
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10, **fields)
    return ctx


def put_box(ctx, menu: bool = False, text_rows=("HELLO THERE",)) -> None:
    """Draw a frame in the tile map: 0x79 0x7A top edge, then rows between 0x7C edges (CHARMAP letters at 0x80+)."""
    emu = ctx.emu
    emu.set(TM + 20 * 10, 0x79)
    emu.set(TM + 20 * 10 + 1, 0x7A)
    for r, text in enumerate(text_rows, start=11):
        emu.set(TM + 20 * r, 0x7C)
        emu.set(TM + 20 * r + 19, 0x7C)
        for i, ch in enumerate(text):
            emu.set(TM + 20 * r + 1 + i, 0x80 + (ord(ch) - ord("A")) if ch.isalpha() else 0x7F)
    if menu:
        emu.set(TM + 20 * 11 + 1, 0xED)


def applies(behaviour, ctx) -> bool:
    ctx.refresh()
    return behaviour.applies(ctx)


def test_settle_and_readiness_start_conditions(tmp_path):
    ctx = make_ctx(tmp_path)
    assert not applies(SettleWait(), ctx)
    ctx.settle = 30
    assert applies(SettleWait(), ctx)
    ctx.settle = 0
    assert not applies(Readiness(), ctx)  # the screen has been still for 10 frames
    ctx.stable_frames = 0
    assert applies(Readiness(), ctx)  # screen moving on its own: wait
    decision = Readiness().step(ctx)
    assert decision.button == "" and decision.rule.startswith("busy_wait") and ctx.mash == 1
    ctx.stable_frames = 10
    ctx.emu.set(0xCD6B, 1)  # the game says it ignores the joypad
    assert applies(Readiness(), ctx)


def test_readiness_ends_the_mash_without_pressing(tmp_path):
    ctx = make_ctx(tmp_path, mash=3)
    assert applies(Readiness(), ctx)
    assert Readiness().step(ctx) is None and ctx.mash == 0


def test_dialog_and_menu_start_conditions(tmp_path):
    ctx = make_ctx(tmp_path)
    assert not applies(AdvanceDialog(), ctx) and not applies(Menu(), ctx)
    put_box(ctx)
    assert applies(AdvanceDialog(), ctx) and not applies(Menu(), ctx)
    d = AdvanceDialog().step(ctx)
    assert (d.button, d.rule) == ("A", "advance_a")
    ctx2 = make_ctx(tmp_path)
    put_box(ctx2, menu=True)
    assert applies(Menu(), ctx2)
    assert AdvanceDialog().step(ctx2) is None  # a menu is the menu behaviour's


def test_stuck_dialog_and_menu_backs_out_with_b(tmp_path):
    ctx = make_ctx(tmp_path, box_streak=60)
    put_box(ctx)
    ctx.refresh()
    assert AdvanceDialog().step(ctx).rule == "dialog_stuck_b"
    ctx = make_ctx(tmp_path, box_streak=12)
    put_box(ctx, menu=True)
    ctx.refresh()
    assert AdvanceDialog().step(ctx).rule == "menu_stuck_b"


def test_naming_keyboard_presses_start(tmp_path):
    ctx = make_ctx(tmp_path)
    put_box(ctx, text_rows=("A B C D E F G H I",))
    assert applies(NamingKeyboard(), ctx)
    assert NamingKeyboard().step(ctx).button == "START"


def test_battle_behaviours_start_conditions(tmp_path):
    ctx = make_ctx(tmp_path)
    assert not applies(Battle(), ctx) and not applies(Catch(), ctx) and not applies(BattleMoves(), ctx)
    ctx.emu.set(BATTLE, 1)
    assert applies(Battle(), ctx)
    assert not applies(Catch(), ctx)  # needs the battle behaviour's read first
    assert Battle().step(ctx) is None and ctx.bv is not None and ctx.in_battle
    assert applies(Catch(), ctx) and applies(BattleMoves(), ctx)
    d = BattleMoves().step(ctx)
    assert (d.button, d.rule) == ("A", "fight")
    ctx.emu.set(BATTLE, 0)  # the fight ended: only the bookkeeping part of Battle still applies
    assert applies(Battle(), ctx) and not applies(Catch(), ctx)


def test_guards_and_wait_behaviours(tmp_path):
    ctx = make_ctx(tmp_path)
    assert applies(LoopGuard(), ctx) and applies(StallGuard(), ctx)
    assert LoopGuard().step(ctx) is None
    ctx.last_press, ctx.a_pos, ctx.a_streak = "A", (0x28, 5, 6), 39
    ctx.refresh()
    d = LoopGuard().step(ctx)  # the 40th A on one tile with no box: walk away, then shake
    assert d.rule == "a40_walk_away" and ctx.shake == 25
    ctx = make_ctx(tmp_path, stall=14, last_sig=(0x28, 5, 6, ()))
    ctx.refresh()
    d = StallGuard().step(ctx)
    assert d.rule == "stall_escalate" and ctx.stalls == 1


def test_goto_heal_replay_and_procedure_start_conditions(tmp_path):
    ctx = make_ctx(tmp_path)
    assert not applies(Goto(), ctx) and not applies(Heal(), ctx) and not applies(Procedures(), ctx)
    assert not applies(ReplayBeat(), ctx) and not applies(ReplayInterrupt(), ctx)
    ctx.goto = [0x28, 5, 5]
    assert applies(Goto(), ctx)
    ctx.mom_talk_step = 3
    assert applies(Heal(), ctx)
    ctx.proc_due = ["check_health"]
    assert applies(Procedures(), ctx)
    ctx.replay = ["A", "B"]
    assert applies(ReplayBeat(), ctx)
    assert not applies(ReplayInterrupt(), ctx)
    put_box(ctx)
    assert applies(ReplayInterrupt(), ctx)  # a box interrupted the replay


def test_replay_runs_buttons_then_grades(tmp_path):
    ctx = make_ctx(tmp_path, replay=["A", "B"], replay_ctx={"demo": {"source": "human", "grade": 0}, "pos": (0x28, 5, 6), "goals": {}})
    ctx.refresh()
    first = ReplayBeat().step(ctx)
    assert first.button == "A" and first.after is None
    last = ReplayBeat().step(ctx)
    assert last.button == "B" and last.after is not None  # graded right after the final press


def test_planner_and_frontier_always_apply_and_frontier_presses(tmp_path):
    ctx = make_ctx(tmp_path)
    for b in (ExploreBurst(), PlanGoal(), Frontier()):
        assert applies(b, ctx)
    ctx.refresh()
    d = Frontier().step(ctx)
    assert d.button in ("UP", "DOWN", "LEFT", "RIGHT", "A") and d.rule == "frontier"


def test_selector_picks_the_first_applicable_in_order(tmp_path):
    ran: list[str] = []

    class Stub:
        def __init__(self, name, ok, press):
            self.name, self.ok, self.press = name, ok, press

        def applies(self, ctx):
            return self.ok

        def step(self, ctx):
            ran.append(self.name)
            return Decision(self.press, self.name) if self.press else None

        def done(self, ctx):
            return False

        def failed(self, ctx):
            return False

    ctx = make_ctx(tmp_path)
    sel = Selector([Stub("a", False, "UP"), Stub("b", True, ""), Stub("c", True, "LEFT"), Stub("d", True, "DOWN")])
    d = sel.choose(ctx)
    assert (d.button, d.behaviour) == ("LEFT", "c")  # a skipped (does not apply), b passed (None), d never asked
    assert ran == ["b", "c"]
    assert sel.first_applicable(ctx).name == "b"
    assert Selector([Stub("x", False, "A")]).choose(ctx) is None


def test_default_order_is_the_old_agent_step_order():
    names = [b.name for b in default_behaviours()]
    assert names == ["settle", "guards", "party_order", "post_talk_settle", "readiness", "anomaly_wait", "replay_interrupt", "already_out", "battle_yesno", "battle_text_wait", "battle", "switch_out", "catch", "battle_moves", "cave_escape", "cave_topup", "use_items",
                     "naming_keyboard", "beat_start", "box_settle", "advance_dialog", "menu", "procedures", "goto", "replay_beat",
                     "stall_guard", "heal", "restock", "status_care", "use_items", "goal_talk", "grind_drill", "explore_burst", "pickup", "plan_goal", "learner_hunt", "team_hunt", "trainer_hunt", "frontier"]
    assert no_press("x").button == ""


def test_decision_helpers():
    assert goal_stage({"potion": True, "left_house": False}) == "left_house"
    assert goal_stage({}) == "potion"
    assert classify_outcome((1, 2, 3), (1, 2, 3), "UP", False, False) == "blocked"
    assert classify_outcome((1, 2, 3), (1, 2, 2), "UP", False, False) == "moved"
    assert classify_outcome((1, 2, 3), (2, 0, 0), "UP", False, False) == "map_change"
    assert classify_outcome((1, 2, 3), (1, 2, 3), "A", True, False) == "box"
    assert classify_outcome((1, 2, 3), (1, 2, 3), "A", False, False) == "none"
    assert classify_outcome((1, 2, 3), (1, 2, 2), "UP", False, True) == "goal"


def test_engine_presses_and_writes_complete_decision_lines(tmp_path):
    ctx = make_ctx(tmp_path)
    log_path = tmp_path / "runs" / "x" / "decisions.jsonl"
    ctx.trans = (tmp_path / "t.jsonl").open("a", encoding="utf-8")
    engine = Engine(ctx, decision_log=DecisionLog(log_path))
    for _ in range(4):
        engine.step()
    engine.decision_log.close()
    ctx.trans.close()
    lines = [json.loads(ln) for ln in log_path.read_text(encoding="utf-8").splitlines()]
    assert lines and len(lines) == len(ctx.emu.presses)
    for rec in lines:
        assert set(rec) == set(FIELDS)
        assert rec["outcome"] in {"moved", "blocked", "box", "map_change", "goal", "none"}
    assert lines[0]["step"] == 1 and lines[0]["map"] == 0x28 and lines[0]["goal_stage"] == "potion"
    assert make_record(1, "b", "r", "A", (1, 2, 3), "potion", False, False, "none").keys() == set(FIELDS)


def test_map_memory_round_trip_is_byte_identical(tmp_path):
    maps = {"maps": {"1": {"visited": {"3,4": 2}, "blocked": ["3,4,UP"], "warps": {"3,5,DOWN": [2, 0, 0]}, "last_seen": 7,
                           "interactions": {"3,4,UP": {"count": 1, "text": "HI", "presses": [], "menus": [], "choices": []}}}},
            "updated": "2026-01-01T00:00:00"}
    src = tmp_path / "maps.json"
    src.write_text(json.dumps(maps, indent=1))
    mem = MapMemory(src)
    mem.data["updated"] = maps["updated"]  # save() restamps this; everything else must come back untouched
    out = tmp_path / "out.json"
    mem.path = out
    mem.save()
    # save() writes a fresh "updated" stamp; compare the rest byte for byte by pinning it to the original
    data = json.loads(out.read_text())
    data["updated"] = maps["updated"]
    assert json.dumps(data, indent=1) == src.read_text()


@pytest.mark.parametrize("record_paths", [True, False])
def test_demo_mode_adds_no_paths_key(tmp_path, record_paths):
    mem = MapMemory(tmp_path / "m.json", record_paths=record_paths)
    assert mem.learn((1, 10, 10), "UP", (1, 10, 9), confirmed=True) == "moved"
    assert ("paths" in mem.m(1)) is record_paths


def test_explorer_package_layering_and_size():
    """pokeagent.explorer imports only the allowed framework layers (never tools/), and no module passes 300 lines."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "pokeagent" / "explorer"
    allowed = {"emulator", "ram", "screentext", "screencontext", "hexmap", "names", "goals", "navigation", "explorer", "ramstructs", "ramworld", "magikarp", "knowledge", "checkpoint_goals", "bandit", "campaign", "legs", "novelty", "training_progress", "segment_names"}  # segment_names: the start-state name heuristic (state_goal); novelty: the opt-in explorer-role steering and tracker hook; bandit: the opt-in decision-point hooks; campaign: main's hook; legs: par_follow routes on the ROM grid; training_progress: the loop memory's progress signal (explorer.progress)
    for f in root.rglob("*.py"):
        assert len(f.read_text(encoding="utf-8").splitlines()) <= 300, f"{f.name} is over 300 lines"
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [node.module] if isinstance(node, ast.ImportFrom) and node.module else \
                [a.name for a in node.names] if isinstance(node, ast.Import) else []
            for mod in mods:
                top = mod.split(".")
                assert top[0] not in ("tools", "explore_demo", "explore_plan"), f"{f.name} imports {mod}"
                if top[0] == "pokeagent":
                    assert len(top) > 1 and top[1] in allowed, f"{f.name} imports {mod}"


def test_map_memory_accepts_str_path(tmp_path):
    from pokeagent.explorer import MapMemory
    p = tmp_path / "maps.json"
    p.write_text('{"maps": {}}')
    assert MapMemory(str(p)).data == {"maps": {}}


def _lab_maps(*ball_spots, tried=()):
    inter = {f"{x},{y},UP": {"count": 5, "text": f"So! You want the {el} POKeMON, {sp}?"} for x, y, el, sp in ball_spots}
    inter.update({f"{x},{y},UP": {"count": 3, "text": "SIGN"} for x, y in tried})
    visited = {f"{x},{y}": 1 for x in range(3, 10) for y in (4, 5)}
    return {"40": {"visited": visited, "blocked": [], "warps": {}, "interactions": inter}}


def test_declined_starter_ball_is_remembered_and_another_is_tried(tmp_path):
    """After NO at the Charmander ball the agent must stop re-approaching it and walk to an untried neighbour."""
    from pokeagent.explorer.planner import plan_step
    maps = _lab_maps((6, 4, "fire", "CHARMANDER"), tried=[(5, 4)])
    goals = {"potion": 1, "left_house": 1, "_starter": "bulbasaur", "_declined": {(40, 6, 4, "UP")}}
    assert plan_step(goals, maps, (40, 6, 4), "UP")[0] == "RIGHT"  # (5,4) was tried; the declined ball is not offered again
    # the target is the (7,4) ball spot: standing there it takes the ball
    assert plan_step(goals, maps, (40, 7, 4), "UP")[0] == "A"
    maps = _lab_maps((6, 4, "fire", "CHARMANDER"), (7, 4, "water", "SQUIRTLE"), tried=[(5, 4)])
    goals["_declined"].add((40, 7, 4, "UP"))
    assert plan_step(goals, maps, (40, 7, 4), "UP")[0] == "RIGHT"
    assert plan_step(goals, maps, (40, 8, 4), "UP")[0] == "A"  # the third ball spot is the target


def test_empty_interaction_capture_does_not_exclude_a_ball_spot():
    from pokeagent.explorer.planner import plan_step
    goals = {"potion": 1, "left_house": 1, "_starter": "bulbasaur", "_declined": {(40, 6, 4, "UP")}}
    empty = _lab_maps((6, 4, "fire", "CHARMANDER"))
    empty["40"]["interactions"]["5,4,UP"] = {"count": 3, "text": ""}
    empty["40"]["interactions"]["7,4,UP"] = {"count": 3, "text": ""}
    # both neighbours are untried (empty captures); (5,4) comes first, so the planner heads to it
    assert plan_step(goals, empty, (40, 6, 4), "UP")[0] == "LEFT"
    texted = _lab_maps((6, 4, "fire", "CHARMANDER"), tried=[(5, 4)])
    assert plan_step(goals, texted, (40, 6, 4), "UP")[0] == "RIGHT"  # (5,4) has text: skipped


def test_will_trainer_change_pokemon_is_answered_no(tmp_path):
    """YES opens the party list on the active mon and the game answers '<name> is already out!' forever."""
    from pokeagent.explorer.dialog import yesno_answer
    assert yesno_answer("Will BCN change POKéMON?")[0] == "NO"
    assert yesno_answer("BUG CATCHER is about to use KAKUNA! Will BCN change POKeMON?")[0] == "NO"
    assert yesno_answer("Do you want to continue?")[0] == "YES"  # other boxes keep the default
    ctx = make_ctx(tmp_path)
    put_box(ctx, text_rows=("Will BCN", "change POKeMON?", " YES", " NO"))
    ctx.emu.set(TM + 20 * 13 + 1, 0xED)  # the cursor starts on YES
    ctx.refresh()
    d = Menu().step(ctx)
    assert (d.button, d.rule) == ("DOWN", "yesno_cursor")


def test_no_to_unwanted_starter_records_the_ball_and_readiness_does_not_reopen_it(tmp_path):
    ctx = make_ctx(tmp_path, memory={PX: 6, PY: 4})
    ctx.opts.starter = "bulbasaur"
    ctx.facing = "UP"
    put_box(ctx, text_rows=("WANT CHARMANDER", " YES", " NO"))
    ctx.emu.set(TM + 20 * 12 + 1, 0xED)  # the cursor on YES
    ctx.refresh()
    assert Menu().step(ctx).rule == "yesno_cursor"
    assert ctx.declined_balls == {(40, 6, 4, "UP"): "CHARMANDER"}
    ctx = make_ctx(tmp_path, memory={PX: 6, PY: 4}, declined_balls={(40, 6, 4, "UP"): "CHARMANDER"})
    ctx.facing, ctx.stable_frames = "UP", 0  # the box just closed; the screen is still settling
    force(ctx, "A/4")
    ctx.refresh()
    assert Readiness().step(ctx).button == "B"
    ctx.refresh()
    ctx.emu.set(0xD163, 1)  # a starter is in the party now: the old decline no longer matters
    ctx.frame += 10
    assert Readiness().step(ctx).button == "A" and not ctx.declined_balls


def test_readiness_still_presses_a_at_a_non_declined_spot(tmp_path):
    ctx = make_ctx(tmp_path, memory={PX: 7, PY: 4}, declined_balls={(40, 6, 4, "UP"): "CHARMANDER"})
    ctx.facing, ctx.stable_frames = "UP", 0
    force(ctx, "A/4")
    ctx.refresh()
    assert Readiness().step(ctx).button == "A"


def force(ctx, strategy):
    class Fixed(MashSkill):
        def choose(self, sig):
            return strategy
    ctx.skill = Fixed(ctx.mem.data)


def run_busy(ctx, ticks):
    out = []
    for _ in range(ticks):
        out.append(Readiness().step(ctx).button)
        ctx.frame += ctx.opts.frames_per_step
    return out


def test_readiness_wait_strategy_presses_once_per_bound(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.stable_frames = 0
    ctx.refresh()
    force(ctx, WAIT)
    n = BOUND_FRAMES // ctx.opts.frames_per_step
    assert run_busy(ctx, n * 2 + 2) == [""] * n + ["A"] + [""] * (n - 1) + ["A"] + [""]  # nothing between nudges


def test_readiness_a_strategy_presses_at_its_pace_and_learns_the_episode(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.stable_frames = 0
    ctx.refresh()
    force(ctx, "A/32")
    assert run_busy(ctx, 8) == ["A", "", "", "", "A", "", "", ""]  # 32 frames at 10f per decision
    ctx.stable_frames = 10  # resolved
    ctx.refresh()
    assert Readiness().step(ctx) is None and ctx.mash == 0
    e = ctx.mem.data["mash_skill"][signature(0x28, False, False)]["A/32"]
    assert e["n"] == 1 and e["mean_frames"] == 80 and e["mean_presses"] == 2


def test_mash_skill_prefers_the_faster_strategy_and_starts_unknowns_from_the_global_best(tmp_path):
    data: dict = {}
    sk = MashSkill(data)
    for s_ in ("WAIT", "A/4", "A/8", "A/16", "A/32"):
        sk.record("1|overworld|j0|", s_, 40 if s_ == "WAIT" else 90, 0 if s_ == "WAIT" else 8)
    sk.rng.random = lambda: 0.5  # no exploration
    assert sk.choose("1|overworld|j0|") == WAIT
    assert sk.choose("9|overworld|j0|") == WAIT  # unknown signature: the global best


def test_mash_skill_is_optimistic_about_untried_strategies():
    sk = MashSkill({})
    sk.rng.random = lambda: 0.5
    sk.record("s", WAIT, 50, 1)
    assert sk.choose("s") == "A/4"  # untried and nowhere measured: tried before settling


def test_readiness_waits_while_the_joypad_is_ignored(tmp_path):
    ctx = make_ctx(tmp_path, memory={0xCD6B: 1})
    ctx.refresh()
    assert Readiness().step(ctx).button == ""


def test_readiness_leaves_a_waiting_text_box_to_the_dialog_behaviour(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.stable_frames = 0
    put_box(ctx)
    ctx.refresh()
    assert not Readiness().applies(ctx)  # a box is waiting: advance_dialog presses, readiness does not
