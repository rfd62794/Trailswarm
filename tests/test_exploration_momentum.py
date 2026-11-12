"""Exploration momentum: reverse penalty + tabu in choose_local, committed frontier routes with
hysteresis, the reversal flag in decisions.jsonl, and tools/backtrack_report.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.frontier import TABU_LEN, Frontier, _frontier_move
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.decisions import DecisionLog
from pokeagent.explorer.engine import Engine
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.memory_nav import OPPOSITE
from pokeagent.explorer.perceive import DIRS

MAP, PX, PY = 0xD35E, 0xD362, 0xD361


def make_ctx(tmp_path, mem=None, map_id=1, x=4, y=5, **fields) -> ExplorerContext:
    emu = FakeEmulator({MAP: map_id, PX: x, PY: y})
    return ExplorerContext(emu=emu, mem=mem or MapMemory(tmp_path / "maps.json"),
                           opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10, **fields)


def corridor_mem(tmp_path, expensive=(3, 9), mid=(6, 3)):
    """1-wide corridor x=0..11 at y=0, all neighbours visited once except `expensive`/`mid` counts;
    UP/DOWN blocked everywhere, dead ends at both ends. No tile is a frontier."""
    mem = MapMemory(tmp_path / "maps.json")
    d = mem.m(1)
    for x in range(12):
        d["visited"][f"{x},0"] = 1
    d["visited"][f"{expensive[0]},0"] = expensive[1]
    d["visited"][f"{mid[0]},0"] = mid[1]
    for x in range(12):
        d["blocked"] += [f"{x},0,UP", f"{x},0,DOWN"]
    d["blocked"] += ["0,0,LEFT", "11,0,RIGHT"]
    return mem


def walk(mem, start, steps, *, momentum):
    """Drive choose_local like track_progress does: returns the button sequence and end position."""
    x, y = start
    last_dir, recent, buttons = None, {1: [(start[0], start[1])]}, []
    for i in range(steps):
        name, _, _ = mem.choose_local(1, x, y, "RIGHT", None, 0,
                                      last_dir=last_dir if momentum else None,
                                      tabu=set(recent.get(1, ())) if momentum else None,
                                      reverse_penalty=2 if momentum else 0)
        if name not in DIRS:
            break
        buttons.append(name)
        dx, dy = DIRS[name]
        x, y = x + dx, y + dy
        mem.visit(1, x, y, i)
        if momentum:
            last_dir = name
            recent.setdefault(1, []).append((x, y))
            del recent[1][:-TABU_LEN]
    return buttons, (x, y)


def reversals(buttons):
    return sum(1 for i in range(1, len(buttons)) if buttons[i] == OPPOSITE[buttons[i - 1]])


def test_corridor_old_rule_ping_pongs_new_rule_walks_out(tmp_path):
    old_buttons, _ = walk(corridor_mem(tmp_path / "old"), (4, 0), 10, momentum=False)
    new_buttons, end = walk(corridor_mem(tmp_path / "new"), (4, 0), 7, momentum=True)
    assert reversals(old_buttons) >= 3, old_buttons          # the trap the directive measured
    assert reversals(new_buttons) == 0, new_buttons          # momentum: no immediate undo
    assert end == (11, 0)                                    # and it reached the far end in 7 steps


def frontier_map(tmp_path, extra_open=()):
    """Corridor x=0..8 at y=5, all visited; UP/DOWN blocked except `extra_open` tiles' UP side.
    (0,5) LEFT and (8,5) RIGHT lead off-map: the two equidistant frontier tiles."""
    mem = MapMemory(tmp_path / "maps.json")
    d = mem.m(1)
    for x in range(9):
        d["visited"][f"{x},5"] = 1
    for x in range(9):
        d["blocked"] += [f"{x},5,UP", f"{x},5,DOWN"]
    for x in extra_open:
        d["blocked"].remove(f"{x},5,UP")
    return mem


def test_two_equidistant_frontiers_commits_to_one(tmp_path):
    ctx = make_ctx(tmp_path, mem=frontier_map(tmp_path), x=4, y=5, facing="RIGHT")
    targets, buttons = [], []
    for i in range(4):  # the committed route is four LEFTs to (0,5)
        ctx.refresh()
        d = Frontier().step(ctx)
        assert d.button == "LEFT", d.why
        buttons.append(d.button)
        targets.append(ctx.frontier_target)
        ctx.emu.set(PX, ctx.view.x - 1)   # simulate the press landing one tile left
        ctx.mem.visit(1, ctx.view.x - 1, 5, i)
        ctx.last_press, ctx.facing = "LEFT", "LEFT"
    assert set(targets) == {(1, 0, 5)}    # one target, never alternated with (1,8,5)
    assert buttons == ["LEFT"] * 4


def test_retarget_keeps_current_within_margin(tmp_path):
    ctx = make_ctx(tmp_path, mem=frontier_map(tmp_path, extra_open=(6,)), x=4, y=5)
    ctx.frontier_target, ctx.frontier_route, ctx.frontier_at = (1, 0, 5), [], None
    # nearest frontier is now (6,5) two steps away; current target is four: 4-2 < RETARGET_MARGIN
    name, why = _frontier_move(ctx, 1, 4, 5)
    assert name == "LEFT" and ctx.frontier_target == (1, 0, 5)


def test_retarget_switches_at_margin(tmp_path):
    ctx = make_ctx(tmp_path, mem=frontier_map(tmp_path, extra_open=(5,)), x=4, y=5)
    ctx.frontier_target, ctx.frontier_route, ctx.frontier_at = (1, 0, 5), [], None
    # nearest frontier is (5,5) one step away: 4-1 >= RETARGET_MARGIN -> switch
    name, why = _frontier_move(ctx, 1, 4, 5)
    assert name == "RIGHT" and ctx.frontier_target == (1, 5, 5)


def test_target_losing_frontier_status_replans(tmp_path):
    mem = frontier_map(tmp_path)
    mem.m(1)["visited"]["-1,5"] = 1  # (0,5)'s last open side is now visited: not a frontier any more
    ctx = make_ctx(tmp_path, mem=mem, x=4, y=5)
    ctx.frontier_target, ctx.frontier_route, ctx.frontier_at = (1, 0, 5), [], None
    name, why = _frontier_move(ctx, 1, 4, 5)
    assert ctx.frontier_target == (1, 8, 5) and name == "RIGHT"


def test_tabu_and_reverse_penalty_in_choose_local(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    d = mem.m(1)
    d["visited"].update({"4,5": 1, "6,5": 1})
    d["blocked"] += ["5,5,UP", "5,5,DOWN"]
    assert mem.choose_local(1, 5, 5, "RIGHT")[0] == "LEFT"          # tie -> fixed order
    assert mem.choose_local(1, 5, 5, "RIGHT", tabu={(4, 5)})[0] == "RIGHT"   # tabu +1 breaks the tie
    mem.m(1)["visited"]["6,5"] = 2
    assert mem.choose_local(1, 5, 5, "RIGHT")[0] == "LEFT"          # 1 < 2 without momentum
    assert mem.choose_local(1, 5, 5, "RIGHT", last_dir="RIGHT")[0] == "RIGHT"  # LEFT gets +2: 3 > 2
    mem.m(1)["visited"]["4,5"] = 1
    mem.m(1)["visited"]["6,5"] = 1
    # tie 1=1 with last_dir=RIGHT: LEFT is penalised (+2) and RIGHT continues straight -> RIGHT
    assert mem.choose_local(1, 5, 5, "RIGHT", last_dir="RIGHT", reverse_penalty=0)[0] == "RIGHT"


def _transitions(path: Path) -> None:
    moves = [
        ((1, 5, 5), (1, 6, 5), "RIGHT", "agent", True),
        ((1, 6, 5), (1, 5, 5), "LEFT", "agent", True),    # undo of move 1
        ((1, 5, 5), (1, 4, 5), "UP", "human", True),      # not an agent move: excluded
        ((1, 5, 5), (1, 6, 5), "RIGHT", "agent", True),   # undo of move 2 -> reversal + back-in-2
        ((1, 6, 5), (1, 7, 5), "RIGHT", "agent", True),
        ((1, 7, 5), (1, 6, 5), "LEFT", "agent", True),    # undo of move 5 -> reversal + back-in-2
        ((1, 6, 5), (1, 6, 5), "A", "agent", False),      # blocked: not a move
    ]
    with path.open("w", encoding="utf-8") as fh:
        for i, (frm, to, btn, src, moved) in enumerate(moves, start=1):
            fh.write(json.dumps({"step": i, "from": list(frm), "button": btn,
                                 "to": list(to), "moved": moved, "source": src}) + "\n")


def load_backtrack_report():
    spec = importlib.util.spec_from_file_location(
        "backtrack_report_test", Path(__file__).parents[1] / "tools" / "backtrack_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backtrack_report_counts_reversals_and_back_in_2(tmp_path, capsys):
    run = tmp_path / "explore-x"
    run.mkdir()
    _transitions(run / "transitions.jsonl")
    br = load_backtrack_report()
    s = br.backtrack_stats(run / "transitions.jsonl")
    assert s["moves"] == 5 and s["reversals"] == 3 and s["back_in_2"] == 2
    assert s["reversal_pct"] == 60.0 and s["back2_pct"] == 40.0
    assert br.main([str(run)]) == 0
    out = capsys.readouterr().out
    assert "60.0%" in out and "40.0%" in out and "5 agent moves" in out


def test_decision_log_marks_reversals(tmp_path):
    """Engine flags reversal when a press lands back on the previous move's origin."""
    ctx = make_ctx(tmp_path, map_id=0x28, x=5, y=6)
    hops = iter([(0x28, 6, 6), (0x28, 5, 6), (0x28, 6, 6), (0x28, 5, 6)])

    class Teleport:
        def press(self, name, source, why):
            m, x, y = next(hops)
            ctx.emu.set(MAP, m); ctx.emu.set(PX, x); ctx.emu.set(PY, y)

    log_path = tmp_path / "decisions.jsonl"
    engine = Engine(ctx, presser=Teleport(), decision_log=DecisionLog(log_path))
    for _ in range(4):
        engine.step()
    engine.decision_log.close()
    recs = [json.loads(ln) for ln in log_path.read_text(encoding="utf-8").splitlines()]
    assert [r["reversal"] for r in recs] == [False, True, True, True]


def test_a_wait_re_chosen_by_the_loop_veto_is_not_pressed(tmp_path, monkeypatch):
    """loop_veto can swap a dead press for a no-press wait (post_talk_settle); the engine must not press ''."""
    from pokeagent.explorer import engine as engine_mod
    from pokeagent.explorer.behaviours.base import Decision as D
    ctx = make_ctx(tmp_path, map_id=0x28, x=6, y=4)
    wait = D("", "post_talk_settle", "letting the screen redraw", behaviour="post_talk_settle")
    monkeypatch.setattr(engine_mod.loop_veto, "check", lambda c, s, d: wait)
    pressed = []

    class Rec:
        def press(self, name, source, why):
            pressed.append(name)

    engine = Engine(ctx, presser=Rec(), decision_log=DecisionLog(tmp_path / "decisions.jsonl"))
    assert engine.step() is wait
    engine.decision_log.close()
    assert pressed == []
