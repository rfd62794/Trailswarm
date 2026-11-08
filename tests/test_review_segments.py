"""pokeagent review segments: text + --json scorecard, exit codes, --suite filter, --ingest opt-in."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_store as ss  # noqa: E402
from pokeagent import cli_review  # noqa: E402
from test_segment_curriculum import att, fill, meta, mkjob, mkrun  # noqa: E402


def _root(tmp_path, doc=None):
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    if doc is not None:
        ss.save(tmp_path, doc)
    return tmp_path


def _doc_broken():
    doc = ss.empty_doc()
    st = ss.stat(doc, "potion")
    st["attempts"] = [att(True, git_sha="a")] * 15 + [att(False, git_sha="b")] * 5
    st["n"], st["solves"] = 20, 15
    return doc


def test_text_and_json_on_fixture_doc(tmp_path, capsys):
    root = _root(tmp_path, _doc_broken())
    assert cli_review.main(["segments", "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "segments scorecard" in out and "potion" in out and "BROKEN" in out and "shares:" in out
    assert cli_review.main(["segments", "--root", str(root), "--json"]) == 1
    s = json.loads(capsys.readouterr().out)
    row = next(r for r in s["rows"] if r["segment"] == "potion")
    assert row["broken"] and row["sha_before"] == 1.0 and row["sha_after"] == 0.0
    assert abs(sum(s["shares"].values()) - 1.0) < 1e-9 and "frontier_health" in s


def test_clean_doc_exits_zero(tmp_path, capsys):
    doc = ss.empty_doc()
    fill(doc, "potion", [True] * 20)
    root = _root(tmp_path, doc)
    assert cli_review.main(["segments", "--root", str(root)]) == 0
    assert "potion" in capsys.readouterr().out


def test_unreadable_root_exits_two(tmp_path, capsys):
    assert cli_review.main(["segments", "--root", str(tmp_path / "nowhere"), "--json"]) == 2
    assert "error" in json.loads(capsys.readouterr().out)


def test_default_is_read_only_and_ingest_is_opt_in(tmp_path, capsys):
    root = _root(tmp_path, ss.empty_doc())
    mkjob(root, "seg:potion:1-0")
    run = mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    for p in run.iterdir():                                   # quiet it: ingest skips a freshly-written run
        os.utime(p, (1, 1))
    before = (root / "runs/segments.json").read_text()
    assert cli_review.main(["segments", "--root", str(root)]) == 0      # a review tool must not write
    capsys.readouterr()
    assert (root / "runs/segments.json").read_text() == before
    assert cli_review.main(["segments", "--root", str(root), "--ingest"]) == 0
    capsys.readouterr()
    assert ss.stat(ss.load(root), "potion")["n"] == 1                   # --ingest updated the store
    assert not (root / "runs/segments.lock").exists()                   # the store lock was released


def test_suite_filters_rows(tmp_path, capsys):
    doc = ss.empty_doc()
    fill(doc, "potion", [True] * 20)
    fill(doc, "left_house", [True] * 20)
    root = _root(tmp_path, doc)
    (root / "runs/segment_sets.json").write_text(json.dumps({"suites": {"only": {"rule": "list", "segments": ["potion"]}}}))
    assert cli_review.main(["segments", "--root", str(root), "--suite", "only", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert [r["segment"] for r in s["rows"]] == ["potion"]
    assert cli_review.main(["segments", "--root", str(root), "--suite", "nosuch", "--json"]) == 2
