"""envelope.build / within_envelope: per-stage organic maxima from fingerprints, with level/money slack."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent import envelope, statefp  # noqa: E402


def _state(d, name, fp):
    p = d / name
    p.write_bytes(b"s")
    statefp.write(p, {"v": 1, **fp})
    return p


def test_build_keeps_per_stage_maxima_and_ignores_synthetic(tmp_path):
    d = tmp_path / "ck"
    d.mkdir()
    _state(d, "to_vermilion.state", {"party": [[179, 29, 79, 79]], "money": 3000, "badges": 1,
                                   "bag_slots": 4, "heal_items": 2, "respawn": 3})
    _state(d, "to_vermilion.1.state", {"party": [[179, 30, 82, 82], [133, 13, 29, 29]], "money": 9000,
                                       "badges": 2, "bag_slots": 8, "heal_items": 5, "respawn": 5})
    _state(d, "97_13_6.state", {"party": [[22, 20, 60, 60]], "money": 14858, "badges": 2, "respawn": 5})
    _state(d, "edited.state", {"party": [[179, 99, 1, 1]], "money": 999999, "synthetic": True})
    env = envelope.build([d])
    assert env["to_vermilion"] == {"lead": 30, "party": 2, "money": 9000, "badges": 2, "bag_slots": 8,
                                   "heal_items": 5, "respawns": [3, 5]}
    assert env["badges:2"]["lead"] == 20 and env["badges:2"]["money"] == 14858
    assert "edited" not in env and env["to_vermilion"]["lead"] == 30          # the L99 synthetic never entered


def test_within_envelope_slack_and_reasons():
    env = {"to_vermilion": {"lead": 38, "party": 4, "money": 14858, "badges": 2, "bag_slots": 11,
                            "heal_items": 4, "respawns": [5]}}
    at_max = {"party": [[1, 38, 9, 9], [2, 30, 9, 9]], "money": 14858, "badges": 2, "bag_slots": 11, "heal_items": 4}
    assert envelope.within_envelope(at_max, "to_vermilion", env) == (True, [])
    slack = {"party": [[1, 41, 9, 9]], "money": 17829, "badges": 2}           # L+3 and +20% money
    assert envelope.within_envelope(slack, "to_vermilion", env)[0]
    over = {"party": [[1, 45, 9, 9]], "money": 90000, "badges": 3, "bag_slots": 12}
    ok, reasons = envelope.within_envelope(over, "to_vermilion", env)
    assert not ok
    assert any("lead L45 > envelope max L38 + 3" in r for r in reasons)
    assert any("money 90,000 > 14,858 * 1.2" in r for r in reasons)
    assert any("badges 3" in r for r in reasons) and any("bag slots 12" in r for r in reasons)


def test_unknown_stage_cannot_refuse():
    ok, reasons = envelope.within_envelope({"party": [[1, 99, 9, 9]], "money": 999999}, "late_goal", {})
    assert ok and reasons == ["no organic data for stage late_goal"]


def test_stage_key_goal_stem_vs_badges():
    assert envelope.stage_key("ss_anne_captain.state", {}) == "ss_anne_captain"
    assert envelope.stage_key("97_13_6.state", {"badges": 2}) == "badges:2"
    assert envelope.stage_key("x@3c.state", {}) == "badges:0"               # sub-segment stem is not a ladder goal


def test_respawns_seen_unions_all_stages():
    env = {"a": {"respawns": [3, 5]}, "b": {"respawns": [5, 7]}}
    assert envelope.respawns_seen(env) == {3, 5, 7}
