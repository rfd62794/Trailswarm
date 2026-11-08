"""procedures: JSON round trip, the predicate vocabulary, grading/downgrade/disable, and the committed seeds."""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.procedures import predicates, schema, seeds, store


def _state(**kw):
    st = {"map": 35, "x": 11, "y": 34, "hp": 40, "hp_max": 50, "party": [1, 2, 3],
          "badges": 0b11, "flags": {0xD803: 0b10}, "beaten": {(35, 11, 31)}, "bag": {0x14: 2}}
    st.update(kw)
    return st


def test_round_trip_covers_every_predicate_and_action_kind():
    proc = schema.Procedure(goal="g", source="mined", attempts=3, successes=2, best_frames=100, best_presses=9,
                            fail_streak=1, steps=[
        schema.Step("s1", {"kind": "buttons", "buttons": ["UP", "A"]},
                    {"all": [{"map": 35}, {"hp_frac_min": 0.5}, {"party_size_min": 2}, {"badge": 1},
                             {"flag": [0xD803, 1]}, {"has_item": 20}]},
                    {"all": [{"at": [35, 11, 34]}]}),
        schema.Step("s2", {"kind": "goto", "map": 35, "x": 11, "y": 34},
                    {"any": [{"map": 35}, {"map": 36}]}, {"not": {"trainer_beaten": [35, 11, 31]}},
                    True, 1, 2, 90, 3000),
        schema.Step("s3", {"kind": "behaviour", "name": "fight_trainer", "at": [35, 11, 31]},
                    {"all": [{"map": 35}, {"hp_frac_max": 0.9}, {"region": [35, 9, 29, 13, 33]}]},
                    {"all": [{"trainer_beaten": [35, 11, 31]}]}),
        schema.Step("s4", {"kind": "interact", "map": 35, "x": 11, "y": 34, "face": "UP"}, {},
                    {"all": [{"at": [35, 11, 34]}]})])
    back = schema.from_json(json.loads(json.dumps(schema.to_json(proc))))
    assert back == proc


def test_load_returns_none_for_missing_corrupt_or_wrong_version(tmp_path):
    assert store.load("nope", tmp_path) is None
    bad = tmp_path / "g.json"
    bad.write_text("{not json", encoding="utf-8")
    assert store.load("g", tmp_path) is None
    bad.write_text(json.dumps({"version": 99, "goal": "g", "steps": []}), encoding="utf-8")
    assert store.load("g", tmp_path) is None


def test_predicates_cover_the_vocabulary():
    s = _state()
    assert predicates.check({"map": 35}, s) and not predicates.check({"map": 36}, s)
    assert predicates.check({"at": [35, 11, 34]}, s) and not predicates.check({"at": [35, 11, 33]}, s)
    assert predicates.check({"region": [35, 10, 30, 12, 35]}, s) and not predicates.check({"region": [36, 10, 30, 12, 35]}, s)
    assert predicates.check({"hp_frac_min": 0.8}, s) and not predicates.check({"hp_frac_min": 0.9}, s)
    assert predicates.check({"hp_frac_max": 0.8}, s) and not predicates.check({"hp_frac_max": 0.7}, s)
    assert predicates.check({"flag": [0xD803, 1]}, s) and not predicates.check({"flag": [0xD803, 0]}, s)
    assert predicates.check({"badge": 1}, s) and not predicates.check({"badge": 2}, s)
    assert predicates.check({"has_item": 0x14}, s) and not predicates.check({"has_item": 0x13}, s)
    assert predicates.check({"trainer_beaten": [35, 11, 31]}, s) and not predicates.check({"trainer_beaten": [35, 11, 30]}, s)
    assert predicates.check({"party_size_min": 3}, s) and not predicates.check({"party_size_min": 4}, s)
    assert predicates.check({"all": [{"map": 35}, {"hp_frac_min": 0.5}]}, s)
    assert predicates.check({"any": [{"map": 36}, {"map": 35}]}, s)
    assert predicates.check({"not": {"map": 36}}, s) and not predicates.check({"not": {"map": 35}}, s)
    assert predicates.check({}, s)


def test_unknown_predicate_key_is_false_and_logged_once():
    seen: list = []
    log = lambda msg, tag=None: seen.append(msg)
    assert not predicates.check({"bogus_key": 1}, _state(), log)
    assert not predicates.check({"bogus_key": 1}, _state(), log)
    assert len(seen) == 1 and "bogus_key" in seen[0]


def test_grading_attempts_steps_and_disable():
    p = schema.Procedure(goal="g", steps=[schema.Step("s1"), schema.Step("s2")])
    store.grade(p, "s1", True)
    assert p.steps[0].ok == 1
    store.grade(p, None, True, presses=40, frames=900)
    store.grade(p, None, True, presses=60, frames=1200)
    assert (p.attempts, p.successes, p.best_presses, p.best_frames) == (2, 2, 40, 900)
    store.grade(p, "s2", False)
    store.grade(p, "s2", False)
    assert store.downgraded(p.steps[1])
    store.grade(p, "s2", True)          # a later success resets the downgrade
    assert not store.downgraded(p.steps[1])
    for _ in range(store.DISABLE_AFTER):
        store.grade(p, None, False)
    assert p.disabled and p.fail_streak == store.DISABLE_AFTER


def test_next_step_skips_done_and_downgraded():
    steps = [schema.Step("s1", effect={"all": [{"at": [35, 11, 34]}]}),      # already true in state
             schema.Step("s2", fail=2, ok=0, effect={"all": [{"map": 36}]}),  # downgraded
             schema.Step("s3", effect={"all": [{"map": 36}]})]
    assert store.next_step(schema.Procedure(goal="g", steps=steps), _state()) is steps[2]


def test_save_is_atomic_and_round_trips(tmp_path):
    p = schema.Procedure(goal="g", attempts=1, steps=[schema.Step("s1")])
    store.save(p, tmp_path)
    assert store.load("g", tmp_path) == p
    assert not list(tmp_path.glob("*.tmp"))


# --- the committed seeds are produced by the helper, never retyped --------------------------------------
ROUTE24 = [
    {"class": "BUG CATCHER", "party": 9, "x": 11, "y": 31, "mons": [(14, "CATERPIE"), (14, "WEEDLE")]},
    {"class": "LASS", "party": 8, "x": 10, "y": 28, "mons": [(14, "PIDGEY"), (14, "NIDORAN(F)")]},
    {"class": "YOUNGSTER", "party": 4, "x": 11, "y": 25, "mons": [(14, "RATTATA"), (14, "EKANS"), (14, "ZUBAT")]},
    {"class": "LASS", "party": 7, "x": 10, "y": 22, "mons": [(16, "PIDGEY"), (16, "NIDORAN(F)")]},
    {"class": "JR.TRAINER(M)", "party": 3, "x": 11, "y": 19, "mons": [(18, "MANKEY")]},
    {"class": "ROCKET", "party": 6, "x": 11, "y": 15, "mons": [(15, "EKANS"), (15, "ZUBAT")]},
    {"class": "JR.TRAINER(M)", "party": 2, "x": 5, "y": 20, "mons": [(14, "RATTATA"), (14, "EKANS")]},
]
SEED_DIR = Path(seeds.__file__).resolve().parent / "seeds"


def test_seed_gauntlet_six_main_line_steps_south_to_north_jr_optional():
    steps = seeds.seed_gauntlet(35, ROUTE24, optional={(5, 20)})
    fights = [s for s in steps if s["action"]["kind"] == "behaviour" and not s["optional"]]
    assert [s["action"]["at"][1:] for s in fights] == [[11, 31], [10, 28], [11, 25], [10, 22], [11, 19], [11, 15]]
    opt = [s for s in steps if s["optional"]]
    assert {tuple(s["action"]["at"][1:]) for s in opt if s["action"]["kind"] == "behaviour"} == {(5, 20)}
    assert steps[0]["pre"] == {"all": [{"map": 35}, {"region": [35, 9, 29, 13, 33]}, {"hp_frac_min": 0.5}]}
    assert steps[1]["pre"] == {"all": [{"map": 35}, {"not": {"trainer_beaten": [35, 11, 31]}}]}


def test_nugget_bridge_seed_matches_the_helper_output():
    seed = json.loads((SEED_DIR / "nugget_bridge.json").read_text(encoding="utf-8"))
    assert seed["goal"] == "nugget_bridge" and seed["source"] == "seed"
    assert seed["steps"] == seeds.seed_gauntlet(35, ROUTE24, optional={(5, 20)})
    assert schema.from_json(seed) is not None


def test_ss_anne_corridor_seed_shape_and_helper_output():
    seed = json.loads((SEED_DIR / "ss_anne_corridor.json").read_text(encoding="utf-8"))
    assert seed["steps"] == seeds.seed_ss_anne()
    assert schema.from_json(seed) is not None
    gotos = [s for s in seed["steps"] if s["action"]["kind"] == "goto"]
    assert [(g["action"]["map"], g["action"]["x"], g["action"]["y"]) for g in gotos] == [(95, None, None), (96, None, None)]
    rival = next(s for s in seed["steps"] if s["action"].get("boss") == "rival_ss_anne")
    assert rival["action"]["name"] == "fight_trainer" and rival["action"]["at"][0] == 96
    rooms = [s for s in seed["steps"] if s["optional"]]
    assert rooms and all(s["action"]["kind"] == "behaviour" for s in rooms)
    assert {s["action"]["at"][0] for s in rooms} <= {99, 102, 103, 104}
