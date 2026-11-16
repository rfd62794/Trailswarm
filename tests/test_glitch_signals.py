"""Glitch signal reads and the detectors that consume them (synthetic FakeEmulator / Snapshot, no ROM):
the Viridian Forest script ceiling, stuck trainer flags, the movement-override byte and the UNVERIFIED
instant-text candidate."""
from __future__ import annotations

import json

from pokeagent import glitch_signals as gs
from pokeagent.emulator import FakeEmulator
from pokeagent.novelty import discoveries as dc
from pokeagent.novelty.features import Snapshot

VFS, MF, S5, ETC, ETS, MO, BAT, D358 = (gs.VIRIDIAN_FOREST_SCRIPT, gs.MISC_FLAGS, gs.STATUS_FLAGS5,
                                       gs.ENGAGED_TRAINER_CLASS, gs.ENGAGED_TRAINER_SET, gs.MOVE_OVERRIDE,
                                       gs.IS_IN_BATTLE, gs.TEXT_DELAY_D358)


def snap(**fields):
    """A Snapshot carrying the given signal bytes (the other feature fields stay default)."""
    return Snapshot(sig=gs.Signals(**fields).as_tuple())


def ctx_for(**kw):
    return {"counts": {}, "maps_known": True, "stage": {}, "seen_species": set(), "stage_now": None, **kw}


def disc(runs_dir):
    return dc.DiscoveryLog(runs_dir, "run-a", "explorer", clock=lambda: 5.0)


# --- read_signals and the pure rules ----------------------------------------------------------------------------------
def test_forest_script_byte_out_of_range(tmp_path):
    assert gs.active_reasons(gs.read_signals(FakeEmulator({VFS: 6}))) == ["script_oor"]
    for ok in (0, 1, 2):
        assert gs.active_reasons(gs.read_signals(FakeEmulator({VFS: ok}))) == []


def test_trainer_flags_rule_needs_flags_set_no_trainer_and_no_battle(tmp_path):
    assert gs.active_reasons(gs.read_signals(FakeEmulator({MF: 1}))) == ["trainer_flags_stuck"]
    assert gs.active_reasons(gs.read_signals(FakeEmulator({S5: 1}))) == ["trainer_flags_stuck"]
    battle = FakeEmulator({MF: 1, S5: 1, BAT: 1})                  # flags set but a battle is on
    assert gs.active_reasons(gs.read_signals(battle)) == []
    engaged = FakeEmulator({MF: 1, S5: 1, ETC: 200, ETS: 3})       # a real trainer mid-approach
    assert gs.active_reasons(gs.read_signals(engaged)) == []


def test_move_override_rule(tmp_path):
    assert gs.active_reasons(gs.read_signals(FakeEmulator({MO: 1}))) == ["move_override"]
    assert gs.active_reasons(gs.read_signals(FakeEmulator({MO: 1, BAT: 2}))) == []   # not checked inside battle


def test_instant_text_is_a_candidate_never_an_active_reason(tmp_path):
    sig = gs.read_signals(FakeEmulator({S5: 0x40}))
    assert gs.instant_text_candidate(sig) and gs.active_reasons(sig) == []
    assert not gs.instant_text_candidate(gs.read_signals(FakeEmulator({S5: 0x20})))


def test_engaged_bytes_are_not_read_inside_a_battle(tmp_path):
    sig = gs.read_signals(FakeEmulator({BAT: 2, ETC: 200, ETS: 7, MO: 1}))
    assert sig.in_battle and (sig.engaged_class, sig.engaged_set) == (0, 0)


def test_tuple_round_trip_and_empty(tmp_path):
    sig = gs.Signals(6, 1, 0x41, 0, 0, 3, False, 2)
    assert gs.Signals.from_tuple(sig.as_tuple()) == sig
    assert gs.Signals.from_tuple(()) is None and gs.Signals.from_tuple(None) is None


# --- detectors ------------------------------------------------------------------------------------------
def test_script_byte_oor_detector_reports_the_byte_and_dedupes(tmp_path):
    lg = disc(tmp_path)
    out = lg.check(snap(forest_script=2), snap(forest_script=6), 3, FakeEmulator({1: 2}), ctx_for())
    rec = [r for r in out if r["kind"] == "glitch_script_oor"][0]
    assert (rec["feature"], rec["before"], rec["after"]) == ("s:0xD618", 2, 6)
    assert json.loads((tmp_path / dc.LOG_NAME).read_text().splitlines()[0])["kind"] == "glitch_script_oor"
    out = lg.check(snap(forest_script=6), snap(forest_script=6), 4, FakeEmulator(), ctx_for())
    assert not [r for r in out if r["kind"] == "glitch_script_oor"]                       # deduped this run
    out = disc(tmp_path).check(Snapshot(), snap(forest_script=6), 5, FakeEmulator(), ctx_for())
    assert [r for r in out if r["kind"] == "glitch_script_oor"][0]["before"] is None      # no previous byte: None


def test_trainer_flags_detector_fires_after_30_consecutive_snapshots(tmp_path):
    lg = disc(tmp_path)
    stuck = snap(misc_flags=1)
    for step in range(dc.STUCK_STEPS - 1):
        assert lg.check(stuck, stuck, step, FakeEmulator(), ctx_for()) == []              # 29 in a row: not yet
    out = lg.check(stuck, stuck, 99, FakeEmulator(), ctx_for())
    assert [r["kind"] for r in out] == ["glitch_trainer_flags"]
    assert out[0]["after"] == {"misc_flags": 1, "status5": 0}


def test_a_gap_in_the_signature_resets_the_streak(tmp_path):
    lg = disc(tmp_path)
    stuck = snap(status5=1)
    for step in range(dc.STUCK_STEPS - 1):
        lg.check(stuck, stuck, step, FakeEmulator(), ctx_for())
    lg.check(Snapshot(), Snapshot(), 99, FakeEmulator(), ctx_for())                       # one clean read: reset
    for step in range(dc.STUCK_STEPS - 1):
        assert lg.check(stuck, stuck, 100 + step, FakeEmulator(), ctx_for()) == []        # 29 again: still silent
    assert not [r for r in lg.records if r["kind"] == "glitch_trainer_flags"]
    assert [r["kind"] for r in lg.check(stuck, stuck, 200, FakeEmulator(), ctx_for())] == ["glitch_trainer_flags"]


def test_move_override_and_instant_text_detectors_use_the_same_streak(tmp_path):
    for kind, snap_sig in (("glitch_move_override", snap(move_override=1)),
                           ("glitch_instant_text", snap(status5=0x40))):
        lg = disc(tmp_path / kind)
        out = []
        for step in range(dc.STUCK_STEPS):
            out = lg.check(snap_sig, snap_sig, step, FakeEmulator(), ctx_for())
        assert [r["kind"] for r in out] == [kind]


def test_instant_text_needs_no_battle_and_empty_sig_fires_nothing(tmp_path):
    lg = disc(tmp_path)
    battling = snap(status5=0x40, in_battle=True)
    for step in range(dc.STUCK_STEPS):
        assert lg.check(battling, battling, step, FakeEmulator(), ctx_for()) == []
    assert lg.check(Snapshot(), Snapshot(), 99, FakeEmulator(), ctx_for()) == []
    assert not lg.records and not (tmp_path / dc.LOG_NAME).exists()
