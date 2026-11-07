"""``pokeagent states check --legal`` / ``promote`` handlers called as functions with an injected emulator."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_legality import CATALOG, HM, KB, world as legal_world  # noqa: E402
from pokeagent import lineage, statefp, statescmd  # noqa: E402
from pokeagent.emulator import FakeEmulator  # noqa: E402


def _inject(monkeypatch):
    monkeypatch.setattr(statescmd, "make_emulator", lambda rom: FakeEmulator())
    tables = {"rom_tables.json": KB, "items.json": CATALOG, "hm_compat.json": HM}
    monkeypatch.setattr(statescmd, "_kb_json", lambda name: tables.get(name))


def _save(d, name, emu, **stamp):
    p = d / name
    emu.save_state(p)
    statefp.stamp(emu, p, **stamp)
    return p


def _args(d, **kw):
    return SimpleNamespace(dir=[str(d)], rom=None, legal=True, envelope=False, **kw)


def test_check_legal_flags_the_illegal_state_and_exits_1(tmp_path, monkeypatch, capsys):
    _inject(monkeypatch)
    _save(tmp_path, "good.state", legal_world())
    bad = legal_world()
    bad.memory[0xD347] = 0xAA                                            # money not BCD
    _save(tmp_path, "bad.state", bad)
    assert statescmd.cmd_check(_args(tmp_path)) == 1
    out = capsys.readouterr().out
    assert "good.state\tok" in out
    assert "bad.state\tmoney:" in out


def test_check_legal_all_legal_exits_0_and_envelope_prints_verdicts(tmp_path, monkeypatch, capsys):
    _inject(monkeypatch)
    _save(tmp_path, "good.state", legal_world())
    assert statescmd.cmd_check(_args(tmp_path, )) == 0
    assert "good.state\tok" in capsys.readouterr().out
    args = _args(tmp_path)
    args.envelope = True
    assert statescmd.cmd_check(args) == 0
    out = capsys.readouterr().out
    assert "good.state\tok" in out


def test_check_legal_empty_party_state_is_ok(tmp_path, monkeypatch, capsys):
    _inject(monkeypatch)
    _save(tmp_path, "bedroom.state", FakeEmulator({0xD35E: 0x26, 0xD163: 0, 0xD164: 0xFF, 0xD31D: 0, 0xD31E: 0xFF}))
    assert statescmd.cmd_check(_args(tmp_path)) == 0
    assert "bedroom.state\tok" in capsys.readouterr().out


def _start(d):
    p = d / "start.state"
    p.write_bytes(b"s")
    statefp.write(p, {"v": 1, "lineage": "synthetic", "edit_class": "organic_equivalent", "synthetic": True})
    return p


def _promote_args(d, end, start):
    return SimpleNamespace(dir=[str(d)], rom=None, path=end, start=start)


def test_cmd_promote_success_and_refusal(tmp_path, monkeypatch, capsys):
    _inject(monkeypatch)
    start = _start(tmp_path)
    end = _save(tmp_path, "end.state", legal_world(), inherit=start)
    assert statescmd.cmd_promote(_promote_args(tmp_path, end, start)) == 0
    assert "promoted end.state" in capsys.readouterr().out
    assert statefp.lineage(end) == "promoted"

    stranger = _save(tmp_path, "stranger.state", legal_world())            # organic: not a descendant of start
    assert statescmd.cmd_promote(_promote_args(tmp_path, stranger, start)) == 1
    assert "stranger.state\tpromote:" in capsys.readouterr().out
    assert statefp.lineage(stranger) == "organic"


def test_promote_end_must_descend_from_start(tmp_path):
    start = _start(tmp_path)
    emu = legal_world()
    unrelated = _save(tmp_path, "unrelated.state", emu)
    other = tmp_path / "other.state"
    other.write_bytes(b"s")
    statefp.write(other, {"v": 1, "lineage": "synthetic", "edit_class": "organic_equivalent", "synthetic": True})
    cousin = _save(tmp_path, "cousin.state", emu, inherit=other)           # synthetic, but descended from another start
    shortcut = tmp_path / "sc.state"
    shortcut.write_bytes(b"s")
    statefp.write(shortcut, {"v": 1, "lineage": "synthetic", "edit_class": "shortcut", "synthetic": True})
    short_end = _save(tmp_path, "short_end.state", emu, inherit=shortcut)  # descended from a shortcut edit
    for end in (unrelated, cousin, short_end):
        ok, reasons = lineage.promote(end, start, legal_world(), KB, catalog=CATALOG, hm=HM, env={})
        assert not ok and reasons
        assert statefp.lineage(end) != "promoted"
    assert any("descend" in r for r in lineage.promote(cousin, start, legal_world(), KB, catalog=CATALOG, hm=HM)[1])
    # a two-hop chain still reaches the start; one hop past MAX_DEPTH does not
    mid = _save(tmp_path, "mid.state", emu, inherit=start)
    far = _save(tmp_path, "far.state", emu, inherit=mid)
    assert lineage._descends_from(far, "start.state")
    chain = mid
    for i in range(lineage.MAX_DEPTH):
        chain = _save(tmp_path, f"c{i}.state", emu, inherit=chain)
    assert not lineage._descends_from(chain, "start.state")
