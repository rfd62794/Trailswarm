"""The StatusCare behaviour: applies only out of battle for a poisoned member, walks or uses an item, verifies."""
from __future__ import annotations

import json

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.status_care import MAX_PRESSES, MAX_TRIES, StatusCare
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.economy import outside_use
from pokeagent.explorer.economy.prices import ANTIDOTE
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.status_care import of

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


def _road_to_center(ctx):
    """Map 0x0D with a visited road tile and a recorded warp (5,7) DOWN into a Pokecenter (map 0x40)."""
    ctx.mem.data["maps"] = {"13": {"visited": {"5,6": 1, "5,7": 1}, "blocked": [], "warps": {"5,7,DOWN": [0x40, 3, 7]}}}


def test_walk_row_requests_a_heal_walk_that_presses_toward_the_center(tmp_path, monkeypatch):
    ctx = poison_ctx(tmp_path)       # hp 5 -> 17 steps to faint
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    _road_to_center(ctx)
    b = StatusCare()
    assert b.applies(ctx)
    d = b.step(ctx)
    assert d is not None and d.button == "DOWN" and d.rule == "heal_walk"     # a real press toward the nurse
    assert of(ctx)["walk"] is not None and ctx.center_intent is None
    # the request survives: PlanGoal-free steps keep walking; the next step, one tile on, presses on
    ctx.emu.set(PY, 7)
    ctx.refresh()
    assert b.applies(ctx) and b.step(ctx).button == "DOWN"
    ctx.view.m = 0x40                                          # inside the center: cross to x=3 (we stand at x=5)
    d = b.step(ctx)
    assert d.button == "LEFT" and ctx.center_intent == "status_care"


def test_heal_walk_is_abandoned_with_a_logged_reason_when_no_route_is_known(tmp_path, monkeypatch):
    ctx = poison_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    lines = []
    ctx.log = lambda t, tag=None: lines.append(t)
    b = StatusCare()
    assert b.step(ctx) is None and of(ctx).get("walk") is None          # no graph: abandoned, not stuck
    assert any("abandoned" in l and "no known route" in l for l in lines)
    from pokeagent.explorer import heal_walk
    assert not heal_walk.start(ctx, "again")                            # cooling down: no restart loop


def test_walk_ends_when_the_party_is_healed(tmp_path, monkeypatch):
    ctx = poison_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    _road_to_center(ctx)
    b = StatusCare()
    b.step(ctx)
    ctx.emu.set(MON1 + 4, 0)                                   # the nurse cured the poison
    assert b.step(ctx) is None and of(ctx).get("walk") is None


def test_poison_ok_row_is_quiet_and_logs_once_per_change(tmp_path, monkeypatch):
    ctx = poison_ctx(tmp_path, hp=40)   # 157 steps to faint > 100 + margin
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    lines = []
    ctx.log = lambda t, tag=None: lines.append(t)
    b = StatusCare()
    assert b.step(ctx) is None and ctx.center_intent is None and of(ctx).get("walk") is None
    ctx.step += 99
    assert b.step(ctx) is None
    assert len([l for l in lines if "status_care" in l]) == 1        # one line per change, not per step


def _seq_ctx(tmp_path, antidotes=1):
    mem = {}
    put_mon(mem, 0, 153, 14, 5, 40, status=0x08)
    mem[0xD31D] = 1
    mem[0xD31E], mem[0xD31F] = ANTIDOTE, antidotes
    ctx = make_ctx(tmp_path, mem)
    of(ctx)["sig"] = (8,)    # pretend the poison was just seen
    return ctx


def test_verify_after_use_clears_on_the_status_byte(tmp_path):
    ctx = _seq_ctx(tmp_path)
    of(ctx)["seq"] = {"item": ANTIDOTE, "slot": 0, "presses": 3, "tries": 0, "bag0": 1, "used_at": None}
    ctx.emu.set(0xD31F, 0)           # the Antidote left the bag
    ctx.emu.set(MON1 + 4, 0)         # ... and the poison bit cleared
    assert StatusCare().step(ctx) is None and of(ctx)["seq"] is None


def test_a_failed_antidote_use_is_retried_at_most_max_tries(tmp_path, monkeypatch):
    ctx = _seq_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    b = StatusCare()
    for i in range(MAX_TRIES):
        d = b.step(ctx)              # starts the sequence (rope_press: empty screen -> START)
        assert d is not None and of(ctx)["seq"] is not None
        for _ in range(MAX_PRESSES):
            d = b.step(ctx)
        assert of(ctx)["seq"] is None and of(ctx)["tries"] == i + 1
    assert of(ctx)["items_out"]                               # written off for this poisoning
    assert of(ctx)["walk"] is not None                                # falls back to the nurse walk


def test_applies_is_a_pure_read(tmp_path, monkeypatch):
    ctx = poison_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    before = dict(of(ctx))
    b = StatusCare()
    assert b.applies(ctx) and b.applies(ctx)
    assert of(ctx) == before and not (tmp_path / "status_care.jsonl").exists()


def test_decision_row_written_with_provenance(tmp_path, monkeypatch):
    ctx = poison_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    StatusCare().step(ctx)
    rows = [json.loads(l) for l in (tmp_path / "status_care.jsonl").read_text().splitlines()]
    row = next(r for r in rows if r["event"] == "decision")             # (then the walk is abandoned: no graph here)
    assert row["action"] == "walk_to_center" and row["provenance"] == "unknown"


def test_record_row_failure_is_logged_once(tmp_path, caplog):
    from pokeagent.explorer.status_care import record_row
    ctx = poison_ctx(tmp_path)
    ctx.run_dir = tmp_path / "missing" / "dir"                       # the append fails: no such directory
    with caplog.at_level("WARNING"):
        record_row(ctx, {"event": "x"})
        record_row(ctx, {"event": "y"})
    assert sum("status_care.jsonl row not written" in r.message for r in caplog.records) == 1


def test_status_bits_come_from_catch_math_and_start_lineage_says_why(tmp_path, caplog):
    from pokeagent import checkpoint_goals as cg
    from pokeagent.explorer.status_care import status_kinds
    from pokeagent.knowledge import catch_math as cm
    assert status_kinds(cm.PSN_BIT) == frozenset({"poison"}) and status_kinds(cm.PAR_BIT) == frozenset({"paralysis"})
    cg._LINEAGE_LOGGED.clear()
    with caplog.at_level("WARNING"):
        assert cg.start_lineage(tmp_path / "none.state") == "unknown"
        assert cg.start_lineage(tmp_path / "none.state") == "unknown"
    assert sum("no readable fingerprint" in r.message for r in caplog.records) == 1


def _walking_ctx(tmp_path, monkeypatch):
    from pokeagent.explorer import heal_walk
    ctx = poison_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 100, 0, 0x40))
    assert heal_walk.start(ctx, "test")
    return ctx, heal_walk


def test_heal_walk_in_center_sequence(tmp_path, monkeypatch):
    ctx, hw = _walking_ctx(tmp_path, monkeypatch)
    ctx.view.m, ctx.view.x, ctx.view.y, ctx.facing = 0x40, 5, 7, "DOWN"       # just inside the door, off the column
    assert hw.step(ctx).button == "LEFT"
    ctx.view.x = 1
    assert hw.step(ctx).button == "RIGHT"
    ctx.view.x = 3
    assert hw.step(ctx).button == "UP" and ctx.center_intent == "status_care"  # up the column
    ctx.view.y = 3                                                             # the counter row, still facing DOWN
    assert hw.step(ctx).button == "UP"                                         # face the nurse
    ctx.facing = "UP"
    assert hw.step(ctx).button == "A"                                          # talk


def test_heal_walk_cap_abandons_with_a_logged_reason(tmp_path, monkeypatch):
    ctx, hw = _walking_ctx(tmp_path, monkeypatch)
    lines = []
    ctx.log = lambda t, tag=None: lines.append(t)
    of(ctx)["walk"]["steps"] = hw.WALK_CAP
    assert hw.step(ctx) is None and of(ctx).get("walk") is None
    assert any("abandoned" in l and f"{hw.WALK_CAP} steps" in l for l in lines)
    assert of(ctx)["walk_cool"] == ctx.step + hw.COOLDOWN


def test_heal_walk_survives_a_battle_and_battle_steps_do_not_count(tmp_path, monkeypatch):
    ctx, hw = _walking_ctx(tmp_path, monkeypatch)
    ctx.view.m = 0x40
    ctx.view.x, ctx.view.y = 5, 7
    b = StatusCare()
    b.step(ctx)
    steps = of(ctx)["walk"]["steps"]
    ctx.emu.set(BATTLE, 1)
    ctx.refresh()
    for _ in range(50):                                   # a long fight: the behaviour stands down, step never runs
        assert not b.applies(ctx)
    assert of(ctx)["walk"]["steps"] == steps              # request kept, cap not consumed
    ctx.emu.set(BATTLE, 0)
    ctx.refresh()
    ctx.view.m, ctx.view.x, ctx.view.y = 0x40, 5, 7
    assert b.applies(ctx) and b.step(ctx).button == "LEFT" and of(ctx)["walk"]["steps"] == steps + 1
