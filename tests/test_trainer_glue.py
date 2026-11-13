"""The trainer-ledger glue (explorer.trainer_hooks): run_provenance, note_battle_won, note_talk (the
false-positive cases), tick, the planner-independent avoidance pass, the logged (never silent) failures,
memory_nav._person_tile end to end, and the atlas-row shape in the grind report. Headless."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from pokeagent.explorer import trainer_hooks as H
from pokeagent.explorer import trainer_ledger as T
from pokeagent.explorer import trainer_route as R
from pokeagent.explorer.behaviours.trainer_hunt import TrainerHunt
from pokeagent.grind.atlas import STEPS_PER_MIN, Spot
from pokeagent.grind.trainer_spots import spot_travel_steps, spot_xp_per_step
from test_item_balls import MAP, PX, PY, make_ctx
from test_trainer_route import M, ROWS, WEAK, _mem

TRAINER = {"positions": {"11,21": 1}, "last": [11, 21]}                     # at/next to ROWS[0] (11,20)
BYSTANDER = {"positions": {"14,20": 3}, "last": [14, 20], "moves": False}   # 3 tiles away, within MATCH_MAX_DIST


def _ctx(tmp_path, rows=ROWS):
    ctx = make_ctx(tmp_path, memory={MAP: M, PX: 11, PY: 14})
    ctx.trainer_ledger = T.TrainerLedger({M: rows})
    ctx.refresh()
    return ctx


# --- run_provenance ---
def test_run_provenance_reads_the_state_fingerprint(tmp_path):
    state = tmp_path / "start.state"
    ctx = SimpleNamespace(opts=SimpleNamespace(state_path=str(state)))
    assert H.run_provenance(ctx) == "unknown"                               # no .fp.json
    fp = tmp_path / "start.state.fp.json"
    for rec, want in (({"lineage": "organic"}, "organic"), ({"lineage": "promoted"}, "organic"),
                      ({"lineage": "synthetic"}, "synthetic"), ({"synthetic": True}, "synthetic"),
                      ({"lineage": "mystery"}, "unknown")):
        fp.write_text(json.dumps(rec))
        assert H.run_provenance(ctx) == want
    fp.write_text("{not json")
    assert H.run_provenance(ctx) == "unknown"
    assert H.run_provenance(SimpleNamespace(opts=SimpleNamespace(state_path=""))) == "unknown"


# --- note_battle_won ---
def test_note_battle_won_pins_the_win_and_persists(tmp_path):
    ctx = _ctx(tmp_path)
    H.note_battle_won(ctx, TRAINER, M)
    e = ctx.trainer_ledger.entries(M)[0]
    assert (e.state, e.source) == ("beaten", "battle_log")
    assert json.loads((tmp_path / "trainers.json").read_text())["entries"][f"{M}:0"]["state"] == "beaten"
    logs = []
    ctx.log = lambda text, tag=None: logs.append(text)
    H.note_battle_won(ctx, {"positions": {"1,1": 1}}, M)                    # nothing within range: logged, not marked
    assert any("no ROM placement" in t for t in logs)


# --- note_talk: the false positives ---
def test_a_bystander_near_an_unbeaten_trainer_is_never_marked_beaten(tmp_path):
    ctx = _ctx(tmp_path)
    H.note_talk(ctx, (M, 11, 14), BYSTANDER, True)
    assert ctx.trainer_ledger._talk == {}                                   # no probe armed at all
    for step in range(1, 40):
        ctx.trainer_ledger.tick(step)
    assert ctx.trainer_ledger.entries(M)[0].state == "unknown"


def test_a_long_pre_battle_speech_is_not_talk_no_battle(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.step = 10
    H.note_talk(ctx, (M, 11, 14), TRAINER, True)
    led = ctx.trainer_ledger
    assert (M, 0) in led._talk
    for step in range(11, 60):                                              # 49 steps of text still scrolling
        led.tick(step, text_open=True)
    assert led.entries(M)[0].state == "unknown"
    led.tick(60, battling=True)                                             # the battle finally starts: probe cancelled
    assert led._talk == {}
    # a beaten trainer: the text ends, then TALK_WAIT_STEPS quiet steps with no battle
    H.note_talk(ctx, (M, 11, 14), TRAINER, True)
    led._talk[(M, 0)] = 100
    for step in range(101, 101 + T.TALK_WAIT_STEPS - 1):
        assert not led.tick(step)
    assert led.tick(100 + T.TALK_WAIT_STEPS) and led.entries(M)[0].source == "talk_no_battle"


# --- tick ---
def test_tick_adds_maps_marks_talk_and_persists(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.step = 5
    H.note_talk(ctx, (M, 11, 14), TRAINER, True)
    ctx.step = 5 + T.TALK_WAIT_STEPS
    H.tick(ctx)
    assert ctx.trainer_ledger.entries(M)[0].state == "beaten"
    assert (tmp_path / "trainers.json").exists()


# --- failures are logged, never silent ---
def test_swallowed_failures_are_logged(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    logs = []
    ctx.log = lambda text, tag=None: logs.append(text)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(T.TrainerLedger, "save", boom)
    H.save_run(ctx)
    assert any("save_run failed" in t and "disk full" in t for t in logs)
    monkeypatch.setattr(T.TrainerLedger, "match", boom)
    H.note_talk(ctx, (M, 11, 14), TRAINER, True)
    assert sum("trainer_ledger skipped" in t for t in logs) == 2           # save_run's line + note_talk's
    monkeypatch.setattr(H, "ledger_for", boom)
    assert H.beaten_trainers(ctx) == set()
    assert sum("trainer_ledger skipped" in t for t in logs) == 3


def test_current_party_logs_once_per_battle_when_it_cannot_read(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    logs = []
    ctx.log = lambda text, tag=None: logs.append(text)
    for _ in range(3):
        assert H.current_party(ctx) == []                                   # no ROM tables here: nothing to read
    assert sum("cannot read the party" in t for t in logs) == 1
    ctx.battles += 1                                                        # a new battle may warn again
    H.current_party(ctx)
    assert sum("cannot read the party" in t for t in logs) == 2


# --- avoidance runs with a goto active, and logs once ---
def test_avoidance_blocks_the_sight_line_with_a_goto_and_logs_once(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, rows=ROWS[:1])
    ctx.mem = _mem(tmp_path, bypass=True)
    ctx.trainer_ledger = T.TrainerLedger({M: ROWS[:1]})
    ctx.refresh()
    ctx.goto = [M, 11, 33]
    monkeypatch.setattr(H, "current_party", lambda c: WEAK)
    monkeypatch.setattr(R, "fight_margin", lambda *a: 0.0)                  # thin: the plan is "avoid"
    logs = []
    ctx.log = lambda text, tag=None: logs.append(text)
    assert not TrainerHunt().applies(ctx)                                   # the hunt itself stands down for a goto
    for _ in range(30):
        ctx.frame += 5
        H.tick(ctx)
    sight = {(M, x, y) for x, y in R.sight_tiles(ctx.trainer_ledger.entries(M)[0])}
    assert sight & set(ctx.mem.temp_blocked)                                # blocked although goto is set
    assert sum("avoiding" in t for t in logs) == 1                          # once, not per step
    ctx.frame += R.AVOID_BLOCK_FRAMES + 1                                   # the block expires and is re-made quietly
    H.tick(ctx)
    assert sum("avoiding" in t for t in logs) == 1
    ctx.goto = [M, 11, 30]                                                  # a new destination is a new decision
    H.tick(ctx)
    assert sum("avoiding" in t for t in logs) == 2


def test_idle_hunt_steps_do_not_consume_the_cap(tmp_path):
    ctx = _ctx(tmp_path)                                                    # no party data -> every trainer is ignore
    hunt = TrainerHunt()
    assert hunt.step(ctx) is None
    assert ctx.trainer_hunt_steps == 0


# --- memory_nav._person_tile with a real NPC entry (recorded from the sprite table) ---
def test_person_tile_end_to_end_with_a_recorded_npc(tmp_path, monkeypatch):
    monkeypatch.setattr(H.trainers, "trainers_on", lambda mid, kb=None: ROWS if mid == M else [])
    ctx = make_ctx(tmp_path, memory={MAP: M, PX: 11, PY: 14,
                                     0xC100 + 16: 4, 0xC204 + 16: 21 + 4, 0xC205 + 16: 11 + 4})   # slot 1, pic 4 at (11,21)
    ctx.refresh()
    ctx.mem.observe_npcs(M, ctx.emu, 1)
    assert ctx.mem.npc_at(M, 11, 21) is not None
    led = H.ledger_for(ctx)                                                 # wires mem.beaten_tiles
    assert not ctx.mem._person_tile(M, 11, 20)                              # unbeaten: just a tile
    H.note_battle_won(ctx, ctx.mem.npc_at(M, 11, 21), M)
    assert led.entries(M)[0].state == "beaten"
    assert ctx.mem._person_tile(M, 11, 20)                                  # the beaten placement now counts as a person
    assert not ctx.mem._person_tile(M, 11, 25)


# --- the grind report on the REAL atlas-row shape (grind.atlas.Spot.to_dict) ---
def _spot(**kw):
    base = dict(map_id=35, name="Route 24", xp_per_battle=30.0, encounter_p=0.1, n_obs=5, win=0.9, blackout=0.02,
                hp_lost=0.2, battle_steps=40.0, travel_steps=12.0, xp_per_step=0.5, xp_per_min=0.5 * STEPS_PER_MIN)
    base.update(kw)
    return Spot(**base)


def test_spot_adapters_accept_atlas_dict_rows_and_objects():
    row = _spot().to_dict()
    assert spot_xp_per_step(row) == pytest.approx(0.5) and spot_travel_steps(row) == pytest.approx(12.0)
    assert spot_xp_per_step(_spot()) == pytest.approx(0.5) and spot_travel_steps(_spot()) == pytest.approx(12.0)
    old = {"name": "x", "xp_per_min": 450.0}                                # xp_per_min only
    assert spot_xp_per_step(old) == pytest.approx(old["xp_per_min"] / STEPS_PER_MIN)
    assert spot_travel_steps(old) == 0.0 and STEPS_PER_MIN == 225


def test_trainer_grind_travel_uses_atlas_dict_spots():
    from pokeagent.grind import trainer_spots as TS
    assert TS._travel([_spot(travel_steps=30.0).to_dict(), _spot(travel_steps=12.0).to_dict()], 11, 20) == 12.0
    assert TS._travel([], 1, 1) == 0.0


def test_print_trainer_section_with_real_atlas_rows(capsys):
    from test_trainer_grind import BASE_EXP, ROWS as GROWS, STRONG as GSTRONG, SYN, _grind_report
    led = T.TrainerLedger({35: GROWS})
    rows = [_spot(map_id=35, xp_per_step=0.01, xp_per_min=0.01 * STEPS_PER_MIN).to_dict()]
    _grind_report().print_trainer_section(35, "Route 24", led, GSTRONG, BASE_EXP, SYN, rows, kb=SYN)
    assert "trainers worth saving or taking" in capsys.readouterr().out


def test_mark_trainer_retypes_a_mistyped_interaction_entry():
    from pokeagent.explorer.memory import MapMemory
    mem = MapMemory.__new__(MapMemory)
    mem.data = {"maps": {"65": {"npcs": {"slot1:pic29": {"pic": 29, "last": [4, 2], "talked": 1,
                                                          "results": {"type": "info", "type_votes": {"info": 1}}}}}}}
    mem.m = lambda mid: mem.data["maps"][str(mid)]
    e = mem.mark_trainer(65, 4, 3, "UP")
    assert e["trainer"] and e["results"]["type"] == "trainer"
