import importlib.util
import json
from importlib import resources
from pathlib import Path

import pytest

from pokeagent.ramlab.trust import TIERS, no_downgrade, promote_verified, tier_of, validate

_spec = importlib.util.spec_from_file_location("build_ram_map", Path(__file__).resolve().parents[1] / "tools" / "build_ram_map.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

ROWS = json.loads(resources.files("pokeagent.data").joinpath("ram_map.json").read_text(encoding="utf-8"))


def test_migrated_map_validates_and_counts():
    assert validate(ROWS) == []
    counts = {t: 0 for t in TIERS}
    for r in ROWS:
        counts[tier_of(r)] += 1
    assert counts["verified"] + counts["caveat"] == 121
    assert counts["sym"] + counts["verified"] + counts["caveat"] == len(ROWS) == 2792
    by = {r["name"]: r for r in ROWS}
    for name in ("wBattleMon", "wPlayerMonNumber", "wGrassRate", "wGrassMons"):
        assert by[name]["trust"] == "caveat" and "valid when" in by[name]["note"]


def test_tier_derivation_for_rows_without_trust():
    assert tier_of({"name": "a", "verified": True}) == "verified"
    assert tier_of({"name": "a"}) == "sym"
    assert tier_of({"name": "a", "verified": False, "trust": "caveat", "note": "x valid when y"}) == "caveat"


def test_validate_flags_bad_rows():
    assert validate([{"name": "x", "trust": "nonsense"}])
    assert validate([{"name": "x", "trust": "caveat", "note": "no clause"}])
    assert validate([{"name": "x", "trust": "discovered"}])
    assert validate([{"name": "x", "trust": "discovered", "verified": True, "evidence": "e"}])
    assert validate([{"name": "x", "trust": "sym", "verified": True}])
    assert validate([{"name": "x", "trust": "verified", "verified": True}])      # no evidence
    assert not validate([{"name": "x", "trust": "caveat", "note": "n valid when a",
                          "verified": True, "evidence": "e"}])
    assert not validate([{"name": "x", "trust": "discovered", "verified": False, "evidence": "probe"}])


def test_no_downgrade():
    prior = [{k: v for k, v in r.items() if k != "trust"} for r in ROWS]     # the file before migration
    assert no_downgrade(prior, ROWS) == []
    before = [{"name": "x", "verified": True, "evidence": "e"},
              {"name": "y", "verified": True, "trust": "caveat", "note": "n valid when q", "evidence": "e"}]
    after = [{"name": "x", "verified": False, "trust": "sym"},
             {"name": "y", "verified": False, "trust": "sym"}]
    assert sorted(no_downgrade(before, after)) == ["x", "y"]
    promoted = [{"name": "x", "verified": True, "evidence": "e"},
                {"name": "y", "verified": True, "trust": "caveat", "note": "n valid when q", "evidence": "e"}]
    assert no_downgrade(before, promoted) == []


def test_promote_verified_rules():
    row = {"name": "x", "verified": False}
    promote_verified(row, "invariant bcd held in 2/2 states (a, b) on 2026-11-12, tools/ram_recheck.py")
    assert row["verified"] and row["trust"] == "verified" and "bcd" in row["evidence"]
    with pytest.raises(ValueError):
        promote_verified({"name": "y"}, "")
    with pytest.raises(ValueError):
        promote_verified({"name": "z", "trust": "caveat", "note": "n valid when a"}, "e")


def test_carry_keeps_trust():
    entries = [{"name": "wFoo", "addr": "0xC100", "size": 2, "encoding": "u8", "region": "other",
                "verified": False, "source": "s", "sym": "wFoo"}]
    merged = build.carry(entries, [{"name": "wFoo", "addr": "0xC100", "size": 2, "verified": True,
                                  "evidence": "e", "trust": "caveat", "note": "n valid when q"}])
    assert merged[0]["trust"] == "caveat" and merged[0]["verified"]
