"""``pokeagent review diff``: first divergence, per-goal deltas, event/rule diffs, warnings."""
from pathlib import Path

from pokeagent.review import diff, load

FIX = Path(__file__).resolve().parent / "fixtures" / "review"
RUNS = FIX / "runs"
RUN_OK = "explore-20261107-150000-1001"
RUN_OK_B = "explore-20261107-150100-1006"


def run(name):
    return load.load_run(RUNS / name)


def test_first_divergence():
    d = diff.diff(run(RUN_OK), run(RUN_OK_B))
    dv = d["divergence"]
    assert dv["step"] == 7
    assert (dv["a"]["button"], dv["a"]["to"]) == ("UP", [35, 10, 28])
    assert (dv["b"]["button"], dv["b"]["to"]) == ("LEFT", [35, 9, 29])
    assert (dv["a"]["rule"], dv["b"]["rule"]) == ("frontier", "frontier")


def test_per_goal_deltas():
    d = diff.diff(run(RUN_OK), run(RUN_OK_B))
    g = d["goals"]["gyarados"]
    assert g["a"] == {"step": 32, "frame": 420} and g["b"] is None
    assert g["delta_steps"] is None and g["delta_frames"] is None
    assert g["first"] == "a"


def test_event_count_and_rule_deltas():
    d = diff.diff(run(RUN_OK), run(RUN_OK_B))
    assert d["event_counts"]["battle"] == {"a": 2, "b": 0}
    assert d["event_counts"]["goal"] == {"a": 1, "b": 0}
    deltas = {r["rule"]: r for r in d["rule_deltas"]}
    assert "menu_back_out" in deltas and deltas["menu_back_out"]["share_b"] > 0.1
    assert "frontier" in deltas          # 0.657 -> 0.833, over RULE_SHARE_DELTA
    assert deltas["frontier"]["delta"] > diff.RULE_SHARE_DELTA


def test_comparability_warnings():
    d = diff.diff(run(RUN_OK), run(RUN_OK_B))
    fields = {w["field"] for w in d["warnings"]}
    assert "seed" in fields and "git_sha" in fields
    assert "starter" not in fields       # same starter: not a warning


def test_identical_and_prefix():
    d = diff.diff(run(RUN_OK), run(RUN_OK))
    assert d["divergence"] is None and d["prefix_only"] is None and d["warnings"] == []
    # one stream a prefix of the other -> no divergence, shorter length reported
    a, b = run(RUN_OK), run(RUN_OK)
    b.transitions = b.transitions[:10]
    d = diff.diff(a, b)
    assert d["divergence"] is None and d["prefix_only"] == 10


def test_exp_delta():
    d = diff.diff(run(RUN_OK), run(RUN_OK_B))
    assert d["exp"] == {"a": 362, "b": 0, "delta": -362}   # 162 + 200 gained, none for B


def test_missing_run_resolves_none():
    assert load.resolve_run_dir("explore-20990101-000000-1", RUNS) is None
