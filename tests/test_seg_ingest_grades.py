"""seg_ingest scorecard fields: git_sha/ts/blackouts/stalled/provenance/loops, one battles pass."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_ingest  # noqa: E402
import seg_store as ss  # noqa: E402
from pokeagent import segment_grades as sg  # noqa: E402
from pokeagent import statefp  # noqa: E402
from test_segment_curriculum import att, meta, mkjob, mkroot, mkrun  # noqa: E402


def _grade(doc, key="potion"):
    seg = next(s for s in ss.layout(doc) if s.key == key)
    return sg.grade_segment(seg, ss.stat(doc, key), ss.FRAMES_PER_STEP, None, 1e12)


def test_build_attempt_adds_scorecard_fields(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mkjob(root, "seg:potion:1-0")
    d = mkrun(root, "explore-20261107-120000-1", meta(git_sha="deadbeef"), [{"goal": "potion", "step": 30, "frame": 900}])
    (d / "loops.jsonl").write_text(json.dumps({"kind": "veto"}) + "\n" + json.dumps({"kind": "probe"}) + "\n")
    (root / "runs/stalls").mkdir(parents=True)
    (root / "runs/stalls/explore-20261107-120000-1.json").write_text("{}")
    (root / "runs/battles.jsonl").write_text(
        json.dumps({"run": "explore-20261107-120000-1", "outcome": "blackout"}) + "\n"
        + json.dumps({"run": "explore-20261107-120000-1", "outcome": "won"}) + "\n"
        + json.dumps({"run": "other-run", "outcome": "blackout"}) + "\n")
    doc = ss.empty_doc()
    seg_ingest.ingest(root, doc, quiet_s=0)
    a = ss.stat(doc, "potion")["attempts"][0]
    assert a["git_sha"] == "deadbeef" and a["ts"] is not None
    assert a["blackouts"] == 1 and a["stalled"] is True and a["loops"] == 1
    assert a["provenance"] == "organic"                       # fixture bedroom.state: organic lineage
    assert a["rejoin"] is False


def test_provenance_synthetic_and_unknown(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    d = mkjob(root, "seg:potion:1-0")
    statefp.write(d / "bedroom.state", {"v": 1, "lineage": "synthetic"})
    run = mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    meta_d = json.loads((run / "meta.json").read_text())
    att_d = seg_ingest.build_attempt(run, meta_d, "potion", root=root, battle_index={})
    assert att_d["provenance"] == "synthetic"
    run2 = mkrun(root, "explore-b", meta(tag="seg:potion:1-9"), [{"goal": "potion", "step": 30, "frame": 900}])
    att2 = seg_ingest.build_attempt(run2, json.loads((run2 / "meta.json").read_text()), "potion",
                                    root=root, battle_index={})
    assert att2["provenance"] == "unknown"                    # no job record for tag 1-9, meta start unresolvable


def test_old_attempts_grade_as_unknown():
    doc = ss.empty_doc()
    st = ss.stat(doc, "potion")
    st["attempts"] = [att(True, frames=800)] * 20            # plain old attempt: none of the new fields
    st["n"], st["solves"] = 20, 20
    g = _grade(doc)
    assert g.solved and g.provenance == "unknown"            # a field old attempts lack reads unknown
    assert not g.synthetic_only                              # unknown is not an indictment
    assert g.blackout_rate is None and g.stall_rate is None and g.loop_rate is None
    assert not g.broken and g.last_ts is None


def test_accepted_and_chain_untouched(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mkjob(root, "seg:potion:1-0")
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    doc = ss.empty_doc()
    seg_ingest.ingest(root, doc, quiet_s=0)
    st = ss.stat(doc, "potion")
    assert ss.accepted(st)["frames"] == 900 and ss.best_frames(st) == 900
    c = ss.chain(doc)
    assert c["rows"][0] == ("potion", 900)                   # chain bests semantics untouched
