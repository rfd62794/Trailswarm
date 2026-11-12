"""Observation loader, measured address table and CLI (synthetic data only, no ROM)."""
from __future__ import annotations

import importlib.util
import json
import random
import re
import sys
from pathlib import Path

import pytest

from pokeagent.ram_lookup import MapEntry
from pokeagent.ramlab.address_table import STATUS_RULES, build_table
from pokeagent.ramlab.observations import GAMES, ObservationError, Sample, load_observation_file, load_observations

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ram_address_table", ROOT / "tools" / "ram_address_table.py")
cli = importlib.util.module_from_spec(_spec)
sys.modules["ram_address_table"] = cli
_spec.loader.exec_module(cli)


def write_obs(path: Path, game: str = "pokemon-red", samples: list | None = None, **extra) -> Path:
    path.write_text(json.dumps({"version": 1, "game": game, "samples": samples or [], **extra}), encoding="utf-8")
    return path


def S(addr: int, value: int, context: str) -> Sample:
    return Sample(addr, value, context)


def row(table: dict, label: str) -> dict:
    return next(r for r in table["entries"] if r["label"] == label)


CUR_MAP = MapEntry("wCurMap", 0xD35E, 1, "map", "u8", True)
GOOD = {"addr": "0xD35E", "value": 12, "context": "walk-route1"}


@pytest.mark.parametrize("doc, rule", [
    ({"version": 2, "game": "pokemon-red", "samples": []}, "version must be 1"),
    ({"version": 1, "game": "pokemon-yellow", "samples": []}, "game must be one of"),
    ({"version": 1, "game": "pokemon-red", "samples": {}}, "samples must be a list"),
    ({"version": 1, "game": "pokemon-red", "samples": [], "notes": "x"}, "unknown key"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "addr": "D35E"}]}, "addr must be a hex string"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "addr": "0xD35"}]}, "addr must be a hex string"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "addr": 54110}]}, "addr must be a hex string"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "addr": "0x8000"}]}, "addr must be in"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "addr": "0xFFFF"}]}, "addr must be in"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "value": 256}]}, "value must be an int 0..255"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "value": -1}]}, "value must be an int 0..255"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "value": "12"}]}, "value must be an int 0..255"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "value": True}]}, "value must be an int 0..255"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "context": "Walk Route 1"}]}, "context must match"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "context": ""}]}, "context must match"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "context": "a" * 65}]}, "context must match"),
    ({"version": 1, "game": "pokemon-red", "samples": [{**GOOD, "text": "HELLO"}]}, "unknown key"),
    ({"version": 1, "game": "pokemon-red", "samples": [{"addr": "0xD35E", "value": 1}]}, "missing key"),
])
def test_loader_rejects_bad_game_addr_value_context_and_unknown_keys(tmp_path, doc, rule):
    p = tmp_path / "obs.json"
    if isinstance(doc.get("samples"), list) and doc["samples"]:
        doc["samples"] = [GOOD, *doc["samples"]]
    p.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ObservationError) as err:
        load_observation_file(p)
    msg = str(err.value)
    assert str(p) in msg and rule in msg
    if doc.get("samples") and isinstance(doc["samples"], list):
        assert "sample 1" in msg


def test_loader_accepts_good_file_and_merges_by_game(tmp_path):
    a = write_obs(tmp_path / "a.json", samples=[GOOD, {"addr": "0xFF80", "value": 0, "context": "hram:probe"}])
    b = write_obs(tmp_path / "b.json", samples=[{**GOOD, "value": 3}])
    c = write_obs(tmp_path / "c.json", game="pokemon-blue")
    merged = load_observations([a, b, c])
    assert set(merged) == set(GAMES)
    assert merged["pokemon-red"] == [S(0xD35E, 12, "walk-route1"), S(0xFF80, 0, "hram:probe"), S(0xD35E, 3, "walk-route1")]
    assert merged["pokemon-blue"] == []


def test_sample_credits_only_the_tightest_covering_entry():
    struct = MapEntry("wPartyMon1", 0xD16B, 44, "party")
    field = MapEntry("wPartyMon1HP", 0xD16C, 2, "party", "u16be")
    t = build_table([struct, field], {"pokemon-red": [S(0xD16D, 1, "a"), S(0xD16D, 2, "b")]})
    assert row(t, "wPartyMon1HP")["games"]["pokemon-red"]["samples"] == 2
    assert row(t, "wPartyMon1HP")["games"]["pokemon-red"]["status"] == "measured"
    assert row(t, "wPartyMon1")["games"]["pokemon-red"]["samples"] == 0
    assert row(t, "wPartyMon1")["games"]["pokemon-red"]["status"] == "not-exercised"
    t2 = build_table([struct, field], {"pokemon-red": [S(0xD16B, 1, "a")]})
    assert row(t2, "wPartyMon1")["games"]["pokemon-red"]["samples"] == 1


@pytest.mark.parametrize("samples, status", [
    ([], "not-exercised"),
    ([S(0xD35E, 5, "a"), S(0xD35E, 5, "b"), S(0xD35E, 5, "c")], "believed"),
    ([S(0xD35E, 1, "a"), S(0xD35E, 2, "a")], "believed"),
    ([S(0xD35E, 1, "a"), S(0xD35E, 2, "b")], "measured"),
])
def test_status_boundaries(samples, status):
    rec = build_table([CUR_MAP], {"pokemon-red": samples})["entries"][0]["games"]["pokemon-red"]
    assert rec["status"] == status
    assert rec["samples"] == len(samples)
    assert rec["distinct_values"] == len({s.value for s in samples})
    assert rec["exercised_by"] == sorted({s.context for s in samples})


def test_exercised_by_is_capped_at_eight():
    samples = [S(0xD35E, i, f"ctx-{i:02d}") for i in range(12)]
    rec = build_table([CUR_MAP], {"pokemon-red": samples})["entries"][0]["games"]["pokemon-red"]
    assert rec["exercised_by"] == [f"ctx-{i:02d}" for i in range(8)]
    assert rec["samples"] == 12


def test_games_are_independent():
    t = build_table([CUR_MAP], {"pokemon-red": [S(0xD35E, 1, "a"), S(0xD35E, 2, "b")]})
    games = t["entries"][0]["games"]
    assert games["pokemon-red"]["status"] == "measured"
    assert games["pokemon-blue"] == {"status": "not-exercised", "samples": 0, "distinct_values": 0, "exercised_by": []}


def test_output_contains_no_raw_values_and_no_sym_text():
    note = "planted note text do not copy"
    entry = MapEntry("wTestByte", 0xD000, 1, "misc", "u8", True, "pokered.sym (pret/pokered, symbols branch)", note)
    t = build_table([entry], {"pokemon-red": [S(0xD000, 237, "a"), S(0xD000, 237, "b")]})
    text = json.dumps(t, indent=1)
    assert "pokered.sym" not in text and note not in text
    assert not re.search(r"(?<![0-9A-Za-z])237(?![0-9])", text)
    assert '"value"' not in text
    for key in ('"source"', '"sym"', '"evidence"', '"note"', '"alias"'):
        assert key not in text
    rec = t["entries"][0]["games"]["pokemon-red"]
    assert rec["distinct_values"] == 1 and isinstance(rec["distinct_values"], int)
    assert set(t["entries"][0]) == {"addr", "label", "width", "type", "region", "ram_map_verified", "games"}


def test_unmapped_samples_are_listed():
    t = build_table([CUR_MAP], {"pokemon-red": [S(0xC0FF, 1, "a"), S(0xC0FF, 2, "b"), S(0xD35E, 1, "a")],
                                "pokemon-blue": [S(0xC001, 9, "x")]})
    assert t["unmapped"] == [{"addr": "0xC001", "samples": {"pokemon-red": 0, "pokemon-blue": 1}},
                             {"addr": "0xC0FF", "samples": {"pokemon-red": 2, "pokemon-blue": 0}}]
    assert row(t, "wCurMap")["games"]["pokemon-red"]["samples"] == 1


def test_output_is_deterministic():
    entries = [CUR_MAP, MapEntry("wPartyMon1", 0xD16B, 44, "party"), MapEntry("wPartyMon1HP", 0xD16C, 2, "party", "u16be"),
               MapEntry("hJoyInput", 0xFFB4, 1, "hram", "bitmask"), MapEntry("wAlias", 0xD35E, 1, "map", "u8")]
    samples = [S(0xD35E, v, f"c{v % 3}") for v in range(6)] + [S(0xD16D, 4, "x"), S(0xC0FF, 1, "y"), S(0xFFB4, 3, "z")]
    rng = random.Random(7)
    first = json.dumps(build_table(entries, {"pokemon-red": samples, "pokemon-blue": samples[:3]}), indent=1)
    e2, s2 = entries[:], samples[:]
    rng.shuffle(e2)
    rng.shuffle(s2)
    blue = samples[:3]
    rng.shuffle(blue)
    second = json.dumps(build_table(e2, {"pokemon-blue": blue, "pokemon-red": s2}), indent=1)
    assert first == second
    addrs = [(r["addr"], r["label"]) for r in json.loads(first)["entries"]]
    assert addrs == sorted(addrs)


def test_cli_writes_table_and_exits_2_on_bad_input(tmp_path, capsys):
    good = write_obs(tmp_path / "good.json", samples=[GOOD, {**GOOD, "value": 0, "context": "pallet-town-start"}])
    out = tmp_path / "nested" / "table.json"
    retro = tmp_path / "retro"
    assert cli.main([str(good), "--out", str(out), "--retro-dir", str(retro)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n") and json.loads(text)["schema_version"] == 1
    for game in GAMES:
        assert (retro / game / "data.json").exists()
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("pokemon-red: measured=1 ") and "unmapped=0" in lines[0] and "retro-skipped-untyped=0" in lines[0]
    assert lines[1].startswith("pokemon-blue: measured=0 believed=0 ")

    bad = write_obs(tmp_path / "bad.json", samples=[{**GOOD, "value": 999}])
    out2, retro2 = tmp_path / "out2" / "table.json", tmp_path / "retro2"
    assert cli.main([str(good), str(bad), "--out", str(out2), "--retro-dir", str(retro2)]) == 2
    assert not out2.exists() and not out2.parent.exists() and not retro2.exists()
    assert "value must be an int 0..255" in capsys.readouterr().err


def test_cli_on_the_packaged_map_with_one_synthetic_file(tmp_path):
    obs = write_obs(tmp_path / "red.json", samples=[{"addr": "0xD35E", "value": 0, "context": "pallet-town-start"},
                                                    {"addr": "0xD35E", "value": 12, "context": "walk-route1"}])
    out = tmp_path / "table.json"
    assert cli.main([str(obs), "--out", str(out)]) == 0
    table = json.loads(out.read_text(encoding="utf-8"))
    cur = row(table, "wCurMap")
    assert cur["addr"] == "0xD35E" and cur["type"] == "u8" and cur["width"] == 1
    assert cur["games"]["pokemon-red"]["status"] == "measured"
    assert cur["games"]["pokemon-blue"]["status"] == "not-exercised"
    assert sum(r["games"]["pokemon-red"]["status"] == "measured" for r in table["entries"]) == 1


def test_schema_file_is_valid_json_and_lists_the_same_statuses():
    schema = json.loads((ROOT / "docs" / "data" / "gen1_ram_addresses.schema.json").read_text(encoding="utf-8"))
    assert schema["$defs"]["status"]["enum"] == list(STATUS_RULES)
    assert sorted(schema["properties"]["status_rules"]["required"]) == sorted(STATUS_RULES)
    assert schema["$defs"]["game"]["enum"] == list(GAMES)
    desc = schema["properties"]["entries"]["items"]["properties"]["ram_map_verified"]["description"]
    assert "single-game claim of unknown game" in desc
