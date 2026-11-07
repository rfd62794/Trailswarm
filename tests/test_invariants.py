"""Invariant checker on synthetic runs/ data (the phantom-warp ROM test skips when the ROM is absent)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pokeagent.invariants import ERROR, WARN, fmt_map, run_all
from pokeagent.invariants.fixplan import fix_plan
from pokeagent.invariants.milestones import check_milestones
from pokeagent.invariants.runner import has_errors
from pokeagent.invariants.segments import check_segments
from pokeagent.invariants.states import check_states
from pokeagent.invariants.tables import check_tables
from pokeagent.invariants.warps import check_warps

ROM = Path(__file__).resolve().parents[1] / "roms" / "Pokemon Red.gb"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM not present")


def _w(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def kinds(fs, kind):
    return [f for f in fs if f.kind == kind]


def test_fmt_map_prints_both_bases():
    assert fmt_map(97) == "97 (0x61)"


@needs_rom
def test_phantom_warp_flagged_and_real_one_is_not(tmp_path):
    # Pallet (map 0): 12,12,UP is a real ROM door; 9,11,UP is the learned phantom.
    _w(tmp_path / "maps.json", {"maps": {"0": {"warps": {"9,11,UP": [40, 5, 11], "12,12,UP": [40, 5, 11]},
                                                "warp_taken": {"9,11,UP": 3}, "warp_disproof": {"9,11,UP": 900}}},
                                "bad_warps": []})
    fs = check_warps(tmp_path / "maps.json", ROM)
    ph = kinds(fs, "phantom_warp")
    assert [f.data["key"] for f in ph] == ["9,11,UP"]
    assert ph[0].level == ERROR and ph[0].data["warp_disproof"] == 900 and ph[0].data["warp_taken"] == 3
    assert "brain.py edit warp_remove 0 9,11,UP" in fix_plan(fs)


def test_phantom_warp_with_injected_grid_and_tombstone(tmp_path):
    import numpy as np
    from pokeagent.legs.grid import Grid
    g = Grid(np.ones((10, 10), bool), np.zeros((10, 10), bool), {(5, 5)})
    _w(tmp_path / "maps.json", {"maps": {"7": {"warps": {"5,5,UP": [1, 0, 0], "2,2,UP": [1, 0, 0], "0,0,UP": [1, 0, 0]}}},
                                "bad_warps": ["7:2,2,UP"]})
    fs = kinds(check_warps(tmp_path / "maps.json", grid_get=lambda m: g), "phantom_warp")
    assert {f.data["key"]: f.level for f in fs} == {"2,2,UP": WARN}   # 5,5 is a warp tile, 0,0,UP leaves the map edge


def test_impossible_milestone(tmp_path):
    _w(tmp_path / "milestones.json", {"to_route4": [{"run": "r1", "step": 10}]})
    _w(tmp_path / "r1" / "meta.json", {"start": "left_house", "initial_goals": []})
    fs = check_milestones(tmp_path)
    assert fs[0].kind == "impossible_milestone" and fs[0].data == {"goal": "to_route4", "count": 1}


def test_respawn_behind_state(tmp_path):
    from pokeagent.checkpoint_goals import write_completed
    ck = tmp_path / "checkpoints"
    ck.mkdir()
    bad, good = ck / "ss_anne_2f.state", ck / "to_ss_anne.best.state"
    for s, r in ((bad, 3), (good, 5)):
        s.write_bytes(b"x")
        write_completed(s, ["potion"], respawn=r)
    fs = check_states(tmp_path)
    assert [f.data["file"] for f in kinds(fs, "respawn_behind")] == ["checkpoints/ss_anne_2f.state"]


def test_discovery_state_as_checkpoint(tmp_path):
    ck = tmp_path / "checkpoints"
    ck.mkdir()
    (ck / "x.discovery.state").write_bytes(b"x")
    assert kinds(check_states(tmp_path), "discovery_as_checkpoint")


def test_bad_split_cut(tmp_path):
    attempts = [{"maps": [96, 97]}, {"maps": [96, 97, 99]}]
    _w(tmp_path / "segments.json", {"splits": {"ss_anne_captain": [97, 50]}, "stats": {"ss_anne_captain": {"attempts": attempts}}})
    fs = kinds(check_segments(tmp_path), "bad_cut")
    assert [f.data["cut"] for f in fs] == [50] and "50 (0x32)" in fs[0].message
    assert kinds(check_segments(tmp_path, valid_ids=frozenset({96, 97})), "bad_cut")[0].data["cut"] == 50


def test_corrupted_tables(tmp_path):
    (tmp_path / "bandit.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "novelty.json").write_text('{"counts": {"a": -1}, "merged": ["r1", "r1"]}', encoding="utf-8")
    (tmp_path / "grind_atlas.json").write_text('{"stats": {"k": [NaN, 1]}}', encoding="utf-8")
    got = {(f.data.get("file"), f.kind) for f in check_tables(tmp_path)}
    assert {("bandit.json", "unparsable"), ("novelty.json", "negative_count"), ("novelty.json", "duplicate_merged"),
            ("grind_atlas.json", "nan")} <= got


def test_run_all_and_cli_exit_code(tmp_path, capsys):
    import importlib.util
    (tmp_path / "bandit.json").write_text("oops", encoding="utf-8")
    assert has_errors(run_all(tmp_path))
    spec = importlib.util.spec_from_file_location("inv_cli", Path(__file__).resolve().parents[1] / "tools" / "invariants.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.main(["check", "--json", "--runs", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert cli.main(["fix-plan", "--runs", str(tmp_path)]) == 0


@needs_rom
def test_load_states_flags_ram_label_mismatch(tmp_path):
    """A real saved state whose label names a different map is flagged (one emulator, loaded once)."""
    from pokeagent.checkpoint_goals import write_completed
    from pokeagent.emulator import PyBoyEmulator
    ck = tmp_path / "checkpoints"
    ck.mkdir()
    emu = PyBoyEmulator(ROM, headless=True)
    try:
        emu.save_state(ck / "to_ss_anne@3c.state")
    finally:
        emu.close()
    write_completed(ck / "to_ss_anne@3c.state", ["potion"], respawn=9)
    fs = check_states(tmp_path, ROM, load=True)
    assert {f.kind for f in fs} >= {"label_map_mismatch", "sidecar_respawn_mismatch"}
