"""The trainer ledger: states and sources, the walked-up-NPC match, per-run persistence,
the beaten_trainers(ctx) seam, and read-only RAM (no emu.set/write anywhere)."""
from __future__ import annotations

import json

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import trainer_ledger as T
from test_item_balls import MAP, make_ctx

# The Route 24 (map 35) rows from the directive, in ROM list order.
R24 = [{"class": "ROCKET", "party": 6, "x": 11, "y": 15, "mons": [(15, "EKANS"), (15, "ZUBAT")]},
       {"class": "JR.TRAINER(M)", "party": 2, "x": 5, "y": 20, "mons": [(14, "RATTATA"), (14, "EKANS")]},
       {"class": "JR.TRAINER(M)", "party": 3, "x": 11, "y": 19, "mons": [(18, "MANKEY")]},
       {"class": "LASS", "party": 7, "x": 10, "y": 22, "mons": [(16, "PIDGEY"), (16, "NIDORAN(F)")]},
       {"class": "YOUNGSTER", "party": 4, "x": 11, "y": 25, "mons": [(14, "RATTATA"), (14, "EKANS"), (14, "ZUBAT")]},
       {"class": "LASS", "party": 8, "x": 10, "y": 28, "mons": [(14, "PIDGEY"), (14, "NIDORAN(F)")]},
       {"class": "BUG CATCHER", "party": 9, "x": 11, "y": 31, "mons": [(14, "CATERPIE"), (14, "WEEDLE")]}]


def test_states_start_unknown_and_unknown_is_not_a_hazard():
    led = T.TrainerLedger({35: R24})
    assert [e.state for e in led.entries(35)] == ["unknown"] * 7
    assert led.beaten_tiles() == set()           # unknown is never 'beaten' - not a hazard, just untested
    led.mark_beaten(35, 6, "battle_log", 42)
    e = led.entries(35)[6]
    assert (e.state, e.source, e.step) == ("beaten", "battle_log", 42)
    assert led.beaten_tiles() == {(35, 11, 31)}
    led.mark_beaten(35, 6, "flag", 43)           # idempotent: the first mark wins
    assert led.entries(35)[6].step == 42


def test_mark_beaten_round_trips_through_run_trainers_json(tmp_path):
    led = T.TrainerLedger({35: R24}, provenance="organic")
    led.mark_beaten(35, 6, "battle_log", 42)
    led.mark_beaten(35, 3, "talk_no_battle", 50)
    f = tmp_path / "trainers.json"
    led.save(f)
    rec = json.loads(f.read_text())
    assert rec["entries"]["35:6"]["state"] == "beaten" and rec["entries"]["35:6"]["provenance"] == "organic"
    led2 = T.TrainerLedger({35: R24})
    assert led2.restore(f) == 2
    assert led2.entries(35)[6].state == "beaten" and led2.entries(35)[6].step == 42
    assert led2.entries(35)[3].source == "talk_no_battle"
    assert led2.entries(35)[0].state == "unknown"
    # a restore recorded before the map was added applies when it is added (resume order does not matter)
    led3 = T.TrainerLedger({})
    assert led3.restore(f) == 2
    led3.add_map(35, R24)
    assert led3.entries(35)[6].state == "beaten"


def test_match_picks_the_placement_a_walked_up_npc_came_from():
    led = T.TrainerLedger({35: R24})
    # the Bug Catcher sighted the player at (11,33) and walked up: its tiles are not its placement
    assert led.match(35, [(11, 31), (11, 32), (11, 33)]) == 6
    assert led.match(35, [(11, 32), (11, 33)]) == 6       # only the walked-to tiles were seen
    assert led.match(35, [(0, 0), (1, 1)]) is None        # nothing within MATCH_MAX_DIST


def test_match_ties_break_toward_the_rom_party_with_the_enemy_species():
    led = T.TrainerLedger({35: R24})
    # (11,27) is Manhattan 2 from both YOUNGSTER p4 (11,25) and LASS p8 (10,28)
    assert led.match(35, [(11, 27)]) == 4                  # no species: ROM order wins
    assert led.match(35, [(11, 27)], ["PIDGEY"]) == 5      # the lass's party holds PIDGEY
    assert led.match(35, [(11, 27)], ["ZUBAT"]) == 4


def test_sync_flags_reads_the_event_block_without_writing():
    led = T.TrainerLedger({35: R24}, flag_bits={"35:0": (T.FLAG_LO + 2, 3), "35:1": (T.FLAG_LO + 2, 4)})
    block = bytearray(T.FLAG_LEN)
    led.sync_flags(bytes(block))                            # nothing set: unknown -> unbeaten
    assert led.entries(35)[0].state == "unbeaten" and led.entries(35)[6].state == "unknown"
    block[2] = 0b1000                                        # 35:0's bit flips on
    led.sync_flags(bytes(block))
    assert led.entries(35)[0].state == "beaten" and led.entries(35)[0].source == "flag"
    led.mark_beaten(35, 4, "battle_log", 7)
    block[2] = 0                                             # a clear bit never erases a recorded win
    led.sync_flags(bytes(block))
    assert led.entries(35)[4].state == "beaten" and led.entries(35)[0].state == "beaten"


def test_talk_no_battle_marks_beaten_only_after_talk_wait_steps():
    led = T.TrainerLedger({35: R24})
    led.note_talk(35, 6, 100)
    led.note_talk(35, 6, 104)                                # advancing the dialog does not re-arm
    assert not led.tick(100 + T.TALK_WAIT_STEPS - 1)
    assert led.entries(35)[6].state == "unknown"
    assert led.tick(100 + T.TALK_WAIT_STEPS)
    e = led.entries(35)[6]
    assert e.state == "beaten" and e.source == "talk_no_battle"


def test_a_starting_battle_cancels_the_talk_probe():
    led = T.TrainerLedger({35: R24})
    led.note_talk(35, 6, 100)
    led.tick(105, battling=True)                             # the battle started: the probe is gone
    assert not led.tick(100 + T.TALK_WAIT_STEPS)
    assert led.entries(35)[6].state == "unknown"


def test_beaten_trainers_seam_returns_the_beaten_rom_tiles(tmp_path):
    ctx = make_ctx(tmp_path, memory={MAP: 35})
    led = T.TrainerLedger({35: R24})
    led.mark_beaten(35, 6, "battle_log", 42)
    ctx.trainer_ledger = led
    assert T.beaten_trainers(ctx) == {(35, 11, 31)}
    # no ROM data (fresh ctx, no kb): an empty set, and it never raises on a bare object
    assert T.beaten_trainers(make_ctx(tmp_path / "b")) == set()

    class Bare:
        pass
    assert T.beaten_trainers(Bare()) == set()


def test_the_ledger_never_writes_to_the_emulator(tmp_path):
    class RecEmu(FakeEmulator):
        def __init__(self, memory=None):
            super().__init__(memory)
            self.writes = []

        def set(self, addr, value):
            self.writes.append(("set", addr)); super().set(addr, value)

        def write(self, addr, value):
            self.writes.append(("write", addr)); super().write(addr, value)

    emu = RecEmu({MAP: 35, T.FLAG_LO + 2: 0b1000})
    ctx = make_ctx(tmp_path, memory=None)
    ctx.emu = emu
    led = T.TrainerLedger({35: R24}, flag_bits={"35:0": (T.FLAG_LO + 2, 3)})
    ctx.trainer_ledger = led
    ctx.view.m = 35
    ctx.step = T.LEDGER_SYNC_EVERY
    T.tick(ctx)                                               # reads wEventFlags, saves trainers.json
    assert led.entries(35)[0].state == "beaten"
    npc = {"pic": 4, "positions": {"11,32": 1, "11,31": 1}, "last": [11, 32]}
    T.note_battle_won(ctx, npc, 35)
    T.note_talk(ctx, (35, 11, 32), npc, True)
    T.save_run(ctx)
    assert led.entries(35)[6].state == "beaten"
    assert emu.writes == [] and (tmp_path / "trainers.json").exists()
