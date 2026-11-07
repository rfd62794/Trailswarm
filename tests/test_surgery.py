"""State surgery (pokeagent.surgery): whitelisted RAM writes, all-or-nothing validation, the synthetic stamp,
and the curriculum gate that keeps an edited state out of the segment record."""
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import seg_ingest  # noqa: E402
import seg_store as ss  # noqa: E402
import state_edit  # noqa: E402
from pokeagent import statefp, surgery  # noqa: E402
from pokeagent.emulator import FakeEmulator  # noqa: E402
from pokeagent.explorer import stats  # noqa: E402
from pokeagent.ramstructs import read_bag  # noqa: E402

LEAD = 0xD16B
SIZE = 44
BASE = {"hp": 55, "attack": 55, "defense": 50, "speed": 55, "special": 40}


def world(respawn=5):
    """Two party mons on map 0x61 (x13, y6), one potion stack, 1,234 money, two badges, respawn 5."""
    emu = FakeEmulator({0xD35E: 0x61, 0xD362: 13, 0xD361: 6, 0xD719: respawn, 0xD356: 0b11,
                        0xD347: 0x00, 0xD348: 0x12, 0xD349: 0x34, 0xD163: 2,
                        0xD164: 133, 0xD165: 179, 0xD166: 0xFF})
    for off, v in ((0, 133), (1, 0), (2, 0), (3, 12), (4, 0x08), (8, 40), (9, 150),
                   (29, 0x45), (30, 0x10), (33, 12), (34, 0), (35, 27)):       # L12, 0/27 HP, poisoned, 2 moves
        emu.memory[LEAD + off] = v
    for off, v in ((0, 179), (1, 0), (2, 6), (3, 29), (33, 29), (34, 0), (35, 79)):  # L29, 6/79 HP
        emu.memory[LEAD + SIZE + off] = v
    emu.memory.update({0xD31D: 1, 0xD31E: 0x14, 0xD31F: 2, 0xD320: 0xFF})
    return emu


def _stock(emu, items):
    """Overwrite the bag list at 0xD31D: count, (id, qty) pairs, 0xFF terminator."""
    emu.memory[0xD31D] = len(items)
    for k, (i, q) in enumerate(items):
        emu.memory[0xD31E + 2 * k], emu.memory[0xD31F + 2 * k] = i, q
    emu.memory[0xD31E + 2 * len(items)] = 0xFF


# --- 1. heal ---------------------------------------------------------------------------------------------------
def test_heal_restores_hp_status_and_pp_with_move_table():
    emu = world()
    writes = {a: (o, n) for a, o, n in surgery.apply(emu, {"heal": True}, max_pp={40: 25, 150: 20}.get)}
    assert (emu.memory[LEAD + 1], emu.memory[LEAD + 2]) == (0, 27)                  # slot 0 HP = max HP
    assert (emu.memory[LEAD + SIZE + 1], emu.memory[LEAD + SIZE + 2]) == (0, 79)    # slot 1 HP = max HP
    assert emu.memory[LEAD + 4] == 0                                              # status cleared
    assert emu.memory[LEAD + 29] == 0x5E                                          # PP 25 + 1 ups x (25//5), ups bits kept
    assert emu.memory[LEAD + 30] == 20                                            # base PP, no ups
    assert LEAD + 33 not in writes and LEAD + SIZE + 4 not in writes              # level untouched, clean status unwritten


def test_heal_without_move_table_leaves_pp_bytes():
    emu = world()
    surgery.apply(emu, {"heal": True})
    assert (emu.memory[LEAD + 29], emu.memory[LEAD + 30]) == (0x45, 0x10)
    assert emu.memory[LEAD + 2] == 27


# --- 2. set_hp -------------------------------------------------------------------------------------------------
def test_set_hp_writes_big_endian():
    emu = world()
    emu.memory[LEAD + SIZE + 34], emu.memory[LEAD + SIZE + 35] = 0x01, 0x90         # slot 1 max HP 400
    surgery.apply(emu, {"set_hp": {1: 300}})
    assert (emu.memory[LEAD + SIZE + 1], emu.memory[LEAD + SIZE + 2]) == (0x01, 0x2C)


def test_set_hp_above_max_or_bad_slot_raises_and_writes_nothing():
    emu = world()
    snap = dict(emu.memory)
    for bad in ({0: 28}, {2: 1}, {0: -1}):
        with pytest.raises(surgery.SurgeryError):
            surgery.apply(emu, {"set_hp": bad})
    assert emu.memory == snap


# --- 3. set_level ----------------------------------------------------------------------------------------------
def test_set_level_recomputes_level_hp_stats_and_exp():
    emu = world()
    surgery.apply(emu, {"set_level": {0: 20}}, base_stats=lambda s: BASE if s == 133 else None,
                  growth=lambda s: "SLOW" if s == 133 else None)
    new_max = stats.stat_value(55, 0, 0, 20, hp=True)                              # DVs and stat exp are 0 in the fixture
    assert (emu.memory[LEAD + 3], emu.memory[LEAD + 33]) == (20, 20)               # box level and level
    assert (emu.memory[LEAD + 34] << 8) | emu.memory[LEAD + 35] == new_max
    assert (emu.memory[LEAD + 1] << 8) | emu.memory[LEAD + 2] == new_max - 27      # HP rose by what max HP rose
    for i, k in enumerate(("attack", "defense", "speed", "special")):
        assert (emu.read(LEAD + 36 + 2 * i) << 8) | emu.read(LEAD + 37 + 2 * i) == stats.stat_value(BASE[k], 0, 0, 20)
    # the exp rewrite: the old level's exp on a raised level is illegal (party_exp)
    exp = 5 * 20 ** 3 // 4                                                          # SLOW L20 = 10000
    assert tuple(emu.read(LEAD + 14 + i) for i in range(3)) == (exp >> 16, exp >> 8 & 255, exp & 255)


def test_set_level_to_the_same_level_is_a_noop_on_exp():
    emu = world()
    emu.memory[LEAD + 14], emu.memory[LEAD + 15], emu.memory[LEAD + 16] = 0, 0, 50  # some earned exp at L12
    surgery.apply(emu, {"set_level": {0: 12}}, base_stats=lambda s: BASE, growth=lambda s: "SLOW")
    assert tuple(emu.read(LEAD + 14 + i) for i in range(3)) == (0, 0, 50)


def test_set_level_lowering_missing_stats_or_growth_raises():
    emu = world()
    snap = dict(emu.memory)
    with pytest.raises(surgery.SurgeryError):
        surgery.apply(emu, {"set_level": {0: 5}}, base_stats=lambda s: BASE, growth=lambda s: "SLOW")
    with pytest.raises(surgery.SurgeryError):
        surgery.apply(emu, {"set_level": {0: 20}}, base_stats=lambda s: None, growth=lambda s: "SLOW")
    with pytest.raises(surgery.SurgeryError):
        surgery.apply(emu, {"set_level": {0: 101}}, base_stats=lambda s: BASE, growth=lambda s: "SLOW")
    with pytest.raises(surgery.SurgeryError, match="growth rate"):
        surgery.apply(emu, {"set_level": {0: 20}}, base_stats=lambda s: BASE)
    assert emu.memory == snap


# --- 4/5. money, respawn ---------------------------------------------------------------------------------------
def test_money_writes_three_bcd_bytes():
    emu = world()
    surgery.apply(emu, {"money": 1_234})
    assert tuple(emu.memory[a] for a in (0xD347, 0xD348, 0xD349)) == (0x00, 0x12, 0x34)
    surgery.apply(emu, {"money": 999_999})
    assert tuple(emu.memory[a] for a in (0xD347, 0xD348, 0xD349)) == (0x99, 0x99, 0x99)


def test_money_out_of_range_raises_and_writes_nothing():
    emu = world()
    snap = dict(emu.memory)
    for bad in (1_000_000, -1):
        with pytest.raises(surgery.SurgeryError):
            surgery.apply(emu, {"money": bad})
    assert emu.memory == snap


def test_respawn_accepts_town_ids_only():
    emu = world()
    assert surgery.apply(emu, {"respawn": 5}) == []                                # already 5: no changed bytes
    assert surgery.apply(emu, {"respawn": 3}) == [(0xD719, 5, 3)]
    snap = dict(emu.memory)
    for bad in (15, 300):
        with pytest.raises(surgery.SurgeryError):
            surgery.apply(emu, {"respawn": bad})
    assert emu.memory == snap


# --- 6. bag ----------------------------------------------------------------------------------------------------
def test_give_merges_splits_and_appends_with_terminator():
    emu = world()
    _stock(emu, [(0x14, 50), (0x13, 20), (0x11, 5)])
    surgery.apply(emu, {"give": [(0x14, 80), (0x12, 5)]})
    assert read_bag(emu) == [(0x14, 99), (0x13, 20), (0x11, 5), (0x14, 31), (0x12, 5)]
    assert emu.memory[0xD31D] == 5 and emu.memory[0xD31E + 10] == 0xFF             # terminator right after the last pair


def test_give_past_capacity_raises_and_writes_nothing():
    emu = world()
    _stock(emu, [(0x10 + i, 10) for i in range(20)])                               # a full 20-slot bag
    snap = dict(emu.memory)
    with pytest.raises(surgery.SurgeryError):
        surgery.apply(emu, {"give": [(0x50, 1)]})
    assert emu.memory == snap


def test_take_removes_a_middle_slot_and_shifts_up():
    emu = world()
    _stock(emu, [(0x14, 99), (0x13, 20), (0x11, 5)])
    surgery.apply(emu, {"take": [(0x13, 20)]})
    assert read_bag(emu) == [(0x14, 99), (0x11, 5)]
    assert emu.memory[0xD31D] == 2 and emu.memory[0xD31E + 4] == 0xFF


def test_take_more_than_held_raises_and_writes_nothing():
    emu = world()
    _stock(emu, [(0x14, 99), (0x13, 20)])
    snap = dict(emu.memory)
    with pytest.raises(surgery.SurgeryError):
        surgery.apply(emu, {"take": [(0x14, 60), (0x13, 99)]})                     # second pair would fail anyway
    with pytest.raises(surgery.SurgeryError):
        surgery.apply(emu, {"take": [(0x12, 1)]})                                  # not in the bag at all
    assert emu.memory == snap


# --- 7. position -----------------------------------------------------------------------------------------------
def test_position_is_refused_by_default_and_needs_the_current_map_with_the_key():
    emu = world()
    snap = dict(emu.memory)
    # v1 position edits desync the view (0xD35F pointer not shifted): refused without the explicit key
    with pytest.raises(surgery.SurgeryError, match="unsafe in v1"):
        surgery.apply(emu, {"position": {"map": 0x61, "x": 1, "y": 2}})
    with pytest.raises(surgery.SurgeryError, match="unsafe in v1"):
        surgery.apply(emu, {"position": {"map": 0x61, "x": 1, "y": 2, "warp_safe": True}})   # old key no longer works
    with pytest.raises(surgery.SurgeryError):
        surgery.apply(emu, {"position": {"map": 0x62, "x": 1, "y": 2, "unsafe_pos": True}})   # a map change
    assert emu.memory == snap
    writes = surgery.apply(emu, {"position": {"map": 0x61, "x": 1, "y": 2, "unsafe_pos": True}})
    assert writes == [(0xD361, 6, 2), (0xD362, 13, 1)]                             # y then x, nothing else
    assert emu.memory[0xD35E] == 0x61


# --- 8. apply contract -----------------------------------------------------------------------------------------
def test_unknown_or_empty_edits_raise_and_a_failing_edit_writes_nothing():
    emu = world()
    for bad in ({}, {"speed": 9}, {"badges": 0xFF}, "heal"):
        with pytest.raises(surgery.SurgeryError):
            surgery.apply(emu, bad)
    snap = dict(emu.memory)
    with pytest.raises(surgery.SurgeryError):
        surgery.apply(emu, {"heal": True, "money": 1_000_000})                     # heal is fine, money is not
    assert emu.memory == snap
    assert surgery.apply(emu, {"money": 1234, "respawn": 5}) == []                 # only changed bytes are returned


@pytest.mark.parametrize("edits", [
    {"give": [(0x14, 1)], "take": [(0x13, 1)]},
    {"heal": True, "set_hp": {0: 5}},
    {"heal": True, "set_level": {0: 20}},
    {"set_hp": {0: 5}, "set_level": {0: 20}},
])
def test_conflicting_pairs_raise_and_write_nothing(edits):
    emu = world()
    _stock(emu, [(0x14, 50), (0x13, 20)])
    snap = dict(emu.memory)
    with pytest.raises(surgery.SurgeryError, match="sequential edits"):
        surgery.apply(emu, edits, base_stats=lambda s: BASE)
    assert emu.memory == snap


@pytest.mark.parametrize("edits", [{"money": True}, {"set_hp": {0: True}}, {"set_level": {0: True}}])
def test_bool_values_are_refused_as_numbers(edits):
    emu = world()
    snap = dict(emu.memory)
    with pytest.raises(surgery.SurgeryError):
        surgery.apply(emu, edits, base_stats=lambda s: BASE)
    assert emu.memory == snap


def test_give_only_and_take_only_still_apply_alone():
    emu = world()
    _stock(emu, [(0x14, 50)])
    surgery.apply(emu, {"give": [(0x14, 10)]})
    assert read_bag(emu) == [(0x14, 60)]
    surgery.apply(emu, {"take": [(0x14, 60)]})
    assert read_bag(emu) == []


def test_state_edit_refuses_conflicting_flags_with_exit_2(tmp_path, monkeypatch):
    src = _edit_main(tmp_path, monkeypatch)
    out = tmp_path / "out.state"
    assert state_edit.main([str(src), "--out", str(out), "--give", "0x14:1", "--take", "0x13:1"]) == 2
    assert not out.exists()


# --- 9. tools/state_edit.py ------------------------------------------------------------------------------------
def _edit_main(tmp_path, monkeypatch):
    src = tmp_path / "in.state"
    world().save_state(src)
    monkeypatch.setattr(state_edit, "make_emulator", lambda rom: FakeEmulator())
    return src


def test_state_edit_stamps_the_output_synthetic(tmp_path, monkeypatch):
    src = _edit_main(tmp_path, monkeypatch)
    out = tmp_path / "out.state"
    assert state_edit.main([str(src), "--out", str(out), "--heal", "--money", "500"]) == 0
    fp = statefp.read(out)
    assert fp["synthetic"] is True and fp["parent"] == "in.state" and fp["money"] == 500
    assert fp["edited"] == {"heal": True, "money": 500}
    assert fp["lineage"] == "synthetic" and fp["edit_class"] == "shortcut"          # a bare money edit is a shortcut
    assert fp["edit_context"] == {"money_before": 1234, "parent_lineage": "organic"}
    assert fp["legal"]["ok"] is True and statefp.is_synthetic(out)
    assert not (out.parent / (out.name + ".goals.json")).exists()                  # the goals sidecar is NOT copied


def test_state_edit_refuses_an_edit_that_makes_the_state_illegal(tmp_path, monkeypatch):
    src = _edit_main(tmp_path, monkeypatch)
    out = tmp_path / "out.state"
    assert state_edit.main([str(src), "--out", str(out), "--give", "0xFE:1"]) == 2  # 0xFE is not a real item id
    assert not out.exists()
    assert state_edit.main([str(src), "--out", str(out), "--give", "0xFE:1", "--allow-illegal"]) == 0
    fp = statefp.read(out)
    assert fp["legal"]["ok"] is False and any(v.startswith("bag:") for v in fp["legal"]["violations"])


def test_an_input_already_illegal_does_not_block_a_legal_edit(tmp_path, monkeypatch):
    src = _edit_main(tmp_path, monkeypatch)
    emu = FakeEmulator()
    emu.load_state(src)
    emu.memory[0xD31D], emu.memory[0xD31E], emu.memory[0xD31F], emu.memory[0xD320] = 1, 0xFE, 1, 0xFF  # illegal bag
    emu.save_state(src)
    out = tmp_path / "out.state"
    assert state_edit.main([str(src), "--out", str(out), "--money", "500"]) == 0    # same violations in and out
    assert statefp.read(out)["legal"]["ok"] is False


def test_state_edit_refusals(tmp_path, monkeypatch):
    src = _edit_main(tmp_path, monkeypatch)
    assert state_edit.main([str(src), "--out", str(src), "--heal"]) == 2           # OUT == IN
    for sub in ("runs/checkpoints/x.state", "runs/segments/x.state"):
        assert state_edit.main([str(src), "--out", str(tmp_path / sub), "--heal"]) == 2
    out = tmp_path / "out.state"
    out.write_bytes(b"x")
    assert state_edit.main([str(src), "--out", str(out), "--heal"]) == 2           # exists, no --force
    assert state_edit.main([str(src), "--out", str(out), "--heal", "--force"]) == 0
    dry = tmp_path / "dry.state"
    assert state_edit.main([str(src), "--out", str(dry), "--heal", "--dry-run"]) == 0
    assert not dry.exists() and statefp.read(dry) is None                          # --dry-run saves nothing


# --- 10. the synthetic gate ------------------------------------------------------------------------------------
ATT = {"run": "explore-a", "solved": True, "frames": 900, "steps": 30, "seed": 5, "starter": "squirtle",
       "explore_rate": 0.0, "box_pace": 8, "budget": 1500, "maps": [0x26], "tagged": True, "outside": 0, "est": False}


def _job(root, tag):
    """The kept job dir: maps.json, the start-state copy, job.json (same shape as test_segment_curriculum.mkjob)."""
    d = ss.job_dir(root, tag)
    d.mkdir(parents=True, exist_ok=True)
    (d / "maps.json").write_text("{}")
    (d / "bedroom.state").write_bytes(b"s")
    (d / "job.json").write_text(json.dumps({"start_name": "bedroom.state", "start_sha": ss.sha256(d / "bedroom.state")}))
    return d


def _seg(doc):
    return next(s for s in ss.layout(doc) if s.key == "potion")


def _run(root, name="explore-a", start="baseline"):
    run = root / "runs" / name
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"start": start}))
    (run / "end.state").write_bytes(b"END-" + name.encode())
    return run


def test_a_synthetic_job_start_records_no_attempt(tmp_path):
    root, doc = tmp_path, ss.empty_doc()
    d = _job(root, "seg:potion:1-0")
    statefp.write(d / "bedroom.state", {"v": 1, "synthetic": True})
    seg_ingest.record_attempt(root, doc, _seg(doc), dict(ATT), _run(root), "seg:potion:1-0")
    assert doc["stats"] == {}                                                      # no attempt, no n, no best


def test_a_synthetic_start_path_in_meta_records_no_attempt(tmp_path):
    root, doc = tmp_path, ss.empty_doc()
    synth = root / "runs" / "edited" / "x.state"
    synth.parent.mkdir(parents=True)
    synth.write_bytes(b"s")
    statefp.write(synth, {"v": 1, "synthetic": True})
    seg_ingest.record_attempt(root, doc, _seg(doc), dict(ATT), _run(root, start=str(synth)), None)
    assert doc["stats"] == {}


def test_a_normal_start_records_the_attempt(tmp_path):
    root, doc = tmp_path, ss.empty_doc()
    (root / "baselines").mkdir()
    (root / "baselines/bedroom.state").write_bytes(b"s")
    _job(root, "seg:potion:1-0")
    seg_ingest.record_attempt(root, doc, _seg(doc), dict(ATT), _run(root), "seg:potion:1-0")
    st = ss.stat(doc, "potion")
    assert st["n"] == 1 and st["solves"] == 1 and st["best"]["frames"] == 900 and not st["best"]["confirmed"]


def test_a_synthetic_start_is_not_replayable(tmp_path):
    d = _job(tmp_path, "seg:potion:1-0")
    start = d / "bedroom.state"
    b = {"input": str(d / "maps.json"), "start": str(start), "start_sha": ss.sha256(start),
         "seed": 5, "starter": "squirtle", "explore_rate": 0.0, "box_pace": 8}
    assert ss.replayable(b) is True
    statefp.write(start, {"v": 1, "synthetic": True})
    assert ss.replayable(b) is False


def test_confirm_rejects_a_best_from_a_synthetic_start(tmp_path):
    synth = tmp_path / "x.state"
    synth.write_bytes(b"s")
    statefp.write(synth, {"v": 1, "synthetic": True})
    doc = ss.empty_doc()
    st = ss.stat(doc, "potion")
    st["best"] = {"run": "explore-a", "frames": 900, "steps": 30, "confirmed": False, "tries": 0, "rejected": False,
                  "state": None, "input": None, "start": str(synth), "start_sha": "x"}
    b = st["best"]
    assert seg_ingest.record_confirm(tmp_path, doc, _seg(doc), "explore-a", dict(ATT)) == "rejected"
    assert b["rejected"] is True and st["best"] is None
