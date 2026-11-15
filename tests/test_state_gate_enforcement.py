"""The party gate at the ledger, the checkpoint fallback and the stamp path: a violating state goes stale and
unselectable everywhere the sidecars are read; an unknown-verdict state stays exactly as it was."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import seg_store as ss  # noqa: E402
from pokeagent import party_rules, statefp, statelog  # noqa: E402
from pokeagent.emulator import FakeEmulator  # noqa: E402
from pokeagent.explorer.press_frame import PressFrame  # noqa: E402
from pokeagent.legs import states as S  # noqa: E402

LEAD, SIZE = 0xD16B, 44
HARDEN, TACKLE = 106, 33
KAKUNA, PIDGEY = 113, 36
KB = {"name_of_internal": {"36": "PIDGEY", "113": "KAKUNA"},
      "moves": {"33": {"name": "TACKLE", "power": 35}, "106": {"name": "HARDEN", "power": 0}}}


def _mon(emu, slot, species, level, moves=(0, 0, 0, 0), hp=20, mx=20):
    b = LEAD + slot * SIZE
    emu.memory.update({b: species, b + 1: hp >> 8, b + 2: hp & 255, b + 3: level,
                       b + 33: level, b + 34: mx >> 8, b + 35: mx & 255})
    for i, mv in enumerate(moves):
        emu.memory[b + 8 + i] = mv


def world(mons, respawn=5, map_id=0x61):
    """A FakeEmulator on map 0x61 whose party is [(species, level, moves)]."""
    emu = FakeEmulator({0xD35E: map_id, 0xD362: 13, 0xD361: 6, 0xD719: respawn, 0xD356: 0b11,
                        0xD347: 0x00, 0xD348: 0x12, 0xD349: 0x34, 0xD057: 0, 0xD163: len(mons)})
    for i, (sp, lv, mv) in enumerate(mons):
        _mon(emu, i, sp, lv, mv)
    emu.memory.update({0xD31D: 1, 0xD31E: 0x14, 0xD31F: 2, 0xD320: 0xFF})
    return emu


def saved(d, name, emu, mtime=1000.0):
    p = d / name
    emu.save_state(p)
    statefp.stamp(emu, p)
    os.utime(p, (mtime, mtime))
    return p


def test_status_bad_and_select_gate_a_violating_state(tmp_path, monkeypatch):
    monkeypatch.setattr(party_rules, "rom_kb", lambda: KB)
    good = saved(tmp_path, "clean.state", world([(PIDGEY, 9, (TACKLE,))]), 1000)
    saved(tmp_path, "tainted.state", world([(KAKUNA, 4, (HARDEN,))]), 2000)   # newest: would win if kept
    es = {e.path.name: e for e in statelog.entries(tmp_path)}
    assert statelog.status(es["tainted.state"]) == "stale" and statelog.status(es["clean.state"]) == "fresh"
    assert statelog.bad(es["tainted.state"]) == "party rule: wild KAKUNA L4 (Harden only) in slot 1"
    assert statelog.bad(es["clean.state"]) is None
    for want in (statelog.Want(), statelog.Want(strongest=True), statelog.Want(min_hp=0.5)):
        assert statelog.select(list(es.values()), want).path == good
        assert statelog.pick(tmp_path, want) == good
    assert statelog.select([es["tainted.state"]], statelog.Want()) is None


def test_an_unknown_verdict_state_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(party_rules, "rom_kb", lambda: KB)
    p = saved(tmp_path, "old.state", world([(PIDGEY, 9, (TACKLE,))]), 1000)
    fp = statefp.read(p)
    fp.pop("team")                                                          # a v1 sidecar from before team
    statefp.write(p, fp)
    e = statelog.entries(tmp_path)[0]
    assert statelog.status(e) == "fresh" and statelog.bad(e) is None         # unknown is not bad, not stale
    assert statelog.select([e], statelog.Want()).path == p                   # and still selectable


def test_ckpt_fallback_skips_a_violating_state(tmp_path, monkeypatch):
    monkeypatch.setattr(party_rules, "rom_kb", lambda: KB)
    d = tmp_path / "runs" / "checkpoints"
    d.mkdir(parents=True)
    saved(d, "to_pewter.state", world([(KAKUNA, 7, (HARDEN,))]), 2000)        # violating: stale to the ledger
    good = saved(d, "to_gym.state", world([(PIDGEY, 12, (TACKLE,))]), 1000)
    assert ss.ckpt(tmp_path, "to_pewter") is None                             # the fallback refuses it too
    assert ss.ckpt(tmp_path, "to_gym") == good
    bare = d / "deliver_parcel.state"
    bare.write_bytes(b"x")                                                  # unstamped: the old name path stands
    assert ss.ckpt(tmp_path, "deliver_parcel") == bare
    noteam = d / "oaks_parcel.state"
    noteam.write_bytes(b"x")
    statefp.write(noteam, {"v": 1, "map": 1})                               # stamped, no team: unknown, kept
    assert ss.ckpt(tmp_path, "oaks_parcel") == noteam


def test_leg_saver_marks_a_violating_state_unselectable(tmp_path, monkeypatch):
    monkeypatch.setattr(party_rules, "rom_kb", lambda: KB)
    c = SimpleNamespace(emu=world([(KAKUNA, 4, (HARDEN,))]), run_dir=tmp_path / "run-1", logs=[])
    c.log = lambda t, tag=None: c.logs.append(t)
    p = S.LegStateSaver(tmp_path / "s").observe(c, PressFrame("RIGHT", "agent", "", before=(1, 0, 0),
                                                            after=(0x61, 13, 6), box_after=False))
    assert p is not None and p.exists()                                     # still saved: it is evidence
    assert statefp.read(p)["rule_violations"] == ["wild KAKUNA L4 (Harden only) in slot 1"]
    assert any("state gate" in m and "wild-never-catch" in m for m in c.logs)
    e = statelog.entries(tmp_path / "s")[0]
    assert statelog.status(e) == "stale" and statelog.pick(tmp_path / "s", statelog.Want()) is None


def test_quarantine_name_protects_a_clean_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(party_rules, "rom_kb", lambda: KB)
    dest = tmp_path / "to_pewter.state"
    dest.write_bytes(b"old")
    statefp.write(dest, statefp.fingerprint(world([(PIDGEY, 9, (TACKLE,))])))
    dirty = statefp.fingerprint(world([(KAKUNA, 4, (HARDEN,))]))
    assert party_rules.quarantine_dest(dirty, dest, party_rules.rom_kb()).name == "to_pewter.quarantine.state"
    assert statefp.read(dest)["team"][0]["species"] == PIDGEY               # the clean checkpoint is untouched
    clean = statefp.fingerprint(world([(PIDGEY, 9, (TACKLE,))]))
    assert party_rules.quarantine_dest(clean, dest, party_rules.rom_kb()) == dest
