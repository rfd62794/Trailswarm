"""``pokeagent states library build|list|validate`` and the party-gate rows in ``states check`` / ``states promote``."""
from types import SimpleNamespace

from pokeagent import statefp, statescmd

HARDEN, TACKLE = 106, 33
KAKUNA, CHARMANDER = 113, 176
KB = {"name_of_internal": {"113": "KAKUNA", "176": "CHARMANDER"},
      "moves": {"33": {"name": "TACKLE", "power": 35}, "40": {"name": "POISON STING", "power": 15},
                "106": {"name": "HARDEN", "power": 0}}}
KBLIND = {"name_of_internal": {"176": "CHARMANDER"}, "moves": KB["moves"]}    # KAKUNA unnamed: cannot flag


def member(species, level, moves=()):
    return {"species": species, "level": level, "moves": list(moves), "hp": 10, "max_hp": 10, "ot_id": 1, "exp": 1}


def state(d, name, fp):
    p = d / name
    p.write_bytes(b"x")
    statefp.write(p, fp)
    return p


def _kb(monkeypatch, table=KB):
    monkeypatch.setattr(statescmd, "_kb_json", lambda name: table if name == "rom_tables.json" else None)


def test_library_build_list_validate_round_trip(tmp_path, capsys, monkeypatch):
    _kb(monkeypatch)
    cps, legs = tmp_path / "checkpoints", tmp_path / "states"
    cps.mkdir(), legs.mkdir()
    state(cps, "to_route2.state", {"v": 1, "map": 13, "team": [member(CHARMANDER, 9, (TACKLE,))]})
    state(legs, "14_5_3.state", {"v": 1, "map": 14, "team": [member(KAKUNA, 4, (HARDEN,))]})
    lib = tmp_path / "library.json"
    assert statescmd.cmd_library_build(SimpleNamespace(dir=[str(cps), str(legs)], out=lib, keep_legs=3,
                                                       root=tmp_path)) == 0
    out = capsys.readouterr().out
    assert "checkpoint" in out and "leg" in out and "clean" in out and "violation" in out and "retention" in out
    base = SimpleNamespace(lib=lib, tier=None, segment=None, build=None, clean_only=False)
    assert statescmd.cmd_library_list(base) == 0
    rows = capsys.readouterr().out.strip().splitlines()
    assert len(rows) == 2 and any(r.startswith("checkpoint\tto_route2") for r in rows)
    assert statescmd.cmd_library_list(SimpleNamespace(lib=lib, tier="checkpoint", segment=None, build=None,
                                                      clean_only=True)) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 1
    assert statescmd.cmd_library_list(SimpleNamespace(lib=lib, tier="leg", segment=None, build=None,
                                                      clean_only=True)) == 0
    assert capsys.readouterr().out.strip() == ""                              # the leg is a violation, not clean
    assert statescmd.cmd_library_validate(SimpleNamespace(lib=lib, strict=False, root=tmp_path)) == 0
    assert "0 retirable" in capsys.readouterr().out


def test_validate_names_a_newly_violating_checkpoint_and_its_ancestor(tmp_path, capsys, monkeypatch):
    cps = tmp_path / "checkpoints"
    cps.mkdir()
    state(cps, "to_pewter.state", {"v": 1, "map": 2, "parent": "to_route2.state",
                                  "team": [member(KAKUNA, 7, (HARDEN,))]})
    state(cps, "to_route2.state", {"v": 1, "map": 13, "team": [member(CHARMANDER, 9, (TACKLE,))]})
    lib = tmp_path / "library.json"
    _kb(monkeypatch, KBLIND)                                                 # built before KAKUNA was namable
    assert statescmd.cmd_library_build(SimpleNamespace(dir=[str(cps)], out=lib, keep_legs=3, root=tmp_path)) == 0
    capsys.readouterr()
    _kb(monkeypatch)                                                         # the rule can name it now
    assert statescmd.cmd_library_validate(SimpleNamespace(lib=lib, strict=False, root=tmp_path)) == 1
    out = capsys.readouterr().out
    assert "RETIRABLE to_pewter" in out and "nearest clean ancestor: to_route2" in out


def test_validate_strict_escalates_a_retirable_leg(tmp_path, capsys, monkeypatch):
    legs = tmp_path / "legs"
    legs.mkdir()
    state(legs, "14_5_3.state", {"v": 1, "map": 14, "team": [member(KAKUNA, 4, (HARDEN,))]})
    lib = tmp_path / "library.json"
    _kb(monkeypatch, KBLIND)
    statescmd.cmd_library_build(SimpleNamespace(dir=[str(legs)], out=lib, keep_legs=3, root=tmp_path))
    capsys.readouterr()
    _kb(monkeypatch)
    assert statescmd.cmd_library_validate(SimpleNamespace(lib=lib, strict=False, root=tmp_path)) == 0   # leg only
    assert statescmd.cmd_library_validate(SimpleNamespace(lib=lib, strict=True, root=tmp_path)) == 1    # strict: any
    assert "RETIRABLE 14_5_3" in capsys.readouterr().out


def test_check_fails_on_a_violating_checkpoint_and_lists_unknowns(tmp_path, capsys, monkeypatch):
    _kb(monkeypatch)
    cps = tmp_path / "checkpoints"
    cps.mkdir()
    state(cps, "to_pewter.state", {"v": 1, "team": [member(KAKUNA, 7, (HARDEN,))]})
    state(cps, "odd.state", {"v": 1, "map": 2})                               # no team: unknown verdict
    assert statescmd.cmd_check(SimpleNamespace(dir=[str(cps)], strict=False)) == 1
    out = capsys.readouterr().out
    assert "to_pewter.state\tviolation\twild KAKUNA" in out and "odd.state\tunknown" in out
    legs = tmp_path / "legs"
    legs.mkdir()
    state(legs, "14_5_3.state", {"v": 1, "team": [member(KAKUNA, 4, (HARDEN,))]})
    assert statescmd.cmd_check(SimpleNamespace(dir=[str(legs)], strict=False)) == 0    # a violating leg: listed only
    assert "14_5_3.state\tviolation" in capsys.readouterr().out
    assert statescmd.cmd_check(SimpleNamespace(dir=[str(legs)], strict=True)) == 1     # strict: any state
    only_unknown = tmp_path / "u"
    only_unknown.mkdir()
    state(only_unknown, "u.state", {"v": 1, "map": 2})
    assert statescmd.cmd_check(SimpleNamespace(dir=[str(only_unknown)], strict=False)) == 0
    assert statescmd.cmd_check(SimpleNamespace(dir=[str(only_unknown)], strict=True)) == 1   # strict fails on unknown


def test_promote_refuses_a_violating_end_state(tmp_path, capsys, monkeypatch):
    _kb(monkeypatch)
    end = tmp_path / "end.state"
    end.write_bytes(b"x")
    statefp.write(end, {"v": 1, "team": [member(KAKUNA, 4, (HARDEN,))]})
    args = SimpleNamespace(path=end, start=tmp_path / "start.state", rom=None, dir=None)
    assert statescmd.cmd_promote(args) == 1                                    # refused before any emulator loads
    assert "party rule: wild KAKUNA" in capsys.readouterr().out
