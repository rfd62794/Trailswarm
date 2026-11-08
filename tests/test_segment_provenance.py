"""Provenance column and the synthetic_only hypothesis grade: promotion by an organic solve."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_sched  # noqa: E402
import seg_store as ss  # noqa: E402
from pokeagent import segment_grades as sg  # noqa: E402
from test_segment_curriculum import att, fill, mkroot  # noqa: E402

NOW = 1_800_000_000.0


def _grade(doc, key="potion", now=NOW):
    seg = next(s for s in ss.layout(doc) if s.key == key)
    return sg.grade_segment(seg, ss.stat(doc, key), ss.FRAMES_PER_STEP, None, now)


def _solved_doc(provenance):
    doc = ss.empty_doc()
    st = ss.stat(doc, "potion")
    st["attempts"] = [att(True, frames=800, provenance=p) for p in provenance]
    st["n"], st["solves"] = len(provenance), sum(1 for p in provenance)
    return doc


def test_provenance_column():
    assert _grade(_solved_doc(["organic"] * 20)).provenance == "organic"
    assert _grade(_solved_doc(["synthetic"] * 20)).provenance == "synthetic"
    assert _grade(_solved_doc(["organic"] * 10 + ["synthetic"] * 10)).provenance == "mixed"
    doc = ss.empty_doc()
    fill(doc, "potion", [True] * 20)
    assert _grade(doc).provenance == "unknown"                     # no lineage recorded anywhere
    assert _grade(ss.empty_doc()).provenance == "unknown"          # no solves at all


def test_synthetic_only_hypothesis_and_promotion():
    doc = _solved_doc(["synthetic"] * 20)
    g = _grade(doc)
    assert g.synthetic_only and g.solved                           # solved flag stays raw (is_solved)
    assert not g.optimized
    assert not sg.solved_effective(g)                              # not a solve for the shares
    eff = sg.effective_shares([g], dict(seg_sched.SHARES))
    assert eff["polish"] == sg.POLISH_MIN                          # a hypothesis earns no polish share
    doc["stats"]["potion"]["attempts"].append(att(True, frames=800, provenance="organic"))
    g2 = _grade(doc)
    assert not g2.synthetic_only and g2.provenance == "mixed"      # one organic solve promotes it


def test_recorded_best_is_organic_evidence():
    doc = _solved_doc(["synthetic"] * 20)
    ss.stat(doc, "potion")["best"] = {"frames": 700, "steps": 9}
    assert not _grade(doc).synthetic_only                          # a recorded best only comes from organic


def test_organic_reproduction_job(tmp_path):
    root = mkroot(tmp_path)
    logs = []
    c = seg_sched.Curriculum(root, log=logs.append, quiet_s=0)
    fill(c.doc, "potion", [])
    st = ss.stat(c.doc, "potion")
    st["attempts"] = [att(True, frames=800, provenance="synthetic")] * 20
    st["n"], st["solves"] = 20, 20
    ss.save(root, c.doc)                                       # next_job reloads the doc inside its txn
    job = c.next_job(0)
    assert job["kind"] == "repro" and job["key"] == "potion", logs  # organic-reproduction job first
    assert job["explore_rate"] == 0.0
    job2 = c.next_job(1)
    assert job2["kind"] != "repro"                                 # throttled to one per BROKEN_RECHECK_HOURS
