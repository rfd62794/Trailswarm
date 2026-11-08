"""Grind points (synthetic fixtures): the ledger file, choose(), episode folding, swarm-merge rules."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pokeagent.grind import points as gp
from pokeagent.grind.atlas import BLACKOUT_STEPS, PRIOR_BLACKOUT, STEPS_PER_MIN

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import swarm_merge  # noqa: E402


def pt(map_id, band=(5, 15), prior=100.0, **kw):
    return gp.GrindPoint(map_id, name=f"MAP{map_id}", level_band=band, xp_per_min_prior=prior, **kw)


def ledger_with(*points):
    return gp.GrindLedger({p.map_id: p for p in points})


def test_ledger_round_trip_and_bad_file(tmp_path):
    led = ledger_with(pt(35, species=[["ODDISH", 7, 12]], patch=[[5, 6]]))
    led.path = tmp_path / "grind_points.json"
    led.save()
    back = gp.GrindLedger.load(led.path)
    assert back.points[35].name == "MAP35" and back.points[35].patch == [[5, 6]]
    assert back.points[35].species == [["ODDISH", 7, 12]] and back.points[35].level_band == (5, 15)
    assert gp.GrindLedger.load(tmp_path / "missing.json").points == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert gp.GrindLedger.load(bad).points == {}           # malformed: empty + a log line, no raise
    (tmp_path / "bad2.json").write_text('{"points": "nope"}', encoding="utf-8")
    assert gp.GrindLedger.load(tmp_path / "bad2.json").points == {}


def test_episode_result_running_mean():
    p = pt(35)
    gp.episode_result(p, 10, 50, 0, ep_id="r1@5")          # rate 45/min
    gp.episode_result(p, 20, 50, 1, ep_id="r1@60")         # rate 90/min, 1 blackout
    assert p.n_measured == 2 and p.xp_per_min_measured == (45 + 90) / 2
    assert p.blackout_rate == 0.5 and p.provenance == "organic"
    p2 = pt(36)
    assert p2.blackout_rate == PRIOR_BLACKOUT and p2.n_measured == 0


def test_merge_is_episode_weighted_and_idempotent():
    a = pt(35)
    gp.episode_result(a, 10, 50, 0, ep_id="r1@5")
    b = pt(35)
    gp.episode_result(b, 20, 50, 0, ep_id="r2@9")
    led, other = ledger_with(a), gp.GrindLedger()
    other.merge(ledger_with(b))
    other.merge(led)
    assert other.points[35].n_measured == 2 and other.points[35].xp_per_min_measured == (45 + 90) / 2
    once = other.to_table()
    other.merge(led)                                       # second merge of the same data: no change
    assert other.to_table() == once


def test_organic_never_overwritten_by_synthetic():
    a = pt(35)
    gp.episode_result(a, 10, 50, 0, ep_id="r1@5")                            # organic
    b = pt(35)
    gp.episode_result(b, 0.1, 50, 0, provenance="synthetic", ep_id="s@1")    # synthetic run saw less
    led = ledger_with(a)
    led.merge(ledger_with(b))
    p = led.points[35]
    assert p.n_measured == 1 and p.xp_per_min_measured == 45 and p.provenance == "organic"
    c = pt(35)
    gp.episode_result(c, 0.1, 50, 0, provenance="synthetic", ep_id="s@1")
    led2 = ledger_with(c)
    led2.merge(ledger_with(a))                                               # organic over synthetic: blended
    p2 = led2.points[35]
    assert p2.n_measured == 2 and p2.provenance == "mixed"


def test_choose_band_filter_gap_and_determinism():
    led = ledger_with(pt(35, prior=100), pt(36, prior=80), pt(37, band=(16, 30), prior=500))
    assert gp.choose(led, [10], 20, None).map_id == 35     # best prior inside the band
    assert gp.choose(led, [10], 20, None).map_id == 35     # deterministic
    assert gp.choose(led, [10], 10, None) is None          # no gap: no grind
    assert gp.choose(led, [25], 40, None).map_id == 37     # only the high band matches L25
    assert gp.choose(led, [20, 9], 20, None, trainee_slot=1).map_id == 35   # the trainee's level decides
    assert gp.choose(led, [20, 9], 20, None) is None                        # lead has no gap


def test_choose_measured_beats_prior_after_two_episodes():
    a = pt(35, prior=10)
    gp.episode_result(a, 10, 50, 0, ep_id="r@1")            # 45/min measured (blackouts 0 -> measured rate 0)
    led = ledger_with(a, pt(36, prior=60))
    assert gp.choose(led, [10], 20, None).map_id == 36      # one episode: still the prior decides
    gp.episode_result(a, 20, 50, 0, ep_id="r@2")
    assert gp.choose(led, [10], 20, None).map_id == 35      # MIN_MEASURED reached: measured 67.5/min wins


def test_choose_travel_and_blackout_penalties():
    maps = {"5": {"warps": {"1,1,UP": [6, 1, 1]}}, "6": {"warps": {"1,1,UP": [7, 1, 1]}}, "7": {}}
    mem = {"maps": maps}
    led = ledger_with(pt(5, band=(1, 99), prior=100), pt(7, band=(1, 99), prior=100))
    assert gp.choose(led, [10], 20, 5, mem).map_id == 5     # same rate, nearer wins
    assert gp.choose(led, [10], 20, 7, mem).map_id == 7
    risky = ledger_with(pt(5, band=(1, 99), prior=100, blackout_rate=0.5),
                        pt(6, band=(1, 99), prior=100, blackout_rate=0.02))
    # from map 5: staying costs 0.5*2000 blackout penalty; one hop away costs ~32/225 + 40
    assert gp.choose(risky, [10], 20, 5, mem).map_id == 6
    assert 0.5 * BLACKOUT_STEPS > gp.HOP_STEPS / STEPS_PER_MIN  # the direction came from the penalty sizes


def test_malformed_rows_are_skipped_with_one_log(caplog):
    import logging
    from pokeagent.grind.points_io import points_of
    with caplog.at_level(logging.INFO, "pokeagent.grind.points_io"):
        assert points_of({"1": {"map_id": 1}, "x": None})[1].map_id == 1   # bad rows skipped, good kept
        assert points_of({"y": "junk"}) == {}
    assert sum("malformed" in r.getMessage() for r in caplog.records) == 1  # logged once, not per row


def test_seed_from_atlas_priors_and_defaults():
    doc = {"atlas": {"BULBASAUR": {"beat_misty": {"12": [
        {"map_id": 35, "name": "ROUTE_24", "xp_per_min": 268.5},
        {"map_id": 36, "name": "ROUTE_25", "xp_per_min": 255.6}]}}},
        "inputs": {"center_cost": {"35": 416}}}
    led = gp.GrindLedger()
    kb = {"wild_by_map": {"35": {"grass": [[7, "ODDISH"], [8, "ODDISH"], [12, "ABRA"]]}}}
    n = led.seed_from_atlas(doc, kb=kb, maps={"35": {"encounters": {"5,6": 2, "7,6": 1}}})
    p = led.points[35]
    assert n == 2 and p.xp_per_min_prior == 268.5 and p.center_cost_frames == 416
    assert p.species == [["ABRA", 12, 12], ["ODDISH", 7, 8]] and p.level_band == (10, 18)
    assert p.patch == [[5, 6], [7, 6]] and p.n_measured == 0 and led.points[36].level_band == gp.DEFAULT_BAND


def test_swarm_merge_grind_points_round_trips():
    a = pt(35)
    gp.episode_result(a, 10, 50, 0, ep_id="r1@5")
    dst, src = {"maps": {}}, {"maps": {}, "grind_points": {"35": a.to_dict()}}
    swarm_merge.merge_memory(dst, src)
    assert dst["grind_points"]["35"]["n_measured"] == 1
    once = json.dumps(dst["grind_points"], sort_keys=True)
    swarm_merge.merge_memory(dst, src)                      # the shared merge is idempotent too
    assert json.dumps(dst["grind_points"], sort_keys=True) == once
