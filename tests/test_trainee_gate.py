"""trainee_gate: never train with a fainted trainee - heal first; the faint is logged and accounted."""
from __future__ import annotations

import json

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.grind_drill import GrindDrill
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.economy import outside_use
from pokeagent.explorer.economy.prices import REVIVE
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.status_care import trainee_eligible as elig
from pokeagent.explorer.status_care import MonStatus, of
from pokeagent.explorer.trainee_gate import trainee_check, trainee_ok


def M(slot, hp, mx=40, kinds=frozenset()):
    return MonStatus(slot, hp, mx, frozenset(kinds))
from pokeagent.training_progress import training_progress

MAP, PX, PY = 0xD35E, 0xD362, 0xD361
COUNT, MON1, SIZE, MAGIKARP = 0xD163, 0xD16B, 44, 133


def put_mon(mem: dict, slot: int, species: int, level: int, hp: int, max_hp: int, status: int = 0) -> None:
    base = MON1 + SIZE * slot
    for a, v in {base: species, base + 1: hp >> 8, base + 2: hp & 255, base + 4: status,
                 base + 33: level, base + 34: max_hp >> 8, base + 35: max_hp & 255}.items():
        mem[a] = v
    mem[0xD164 + slot] = species
    mem[COUNT] = max(mem.get(COUNT, 0), slot + 1)


def make_ctx(tmp_path, mem=None, **fields) -> ExplorerContext:
    emu = FakeEmulator({MAP: 0x0E, PX: 5, PY: 6, **(mem or {})})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path,
                          stable_frames=10, **fields)
    ctx.refresh()
    return ctx


def karp_ctx(tmp_path, hp=0, status=0, **kw):
    mem = {}
    put_mon(mem, 0, 153, 14, 30, 40)                    # the fighter, healthy
    put_mon(mem, 1, MAGIKARP, 5, hp, 17, status=status)  # the trainee
    return make_ctx(tmp_path, mem, **kw)


def test_trainee_eligible_rows():
    party = [M(0, 30, 40), M(1, 12, 17)]
    assert elig(party, 1, False, 80).ok                                   # alive and unpoisoned
    assert elig(party, 1, False, 80).fix == ""
    assert elig(party, None, False, 80).ok                                # no trainee: nothing to gate
    dead = [M(0, 30, 40), M(1, 0, 17)]
    assert elig(dead, 1, True, None).fix == "revive"                      # Revive beats an unknown walk
    assert elig(dead, 1, True, 200).fix == "revive"                       # ... and a far one (200 > 150)
    assert elig(dead, 1, True, 80).fix == "center"                        # a close center beats the Revive
    assert elig(dead, 1, False, None).fix == "center"                     # no Revive: the nurse
    sick = [M(0, 30, 40), M(1, 5, 17, {"poison"})]                        # faint in 17 <= 30 safe steps
    assert elig(sick, 1, False, 80, antidote_carried=True).fix == "antidote"
    assert elig(sick, 1, False, 80).fix == "center"
    fine = [M(0, 30, 40), M(1, 10, 17, {"poison"})]                       # 37 > 30: survives the grass walk
    assert elig(fine, 1, False, 80).ok


def test_fainted_trainee_sets_heal_intent_logs_and_accounts(tmp_path, monkeypatch):
    ctx = karp_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 10, 0, 0x40))
    lines = []
    ctx.log = lambda t, tag=None: lines.append(t)
    e = trainee_ok(ctx)
    assert not e.ok and e.fix == "center" and of(ctx)["walk"] is not None      # a heal-walk request, not center_intent
    assert of(ctx)["fainted_steps"] == 1
    assert any("trainee fainted: no exp" in l and "slot 1" in l for l in lines)  # no ROM tables: species logs as 0x85
    rows = [json.loads(l) for l in (tmp_path / "status_care.jsonl").read_text().splitlines()]
    row = next(r for r in rows if r["event"] == "trainee_fainted")
    assert row["event"] == "trainee_fainted" and row["slot"] == 1 and row["provenance"] == "unknown"
    ctx.step += 1                                                        # same faint, next step: counted, not re-logged
    trainee_ok(ctx)
    assert of(ctx)["fainted_steps"] == 2 and len([l for l in lines if "trainee fainted" in l]) == 1


def test_fainted_trainee_far_from_a_center_requests_the_revive(tmp_path, monkeypatch):
    mem = {}
    put_mon(mem, 0, 153, 14, 30, 40)
    put_mon(mem, 1, MAGIKARP, 5, 0, 17)
    mem[0xD31D], mem[0xD31E], mem[0xD31F] = 1, REVIVE, 1
    ctx = make_ctx(tmp_path, mem)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: None)
    e = trainee_ok(ctx)
    assert not e.ok and e.fix == "revive" and ctx.center_intent is None
    assert of(ctx)["request"] == (REVIVE, 1)                     # StatusCare uses it on that slot


def test_grind_drill_never_starts_with_a_fainted_trainee(tmp_path, monkeypatch):
    ctx = karp_ctx(tmp_path, hp=0)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 10, 0, 0x40))
    ctx.opts.drill_grind = 0x0E
    ctx.view.m = 0x0E
    assert not GrindDrill().applies(ctx)
    ctx2 = karp_ctx(tmp_path, hp=10)
    ctx2.opts.drill_grind = 0x0E
    ctx2.view.m = 0x0E
    assert GrindDrill().applies(ctx2)


def test_fainted_trainee_produces_no_training_progress():
    flat = [{"step": 1, "party": [[153, 14, 500, 30, 40], [133, 5, 100, 0, 17]]},
            {"step": 2, "party": [[153, 14, 500, 30, 40], [133, 5, 100, 0, 17]]}]
    assert training_progress(flat) is False                              # nothing gained while the trainee is down
    gained = [{"step": 1, "party": [[153, 14, 500, 30, 40], [133, 5, 100, 0, 17]]},
              {"step": 2, "party": [[153, 14, 500, 30, 40], [133, 6, 160, 10, 19]]}]
    assert training_progress(gained) is True


def test_trainee_check_is_pure_and_skips_the_path_search_for_a_healthy_trainee(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: calls.append(1) or (160, 0, 0x40))
    ok = karp_ctx(tmp_path, hp=10)
    assert trainee_check(ok).ok and calls == []                          # alive + unpoisoned: no walk computed
    sick = karp_ctx(tmp_path, hp=0)
    before = dict(of(sick))
    assert not trainee_check(sick).ok and not trainee_check(sick).ok
    assert of(sick) == before and sick.center_intent is None and not (tmp_path / "status_care.jsonl").exists()


def test_plan_goal_stands_down_for_a_fainted_trainee_with_a_heal_walk(tmp_path, monkeypatch):
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    ctx = karp_ctx(tmp_path, hp=0)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (16 * 10, 0, 0x40))
    ctx.mem.data["maps"] = {"14": {"visited": {"5,6": 1, "5,7": 1}, "blocked": [], "warps": {"5,7,DOWN": [0x40, 3, 7]}}}
    assert PlanGoal().step(ctx) is None                                  # no training decision for a fainted trainee
    assert of(ctx)["walk"] is not None                                   # and the heal walk is what is pending
    ctx2 = karp_ctx(tmp_path / "b", hp=10)                               # a healthy trainee: no walk requested
    PlanGoal().step(ctx2)
    assert of(ctx2).get("walk") is None


def test_no_path_search_while_a_heal_walk_cools_down_or_runs(tmp_path, monkeypatch):
    from pokeagent.explorer.behaviours.status_care import StatusCare
    calls = []
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: calls.append(1) or None)
    ctx = karp_ctx(tmp_path, hp=0)
    of(ctx)["walk_cool"] = ctx.step + 300                                  # an abandoned walk is cooling down
    b = StatusCare()
    for _ in range(5):
        assert b.applies(ctx)                                              # still ineligible, still cheap
        assert b.step(ctx) is None
        assert not trainee_check(ctx).ok and not trainee_ok(ctx).ok
    assert calls == []                                                     # no BFS at all during the cooldown
    of(ctx)["walk_cool"] = 0
    trainee_check(ctx)
    assert calls == [1]                                                    # once the cooldown is over it searches again
