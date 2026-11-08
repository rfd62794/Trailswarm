"""pokeagent review segments: text + --json scorecard, exit codes, --suite filter."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_store as ss  # noqa: E402
from pokeagent import cli_review  # noqa: E402
from test_segment_curriculum import att, fill  # noqa: E402


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
    assert cli_review.main(["segments", "--root", str(root), "--no-ingest"]) == 1
    out = capsys.readouterr().out
    assert "segments scorecard" in out and "potion" in out and "BROKEN" in out and "shares:" in out
    assert cli_review.main(["segments", "--root", str(root), "--no-ingest", "--json"]) == 1
    s = json.loads(capsys.readouterr().out)
    row = next(r for r in s["rows"] if r["segment"] == "potion")
    assert row["broken"] and row["sha_before"] == 1.0 and row["sha_after"] == 0.0
    assert abs(sum(s["shares"].values()) - 1.0) < 1e-9 and "frontier_health" in s


def test_clean_doc_exits_zero(tmp_path, capsys):
    doc = ss.empty_doc()
    fill(doc, "potion", [True] * 20)
    root = _root(tmp_path, doc)
    assert cli_review.main(["segments", "--root", str(root), "--no-ingest"]) == 0
    assert "potion" in capsys.readouterr().out


def test_unreadable_root_exits_two(tmp_path, capsys):
    assert cli_review.main(["segments", "--root", str(tmp_path / "nowhere"), "--json"]) == 2
    assert "error" in json.loads(capsys.readouterr().out)


def test_suite_filters_rows(tmp_path, capsys):
    doc = ss.empty_doc()
    fill(doc, "potion", [True] * 20)
    fill(doc, "left_house", [True] * 20)
    root = _root(tmp_path, doc)
    (root / "runs/segment_sets.json").write_text(json.dumps({"suites": {"only": {"rule": "list", "segments": ["potion"]}}}))
    assert cli_review.main(["segments", "--root", str(root), "--no-ingest", "--suite", "only", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert [r["segment"] for r in s["rows"]] == ["potion"]
    assert cli_review.main(["segments", "--root", str(root), "--no-ingest", "--suite", "nosuch", "--json"]) == 2
