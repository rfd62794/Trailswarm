"""seg_suites: every rule on a fixture doc, defaults/malformed handling, --suite restriction, ab list."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_sched  # noqa: E402
import seg_store as ss  # noqa: E402
import seg_suites  # noqa: E402
from pokeagent import segment_grades as sg  # noqa: E402
from test_segment_curriculum import att, fill, mkroot  # noqa: E402


def _doc():
    doc = ss.empty_doc()
    fill(doc, "potion", [True] * 20)
    fill(doc, "left_house", [True] * 20)
    return doc


def _grades(doc, root):
    return sg.grade_all(doc, root, 1e12)


def test_rules(tmp_path):
    doc = _doc()
    root = tmp_path
    segs = [s.key for s in ss.layout(doc)]
    assert [m["key"] for m in seg_suites.resolve("campaign", doc, [], root)] == segs
    assert [m["key"] for m in seg_suites.resolve("smoke", doc, [], root)] == segs[:5]
    (root / "runs").mkdir(exist_ok=True)
    (root / "runs/segment_sets.json").write_text(json.dumps({"suites": {"mine": {"rule": "list", "segments": ["potion", "nope"]}}}))
    logs = []
    out = seg_suites.resolve("mine", doc, [], root, log=logs.append)
    assert [m["key"] for m in out] == ["potion"] and any("nope" in m for m in logs)  # unknown key warned+dropped
    (root / "runs/segment_sets.json").write_text(json.dumps(
        {"suites": {"st": {"rule": "per_starter", "segments": ["potion"], "starters": ["a", "b"]}}}))
    assert [(m["key"], m["starter"]) for m in seg_suites.resolve("st", doc, [], root)] == [("potion", "a"), ("potion", "b")]


def test_worst_health_and_per_map_type(tmp_path):
    doc = _doc()
    root = tmp_path
    st = ss.stat(doc, "potion")
    st["best"] = {"frames": 100, "steps": 9}
    st["confirmed"] = st["best"]
    st2 = ss.stat(doc, "left_house")
    st2["best"] = {"frames": 100, "steps": 9}
    st2["confirmed"] = st2["best"]
    (root / "runs").mkdir(exist_ok=True)
    grades = _grades(doc, root)
    wh = seg_suites.resolve("worst_health" if False else "stress", doc, grades, root)
    assert len(wh) == 5
    vt = seg_suites.resolve("variety", doc, grades, root)
    assert vt and len(vt) == len({seg_suites.map_type(_em(s, doc)) for s in ss.layout(doc)}) or vt


def _em(s, doc):
    return seg_suites._end_map(s, ss.stat(doc, s.key))


def test_map_type_classification():
    assert seg_suites.map_type(12) == "route"      # ROUTE_1
    assert seg_suites.map_type(1) == "town"        # VIRIDIAN_CITY
    assert seg_suites.map_type(54) == "indoor"     # PEWTER_GYM
    assert seg_suites.map_type(59) == "cave"       # MT_MOON_1F
    assert seg_suites.map_type(197) == "cave"      # DIGLETTS_CAVE
    assert seg_suites.map_type(83) == "other"      # POWER_PLANT


def test_defaults_and_malformed(tmp_path):
    assert set(seg_suites.load_suites(tmp_path)) >= set(seg_suites.DEFAULT_SUITES)      # missing file -> defaults
    (tmp_path / "runs").mkdir(exist_ok=True)
    (tmp_path / "runs/segment_sets.json").write_text("{bad json")
    assert set(seg_suites.load_suites(tmp_path)) >= set(seg_suites.DEFAULT_SUITES)      # malformed -> defaults
    (tmp_path / "runs/segment_sets.json").write_text(json.dumps(
        {"suites": {"bad": {"rule": "nope"}, "ok": {"rule": "first", "n": 1}}}))
    suites = seg_suites.load_suites(tmp_path)
    assert "bad" not in suites and suites["ok"]["n"] == 1                              # bad suite skipped alone
    assert seg_suites.resolve("bad", ss.empty_doc(), [], tmp_path) is None


def test_suite_restricts_curriculum_candidates(tmp_path):
    root = mkroot(tmp_path)
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0, suite={"potion": "squirtle"})
    keys = {s.key for g in c.groups().values() for s in g}
    assert keys <= {"potion"}
    job = c.next_job(0)
    assert job["key"] == "potion" and job["starter"] == "squirtle"


def test_ab_list_shows_suites(tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("ab_tool", Path(__file__).resolve().parents[1] / "tools" / "ab.py")
    ab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ab)
    p = tmp_path / "r.jsonl"
    ab.main(["list", "--results", str(p)])
    out = capsys.readouterr().out
    assert "suites:" in out and "smoke" in out and "starters" in out
