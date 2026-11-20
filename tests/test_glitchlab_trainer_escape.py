"""The trainer-escape recipe, probe and verdict: hand-built trace rows for the four outcome
shapes (stuck + matching instant encounter, clean escape, stuck without encounter, mismatched
species), read_probe over the verified addresses, and the placeholder guard. Synthetic only."""
from __future__ import annotations

import pytest

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.glitchlab import trainer_escape as te
from pokeagent.glitchlab.script import load_script

SPECIAL = 0x0050   # a Special stat whose low byte is a species index (plain test data)


def row(rid, **ram):
    return {"id": rid, "ram": ram}


def stuck_rows(**over):
    """The full H1+H2 timeline: spotted, Start opened, Teleport away to another map leaving
    bits set, a wild fight leaving Special 0x0050, and an instant battle on return."""
    rows = [
        row("before_spot", map=24, in_battle=False),
        row("walk_to_sight", map=24),
        row("at_exclaim", map=24, engaged_class=0),
        row("start_menu", map=24, start_menu_open=True),
        row("escape", map=24),
        row("after_escape", map=10, in_battle=False, misc_flags=1, status5=0),
        row("special_fight", map=10, special_u16=SPECIAL, special_lo=0x50),
        row("return_walk", map=24, in_battle=False),
        row("on_return", map=24, in_battle=True, enemy_species=0x50, enemy_level=7,
            cur_enemy_level=7, unmod_level=7, unmod_special=0x50),
    ]
    for r in rows:
        r["ram"].update(over.get(r["id"], {}))
    return rows


def test_verdict_stuck_then_instant_encounter_matching_the_stale_special():
    v = te.verdict(stuck_rows())
    assert v["start_opened_before_engagement"] is True
    assert v["trainer_state_stuck"] is True
    assert v["enemy_special"] == {"special_u16": SPECIAL, "special_lo": 0x50}
    assert v["instant_encounter"] == {"species": 0x50, "level": 7, "map": 24}
    assert v["species_matches_special"] is True
    assert "bit meanings UNVERIFIED" in v["notes"]


def test_verdict_escape_without_stuck_bits_is_not_stuck():
    v = te.verdict(stuck_rows(after_escape={"misc_flags": 0, "status5": 0}))
    assert v["trainer_state_stuck"] is False
    assert v["instant_encounter"]["species"] == 0x50   # the rest of the timeline still reads


def test_verdict_stuck_but_no_encounter_on_return():
    v = te.verdict(stuck_rows(on_return={"in_battle": False}))
    assert v["trainer_state_stuck"] is True
    assert v["instant_encounter"] is None and v["species_matches_special"] is None
    assert v["enemy_special"] == {"special_u16": SPECIAL, "special_lo": 0x50}


def test_verdict_encounter_species_differing_from_special_lo_does_not_match():
    v = te.verdict(stuck_rows(on_return={"enemy_species": 0x99}))
    assert v["instant_encounter"]["species"] == 0x99
    assert v["species_matches_special"] is False


def test_verdict_unknown_menu_read_and_same_map_escape():
    v = te.verdict(stuck_rows(start_menu={"start_menu_open": None},
                              after_escape={"map": 24}))   # escaped but never left the map
    assert v["start_opened_before_engagement"] is None
    assert v["trainer_state_stuck"] is False


def test_read_probe_reads_the_verified_addresses_and_signal_bytes():
    emu = FakeEmulator({
        0xD057: 0,                    # not in battle
        0xCD60: 0b1, 0xD730: 0, 0xCD2D: 0, 0xCD2E: 0,
        0xD35E: 24, 0xD361: 7, 0xD362: 11,
        0xCFE5: 0x50, 0xCFF3: 12, 0xCFFC: 0x00, 0xCFFD: 0x50,
        0xD059: 0x50, 0xD031: 9,
        0xD127: 12, 0xCD2C: 0x50, 0xCD23: 12,
    })
    p = te.read_probe(emu, menu_probe=lambda e: True)
    assert (p["misc_flags"], p["status5"], p["engaged_class"], p["engaged_set"]) == (1, 0, 0, 0)
    assert p["in_battle"] is False and p["reasons"] == ["trainer_flags_stuck"]
    assert (p["map"], p["y"], p["x"]) == (24, 7, 11)
    assert p["enemy_species"] == 0x50 and p["enemy_level"] == 12
    assert p["special_u16"] == SPECIAL and p["special_lo"] == 0x50
    assert p["cur_opponent"] == 0x50 and p["trainer_class"] == 9
    assert (p["cur_enemy_level"], p["unmod_special"], p["unmod_level"]) == (12, 0x50, 12)
    assert p["start_menu_open"] is True


def test_read_probe_swallows_a_broken_menu_probe():
    def boom(emu):
        raise RuntimeError("no tile map")

    p = te.read_probe(FakeEmulator(), menu_probe=boom)
    assert p["start_menu_open"] is None


def test_recipe_loads_in_order_and_placeholders_block_run_recipe():
    steps = load_script(te.RECIPE)
    ids = ["before_spot", "walk_to_sight", "at_exclaim", "start_menu", "escape",
           "after_escape", "special_fight", "return_walk", "on_return"]
    assert [s.id for s in steps] == ids
    assert [s.id for s in steps if s.placeholder] == ["walk_to_sight", "escape",
                                                      "special_fight", "return_walk"]
    emu = FakeEmulator()
    with pytest.raises(ValueError):
        te.run_recipe(emu)
    rows = te.run_recipe(emu, allow_placeholder=True, probes=lambda e: {"ok": 1})
    assert [r["id"] for r in rows] == ids
    assert emu.presses == [Button.START]   # the only concrete press in the default recipe


def test_read_probe_uses_the_seen_bit_and_ignores_stale_engaged_class():
    from pokeagent.glitch_signals import ENGAGED_TRAINER_CLASS, MISC_FLAGS
    emu = FakeEmulator({ENGAGED_TRAINER_CLASS: 21})
    r = te.read_probe(emu, menu_probe=lambda e: False)
    assert (r["seen_by_trainer"], r["engaged"], r["engaged_class"]) == (False, False, 21)
    emu.set(MISC_FLAGS, 1)
    r = te.read_probe(emu, menu_probe=lambda e: False)
    assert (r["seen_by_trainer"], r["engaged"]) == (True, True)


def test_verdict_reports_seen_at_exclaim_and_marks_engaged_class_stale():
    v = te.verdict(stuck_rows(at_exclaim={"seen_by_trainer": True, "engaged_class": 21}))
    assert v["seen_at_exclaim"] is True
    assert "at_exclaim engaged_class=21 (stale byte, log only)" in v["notes"]
    assert "at_exclaim seen_by_trainer=True" in v["notes"]
    assert te.verdict([])["seen_at_exclaim"] is None
