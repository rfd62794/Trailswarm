"""after_victory: the push/potion/heal/continue decision on fixture battles, and the one-per-win gate."""
from __future__ import annotations

from dataclasses import replace

import pytest

from pokeagent.explorer.procedures.state import of
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.behaviours.after_victory import AfterVictory
from pokeagent.knowledge.party import trainer_mon
from pokeagent.procedures import after_victory_rules as av

MAP, PX, PY = 0xD35E, 0xD362, 0xD361

# A minimal synthetic cartridge (same shape as test_team_readiness.py's SYN): two types, a one-way chart
# (AQUA crushes PEBBLE), two species rows with real stat maths, one move each.
SYN = {
    "types": ["AQUA", "PEBBLE"],
    "type_chart": [["AQUA", "PEBBLE", 2.0], ["PEBBLE", "AQUA", 0.5], ["AQUA", "AQUA", 0.5], ["PEBBLE", "PEBBLE", 1.0]],
    "moves": {"1": {"name": "SPLASH", "power": 40, "type": "AQUA", "effect": 0, "accuracy": 100},
              "2": {"name": "SLAM", "power": 40, "type": "PEBBLE", "effect": 0, "accuracy": 100}},
    "species_by_dex": {
        "1": {"name": "AQUAMON", "type1": "AQUA", "type2": "AQUA", "hp": 60, "atk": 60, "def": 60, "spd": 60,
              "spc": 60, "moves1": ["SPLASH"], "growth": "med_fast"},
        "2": {"name": "PEBBLEMON", "type1": "PEBBLE", "type2": "PEBBLE", "hp": 50, "atk": 30, "def": 30,
              "spd": 30, "spc": 30, "moves1": ["SLAM"], "growth": "med_fast"}},
    "learnsets": {},
    "name_of_internal": {},
}


def _mon(name, level, frac=1.0):
    c = trainer_mon(name, level, SYN)
    return replace(c, hp=max(0, int(c.hp * frac))) if frac < 1 else c


STRONG = [_mon("AQUAMON", 30), _mon("AQUAMON", 28)]
BOSS = [[(12, "PEBBLEMON"), (14, "PEBBLEMON")]]


def test_healthy_party_that_clears_the_margin_pushes():
    d = av.decide(STRONG, BOSS, {}, None, SYN)
    assert d.action == "push" and d.margin is not None and d.margin >= av.PUSH_MARGIN
    assert d.alive == 2 and d.next_trainer.startswith("12 PEBBLEMON")


def test_hurt_lead_with_a_potion_and_a_far_center_drinks_the_potion():
    party = [_mon("AQUAMON", 30, 0.2), STRONG[1]]
    walk = (10_000, 0, 58)  # a Pokecenter round trip far beyond HEAL_WALK_MAX_FRAMES
    d = av.decide(party, BOSS, {0x14: 2}, walk, SYN)
    assert d.action == "potion"


def test_hurt_lead_with_no_potion_and_a_near_center_walks_to_heal():
    party = [_mon("AQUAMON", 30, 0.2), STRONG[1]]
    d = av.decide(party, BOSS, {}, (100, 0, 58), SYN)
    assert d.action == "heal"


def test_a_lost_fight_with_nowhere_to_heal_continues():
    weak = [_mon("AQUAMON", 3), _mon("AQUAMON", 2)]
    d = av.decide(weak, [[(20, "PEBBLEMON"), (20, "PEBBLEMON"), (20, "PEBBLEMON")]], {}, None, SYN)
    assert d.action == "continue" and "cannot win" in d.why


def test_thin_win_without_a_cheaper_heal_still_pushes():
    # the lead at 10% fails PUSH_MIN_LEAD_HP; no potion and the walk is too far: thin-margin push
    party = [_mon("AQUAMON", 30, 0.1), STRONG[1]]
    d = av.decide(party, [[(6, "PEBBLEMON")]], {}, (9_000, 0, 58), SYN)
    assert d.action == "push" and "thin margin" in d.why


def test_no_remaining_trainers_continues_without_simulating():
    d = av.decide(STRONG, [], {}, None, SYN)
    assert d.action == "continue" and d.margin is None and "path clear" in d.why


def test_missing_data_continues():
    assert av.decide([], BOSS, {}, None, SYN).action == "continue"
    assert av.decide(STRONG, [[(9, "NOSUCHMON")]], {}, None, SYN).action == "continue"


def test_the_reason_names_the_margin():
    d = av.decide(STRONG, BOSS, {}, None, SYN)
    assert f"{d.margin:+.2f}" in d.why


def make_ctx(tmp_path, **fields):
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=tmp_path, stable_frames=10, **fields)
    ctx.refresh()
    return ctx


def test_applies_once_per_trainer_win_and_never_while_battling_or_boxed(tmp_path):
    b = AfterVictory()
    ctx = make_ctx(tmp_path, battles_won=1)
    of(ctx)["twins"] = 1
    assert b.applies(ctx)
    ctx = make_ctx(tmp_path, battles_won=1)
    of(ctx)["twins"] = 1
    ctx.view = replace(ctx.view, battling=True)
    assert not b.applies(ctx)


def test_a_wild_win_never_decides(tmp_path, monkeypatch):
    """battles_won counts wild wins too: with no trainer win recorded (twins == 0) the behaviour does not
    apply, so no decision, no walk_to_center search, no log line, no after_victory.jsonl row."""
    import pokeagent.explorer.behaviours.after_victory as mod
    ctx = make_ctx(tmp_path, battles_won=5)
    calls = []
    monkeypatch.setattr(mod.outside_use, "walk_to_center", lambda c: calls.append(1))
    ctx.log = lambda t, tag=None: calls.append(t)
    assert not AfterVictory().applies(ctx)
    assert calls == [] and not (ctx.run_dir / mod.LOG_NAME).exists()


def test_a_trainer_win_is_recorded_and_written_to_the_run_dir(tmp_path, monkeypatch):
    """battle bookkeeping bumps of(ctx)['twins'] on a won trainer fight (kind == 2 / beaten trainer_npc);
    AfterVictory decides once and writes the row under the run dir."""
    import pokeagent.explorer.behaviours.after_victory as mod
    from pokeagent.explorer.behaviours.battle import Battle
    ctx = make_ctx(tmp_path, battles=1, battles_won=0)
    (tmp_path / "runs").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path)  # battle bookkeeping appends to runs/battles.jsonl relative to the run cwd
    ctx.battle_pos, ctx.in_battle = (0x28, 5, 6), True
    ctx.battle_log = {"start": 0, "kind": 2, "turns": []}
    ctx.emu.set(0xD163, 1)  # one mon standing: a won trainer battle on the same map
    monkeypatch.setattr(mod, "beaten_trainers", lambda c: set())
    monkeypatch.setattr(mod.trainers, "trainers_on", lambda m, kb=None: [])
    monkeypatch.setattr(mod.outside_use, "walk_to_center", lambda c: None)
    monkeypatch.setattr(mod, "bag_contents", lambda emu: {})
    monkeypatch.setattr(mod, "_party_now", lambda emu: STRONG)
    Battle().step(ctx)                      # end-of-battle bookkeeping: trainer win recorded
    assert of(ctx)["twins"] == 1 and ctx.battles_won == 1
    assert AfterVictory().applies(ctx)
    d = AfterVictory().step(ctx)
    assert d is not None and of(ctx)["twins"] == 0
    rows = (ctx.run_dir / mod.LOG_NAME).read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1


def test_the_walk_failure_is_logged_once_per_distinct_message(tmp_path, monkeypatch, caplog):
    import pokeagent.explorer.behaviours.after_victory as mod
    ctx = make_ctx(tmp_path, battles_won=1)
    of(ctx)["twins"] = 1
    monkeypatch.setattr(mod, "_party_now", lambda emu: STRONG)
    monkeypatch.setattr(mod, "beaten_trainers", lambda c: set())
    monkeypatch.setattr(mod.trainers, "trainers_on", lambda m, kb=None: [])
    monkeypatch.setattr(mod, "bag_contents", lambda emu: {})
    mod._walk_warned.clear()
    def boom(c):
        raise RuntimeError("no graph")
    monkeypatch.setattr(mod.outside_use, "walk_to_center", boom)
    with caplog.at_level("WARNING"):
        AfterVictory().step(ctx)
        of(ctx)["twins"] = 1
        AfterVictory().step(ctx)
    hits = [r for r in caplog.records if "walk_to_center failed" in r.message]
    assert len(hits) == 1 and "no graph" in hits[0].message


def test_step_requests_a_heal_walk_and_stores_the_decision(tmp_path, monkeypatch):
    import pokeagent.explorer.behaviours.after_victory as mod
    from pokeagent.explorer.status_care import of as care_of
    ctx = make_ctx(tmp_path, battles_won=1)
    of(ctx)["twins"] = 1
    monkeypatch.setattr(mod, "_party_now", lambda emu: [_mon("AQUAMON", 30, 0.2), STRONG[1]])
    monkeypatch.setattr(mod, "beaten_trainers", lambda c: set())
    row = {"class": "LASS", "party": 1, "x": 3, "y": 3, "mons": [(12, "PEBBLEMON")]}
    monkeypatch.setattr(mod.trainers, "trainers_on", lambda m, kb=None: [row])
    monkeypatch.setattr(mod.outside_use, "walk_to_center", lambda c: (100, 0, 58))
    monkeypatch.setattr(mod, "bag_contents", lambda emu: {})
    monkeypatch.setattr(mod, "decide", lambda party, rem, bag, walk, kb=None:
                        av.decide(party, rem, bag, walk, SYN))
    d = AfterVictory().step(ctx)
    assert of(ctx)["seen"] == 1 and ctx.center_intent is None
    assert care_of(ctx)["walk"] is not None and care_of(ctx)["walk"]["why"] == "after_victory"
    assert of(ctx)["victory"] is not None and d is not None


def test_step_primes_the_field_potion_cache(tmp_path, monkeypatch):
    import pokeagent.explorer.behaviours.after_victory as mod
    ctx = make_ctx(tmp_path, battles_won=1)
    of(ctx)["twins"] = 1
    monkeypatch.setattr(mod, "_party_now", lambda emu: [_mon("AQUAMON", 30, 0.2), STRONG[1]])
    monkeypatch.setattr(mod, "beaten_trainers", lambda c: set())
    row = {"class": "LASS", "party": 1, "x": 3, "y": 3, "mons": [(12, "PEBBLEMON")]}
    monkeypatch.setattr(mod.trainers, "trainers_on", lambda m, kb=None: [row])
    monkeypatch.setattr(mod.outside_use, "walk_to_center", lambda c: (10_000, 0, 58))
    monkeypatch.setattr(mod, "bag_contents", lambda emu: {0x14: 2})
    monkeypatch.setattr(mod, "decide", lambda party, rem, bag, walk, kb=None:
                        av.decide(party, rem, bag, walk, SYN))
    AfterVictory().step(ctx)
    from pokeagent.explorer.economy import ledger
    led = ledger.of(ctx)
    assert led.field_decision is True and led.field_check_at > ctx.step
    assert ctx.center_intent is None


def test_a_weak_lowest_first_lead_does_not_block_the_push():
    """Review of #222: the party stands lowest-first, so slot 0 is the weakest; the fighter's HP decides, not slot 0's."""
    party = [_mon("AQUAMON", 5, 0.2), STRONG[0]]  # weak lead at 20% (< PUSH_MIN_LEAD_HP), healthy fighter behind
    d = av.decide(party, BOSS, {0x14: 2}, (100, 0, 58), SYN)
    assert d.action == "push" and d.lead_hp_frac >= av.PUSH_MIN_LEAD_HP
