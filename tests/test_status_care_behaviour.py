"""The StatusCare behaviour: applies only out of battle for a poisoned member, walks or uses an item, verifies."""
from __future__ import annotations

import json

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.status_care import MAX_PRESSES, MAX_TRIES, StatusCare
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.economy import outside_use
from pokeagent.explorer.economy.prices import ANTIDOTE
from pokeagent.explorer.memory import MapMemory

MAP, PX, PY, BATTLE = 0xD35E, 0xD362, 0xD361, 0xD057
COUNT, MON1, SIZE = 0xD163, 0xD16B, 44


def put_mon(mem: dict, slot: int, species: int, level: int, hp: int, max_hp: int, status: int = 0) -> None:
    base = MON1 + SIZE * slot
    for a, v in {base: species, base + 1: hp >> 8, base + 2: hp & 255, base + 4: status,
                 base + 33: level, base + 34: max_hp >> 8, base + 35: max_hp & 255}.items():
        mem[a] = v
    mem[0xD164 + slot] = species
    mem[COUNT] = max(mem.get(COUNT, 0), slot + 1)


def make_ctx(tmp_path, mem=None, **fields) -> ExplorerContext:
    emu = FakeEmulator({MAP: 0x0D, PX: 5, PY: 6, **(mem or {})})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path,
                          stable_frames=10, **fields)
    ctx.refresh()
    return ctx


def poison_ctx(tmp_path, hp=5, mx=40, **fields):
    mem = {}
    put_mon(mem, 0, 153, 14, hp, mx, status=0x08)
    return make_ctx(tmp_path, mem, **fields)


def test_applies_only_for_a_poisoned_member_out_of_battle(tmp_path):
    ctx = poison_ctx(tmp_path)
    assert StatusCare().applies(ctx)
    ctx.emu.set(BATTLE, 1)
    ctx.refresh()
    assert not StatusCare().applies(ctx)
    ctx = poison_ctx(tmp_path)
    ctx.view.box = True
    assert not StatusCare().applies(ctx)
    ctx = poison_ctx(tmp_path)
    ctx.center_intent = "x"
    assert not StatusCare().applies(ctx)
    ctx = poison_ctx(tmp_path)
    ctx.proc = {"name": "p"}
    assert not StatusCare().applies(ctx)
    clean = {}                       # same mon, status 0: never applies
    put_mon(clean, 0, 153, 14, 5, 40, status=0)
    ctx = make_ctx(tmp_path, clean)
    assert not StatusCare().applies(ctx)


def test_walk_row_sets_center_intent(tmp_path, monkeypatch):
    ctx = poison_ctx(tmp_path)       # hp 5 -> 17 steps to faint
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    b = StatusCare()
    assert b.applies(ctx) and b.step(ctx) is None
    assert ctx.center_intent == "status_care"


def test_poison_ok_row_is_quiet_and_logs_once_per_change(tmp_path, monkeypatch):
    ctx = poison_ctx(tmp_path, hp=40)   # 157 steps to faint > 100 + margin
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    lines = []
    ctx.log = lambda t, tag=None: lines.append(t)
    b = StatusCare()
    assert b.step(ctx) is None and ctx.center_intent is None
    ctx.step += 99
    assert b.step(ctx) is None
    assert len([l for l in lines if "status_care" in l]) == 1        # one line per change, not per step


def _seq_ctx(tmp_path, antidotes=1):
    mem = {}
    put_mon(mem, 0, 153, 14, 5, 40, status=0x08)
    mem[0xD31D] = 1
    mem[0xD31E], mem[0xD31F] = ANTIDOTE, antidotes
    ctx = make_ctx(tmp_path, mem)
    ctx.status_care["sig"] = (8,)    # pretend the poison was just seen
    return ctx


def test_verify_after_use_clears_on_the_status_byte(tmp_path):
    ctx = _seq_ctx(tmp_path)
    ctx.status_care["seq"] = {"item": ANTIDOTE, "slot": 0, "presses": 3, "tries": 0, "bag0": 1, "used_at": None}
    ctx.emu.set(0xD31F, 0)           # the Antidote left the bag
    ctx.emu.set(MON1 + 4, 0)         # ... and the poison bit cleared
    assert StatusCare().step(ctx) is None and ctx.status_care["seq"] is None


def test_a_failed_antidote_use_is_retried_at_most_max_tries(tmp_path, monkeypatch):
    ctx = _seq_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    b = StatusCare()
    for i in range(MAX_TRIES):
        d = b.step(ctx)              # starts the sequence (rope_press: empty screen -> START)
        assert d is not None and ctx.status_care["seq"] is not None
        for _ in range(MAX_PRESSES):
            d = b.step(ctx)
        assert ctx.status_care["seq"] is None and ctx.status_care["tries"] == i + 1
    assert ctx.status_care["items_out"]                               # written off for this poisoning
    assert ctx.center_intent == "status_care"                         # falls back to the nurse walk


def test_decision_row_written_with_provenance(tmp_path, monkeypatch):
    ctx = poison_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    StatusCare().step(ctx)
    row = json.loads((tmp_path / "status_care.jsonl").read_text().splitlines()[-1])
    assert row["event"] == "decision" and row["action"] == "walk_to_center" and row["provenance"] == "unknown"
