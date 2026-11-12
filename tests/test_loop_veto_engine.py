"""The loop veto in the engine: the same screen and the same button 3 times with no progress -> the 4th
decision asks the selector for another behaviour (Selector.choose(skip=...))."""
from __future__ import annotations

import json

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.blocked_cap import BLOCKED_PRESS_CAP, note
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.engine import Engine
from pokeagent.explorer.loop_memory import LOOP_NO_PROGRESS_N
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.selector import Selector

MAP, PX, PY, BATTLE = 0xD35E, 0xD362, 0xD361, 0xD057


class Stub:
    """A behaviour that always proposes the same button."""

    def __init__(self, name, button):
        self.name, self.button = name, button

    def applies(self, ctx):
        return True

    def step(self, ctx):
        return Decision(self.button, self.name + "_rule")


class SpySelector(Selector):
    def __init__(self, behaviours):
        super().__init__(behaviours)
        self.skips: list[frozenset] = []

    def choose(self, ctx, skip=frozenset()):
        self.skips.append(skip)
        return super().choose(ctx, skip)


def make_ctx(tmp_path, **fields):
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6, **fields.pop("memory", {})})
    mem = MapMemory(tmp_path / "maps.json")
    mem.m(0x28)["visited"]["5,6"] = 3  # stood here before: the first press is no 'tile' progress
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10, **fields)
    ctx.trans = (tmp_path / "t.jsonl").open("a", encoding="utf-8")
    return ctx


def rows(tmp_path):
    path = tmp_path / "loops.jsonl"
    return [json.loads(ln) for ln in path.read_text().splitlines()] if path.exists() else []


def test_same_screen_and_button_three_times_vetoes_the_fourth(tmp_path):
    ctx = make_ctx(tmp_path)
    logs = []
    ctx.log = lambda t, tag=None: logs.append(t)
    engine = Engine(ctx, selector=SpySelector([Stub("talker", "A"), Stub("mover", "DOWN")]))
    for _ in range(LOOP_NO_PROGRESS_N):
        assert engine.step().button == "A"
    d = engine.step()  # the 4th: the veto fires and the selector is asked again with talker skipped
    assert d.button == "DOWN" and d.behaviour == "mover"
    assert frozenset({"talker"}) in engine.selector.skips
    assert any("loop_veto" in t and "talker_rule" in t for t in logs)
    rows_ = rows(tmp_path)
    assert rows_[0]["kind"] == "veto" and rows_[0]["source"] == "run"
    assert rows_[0]["button"] == "A" and rows_[0]["no_progress"] == LOOP_NO_PROGRESS_N
    assert rows_[0]["veto_until"] == ctx.step + 60 - 1
    assert ctx.emu.presses[-1].name == "DOWN"


def test_veto_expires_then_re_arms(tmp_path):
    from pokeagent.explorer.loop_memory import LOOP_VETO_STEPS
    ctx = make_ctx(tmp_path)
    engine = Engine(ctx, selector=Selector([Stub("talker", "A"), Stub("mover", "DOWN")]))
    for _ in range(LOOP_NO_PROGRESS_N):
        engine.step()
    for _ in range(LOOP_VETO_STEPS):
        engine.step()  # vetoed: the mover presses DOWN while the veto holds
    assert engine.step().button == "A"  # the veto expired: the action is allowed once more


def test_veto_exhausted_when_every_alternative_is_dead_too(tmp_path):
    ctx = make_ctx(tmp_path)
    logs = []
    ctx.log = lambda t, tag=None: logs.append(t)
    engine = Engine(ctx, selector=Selector([Stub("a", "A"), Stub("b", "A"), Stub("c", "A")]))
    for _ in range(LOOP_NO_PROGRESS_N):
        engine.step()
    d = engine.step()  # every behaviour keeps proposing the dead button: the press goes through
    assert d.button == "A" and ctx.emu.presses[-1].name == "A"
    rows_ = rows(tmp_path)
    assert rows_[-1]["kind"] == "veto_exhausted"


def test_nothing_is_vetoed_inside_a_battle(tmp_path):
    ctx = make_ctx(tmp_path, memory={BATTLE: 1})
    engine = Engine(ctx, selector=Selector([Stub("plan_goal", "A")]))
    for _ in range(LOOP_NO_PROGRESS_N + 2):
        assert engine.step().button == "A"
    assert rows(tmp_path) == []


def test_never_veto_behaviours_are_never_vetoed(tmp_path):
    from pokeagent.explorer.loop_memory import NEVER_VETO
    for name in sorted(NEVER_VETO):
        (tmp_path / name).mkdir()
        ctx = make_ctx(tmp_path / name)
        engine = Engine(ctx, selector=Selector([Stub(name, "A")]))
        for _ in range(LOOP_NO_PROGRESS_N + 2):
            assert engine.step().button == "A"
        assert rows(tmp_path / name) == []


def test_blocked_move_vetoed_at_3_while_blocked_cap_counts_to_20(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.facing = "UP"  # already facing the wall: every press is the same situation
    engine = Engine(ctx, selector=Selector([Stub("walker", "UP"), Stub("mover", "DOWN")]))
    for _ in range(LOOP_NO_PROGRESS_N):
        engine.step()
    before = (0x28, 5, 6)
    assert ctx.blocked_streak[(before, "UP")] == LOOP_NO_PROGRESS_N  # the fast path counts on, unharmed
    d = engine.step()
    assert d.button == "DOWN" and rows(tmp_path)[0]["kind"] == "veto"
    streak = {}  # ... and the cap itself still fires on its own count
    assert all(not note(streak, before, "UP", False) for _ in range(BLOCKED_PRESS_CAP - 1))
    assert note(streak, before, "UP", False)


def test_a_ledger_row_sums_up_the_run_at_finish(tmp_path):
    ctx = make_ctx(tmp_path)
    engine = Engine(ctx, selector=Selector([Stub("talker", "A"), Stub("mover", "DOWN")]))
    for _ in range(LOOP_NO_PROGRESS_N + 1):
        engine.step()
    ctx.done = True
    engine.step()
    rows_ = rows(tmp_path)
    assert rows_[-1]["kind"] == "ledger" and rows_[-1]["top"][0]["button"] == "A"
    assert ctx.mem.data["loops"]["40,5,6,A"]["runs"] == [tmp_path.name]  # folded into shared memory (0x28 = 40)


def test_a_in_a_pokecenter_is_never_vetoed_even_with_a_dead_shared_entry(tmp_path):
    """Robert 2026-11-12: heals failed at the nurse - shared memory had '41,3,3,A' (Viridian counter) active."""
    import time
    center = 41  # Viridian Pokecenter
    emu_mem = {MAP: center, PX: 3, PY: 3}
    ctx = make_ctx(tmp_path, memory=emu_mem)
    ctx.mem.m(center)["visited"]["3,3"] = 3
    now = time.time()
    ctx.mem.data["loops"] = {f"{center},3,3,A": {"runs": ["r1", "r2", "r3"], "last": now, "clear": 0}}
    engine = Engine(ctx, selector=Selector([Stub("heal_walk", "A"), Stub("mover", "DOWN")]))
    for _ in range(LOOP_NO_PROGRESS_N + 3):
        assert engine.step().button == "A"
    assert [r for r in rows(tmp_path) if r.get("kind") in ("veto", "veto_exhausted")] == []
