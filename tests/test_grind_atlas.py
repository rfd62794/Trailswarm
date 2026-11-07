"""Grind atlas: synthetic wild tables and battle logs (no ROM): ranking, risk penalty, Pokecenter term, levels needed, refresh."""
from __future__ import annotations

import json

import pytest

from pokeagent.grind import atlas, refresh
from pokeagent.grind.centers import center_costs
from pokeagent.grind.observed import Obs, band, fold
from pokeagent.grind.xpmath import exp_for_level, xp_gain, xp_needed

TABLES = {"base_exp": {"HI": 100, "LO": 20},
          "wild": {"1": {"grass_rate": 25, "grass": [[10, "HI"]] * 10},
                   "2": {"grass_rate": 25, "grass": [[10, "LO"]] * 10},
                   "3": {"grass_rate": 25, "grass": [[10, "HI"]] * 10}}}
NEAR = {1: 0.0, 2: 0.0, 3: 0.0}


def rank(stats=None, cost=NEAR, **kw):
    return atlas.rank_spots("S", 10, 13, TABLES, stats or {}, cost, **kw)


def battle(m, won=True, fled=False, presses=40, lvl=10, run="r1", **kw):
    return {"kind": 1, "map": m, "won": won, "fled": fled, "presses": presses, "you": [0, lvl], "run": run,
            "hp_end": [5, 20], "turns": [{"hp_you": 20}], **kw}


def test_xp_formula_and_curves():
    assert xp_gain(64, 7) == 64.0 and xp_gain(64, 7, trainer=True) == 96.0 and xp_gain(64, 7, participants=2) == 32.0
    assert exp_for_level("MEDIUM_FAST", 10) == 1000 and exp_for_level("MEDIUM_SLOW", 10) == 560
    assert xp_needed("MEDIUM_SLOW", 10, 13) == exp_for_level("MEDIUM_SLOW", 13) - 560 and xp_needed("FAST", 12, 9) == 0


def test_ranking_prefers_richer_xp_table():
    spots = rank()
    assert [s.map_id for s in spots][-1] == 2 and spots[0].xp_per_step > spots[-1].xp_per_step * 3
    assert all(s.note == "prior only" for s in spots)


def test_levels_needed_scales_with_gap():
    far, near = rank(top=1)[0], atlas.rank_spots("S", 12, 13, TABLES, {}, NEAR, top=1)[0]
    assert near.steps_to_goal < far.steps_to_goal
    assert atlas.rank_spots("S", 13, 13, TABLES, {}, NEAR, top=1)[0].steps_to_goal is None


def test_risk_penalty_demotes_blackout_spot():
    stats = {}
    for _ in range(30):
        fold(stats, battle(1, won=False), {"starter": "S"})   # map 1 always blacks out
        fold(stats, battle(3), {"starter": "S"})
    by = {s.map_id: s for s in rank(stats)}
    assert by[1].blackout > 0.5 and by[3].blackout < 0.1 and by[3].xp_per_step > by[1].xp_per_step * 3
    assert rank(stats)[0].map_id == 3


def test_pokecenter_distance_term():
    near, far = rank(cost={1: 0.0, 2: 0.0, 3: 20000.0}), None
    by = {s.map_id: s for s in near}
    assert by[1].travel_steps == 0 and by[3].travel_steps > 0 and by[1].xp_per_step > by[3].xp_per_step
    assert center_costs({1: {2: 10}, 2: {3: 5}}, [3]) == {3: 0.0, 2: 5.0, 1: 15.0}


def test_observed_overrides_prior_and_real_xp_preferred():
    stats = {}
    for _ in range(200):
        fold(stats, battle(2, exp_gained=500), {"starter": "S"})
    assert rank(stats)[0].map_id == 2   # real exp_gained beats the formula's guess of a poor table
    est = {}
    fold(est, battle(2, run="a", start=5), {"starter": "S"}, estimates={("a", 5): 77.0})
    assert next(iter(est.values())).xp_sum == 77.0 and band(10) == 8
    assert Obs(1, 1, 0, 5, 0.1, 2.0, 1).merge(Obs(1)).n == 2


def test_refresh_is_incremental(tmp_path):
    kb = {"species_by_dex": {"1": {"name": "S", "base_exp": 64, "growth": "MEDIUM_SLOW"}}, "wild_by_map": TABLES["wild"],
          "name_of_internal": {}}
    (tmp_path / "r1").mkdir()
    (tmp_path / "r1" / "meta.json").write_text(json.dumps({"starter": "S", "stop_at_goal": "beat_brock"}))
    log = tmp_path / "battles.jsonl"
    log.write_text("".join(json.dumps(battle(1)) + "\n" for _ in range(5)) + '{"kind": 1, "ma', encoding="utf-8")  # torn tail
    assert refresh.refresh(tmp_path, kb)["folded"] == 5
    assert refresh.refresh(tmp_path, kb)["folded"] == 0
    with log.open("a", encoding="utf-8") as fh:
        fh.write('p": 1}\n' + json.dumps(battle(1)) + "\n")
    out = refresh.refresh(tmp_path, kb)
    doc = json.loads((tmp_path / "grind_atlas.json").read_text())
    assert out["folded"] == 2 and doc["cursor"]["offset"] == log.stat().st_size
    assert doc["stats"]["S|8|1|beat_brock"][0] == 6 and doc["stats"]["|8|1|beat_brock"][0] == 6
    doc["inputs"] = {"need": {"S": {"beat_brock": 13}}, "center_cost": {"1": 0, "2": 0, "3": 0}}
    refresh.save(tmp_path / "grind_atlas.json", doc)
    refresh.refresh(tmp_path, kb)
    top = json.loads((tmp_path / "grind_atlas.json").read_text())["atlas"]["S"]["beat_brock"]["9"]
    assert len(top) == 3 and top[0]["map_id"] in (1, 3)
    assert refresh.refresh(tmp_path / "missing", kb)["folded"] == 0


@pytest.mark.skipif(not __import__("pokeagent.knowledge.kb", fromlist=["ROM_KB"]).ROM_KB, reason="kb/rom_tables.json absent")
def test_rom_tables_have_base_exp_and_growth():
    from pokeagent.knowledge.kb import ROM_KB
    row = next(r for r in ROM_KB["species_by_dex"].values() if r["name"] == "PIDGEY")
    assert row["base_exp"] == 55 and row["growth"] == "MEDIUM_SLOW"
