"""Build-aware start selection: the curriculum picks (state, build) cells from the states library, attempts
record build/cell and tries, drills never load a violating leg state, and long/stalling segments split at
their slowest map transition."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_ingest  # noqa: E402
import seg_sched  # noqa: E402
import seg_split  # noqa: E402
import seg_store as ss  # noqa: E402
from test_segment_curriculum import att, fill, mkjob, mkroot, mkrun, meta  # noqa: E402
from pokeagent import statefp  # noqa: E402
from pokeagent.legs import schedule as leg_sched  # noqa: E402
from pokeagent.statelib import cells  # noqa: E402


def cp(name="bedroom", build="A", verdict="clean", state="baselines/bedroom.state",
       readiness=0.5, steps=100):
    return {"tier": "checkpoint", "name": name, "segment": "potion", "state": state,
            "build": build, "verdict": verdict,
            "metrics": {"steps": steps, "faints": 0, "readiness": readiness}}


def mklib(root, entries):
    p = root / "runs" / "states"
    p.mkdir(parents=True, exist_ok=True)
    (p / "library.json").write_text(json.dumps({"v": 1, "built": None, "entries": entries}))


def _jobdir_with_cell(root, tag, build="B1", cell="bedroom|B1"):
    d = mkjob(root, tag)
    (d / "job.json").write_text(json.dumps({"start_name": "bedroom.state",
        "start_sha": ss.sha256(d / "bedroom.state"), "build": build, "cell": cell}))
    return d


# --- curriculum start pick -----------------------------------------------------------------------------------
def test_next_job_uses_the_build_pick(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mklib(root, [cp(build="B1"), cp(build="B2")])
    logs = []
    c = seg_sched.Curriculum(root, log=logs.append, quiet_s=0)
    job = c.next_job(0)
    assert job["key"] == "potion" and job["build"] in ("B1", "B2")
    assert job["cell"] == f"bedroom|{job['build']}" and job["pick_mode"] in ("exploit", "alternative", "promising")
    assert job["why"] and Path(job["start"]).name == "bedroom.state"
    assert any(f"(build {job['build']}, {job['pick_mode']})" in m for m in logs)


def test_next_job_without_library_is_unchanged(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    job = c.next_job(0)
    assert job["key"] == "potion" and Path(job["start"]).name == "bedroom.state"
    for k in ("build", "cell", "pick_mode", "why"):
        assert k not in job


def test_violating_and_missing_states_are_never_picked(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mklib(root, [cp(verdict="violation"), cp(build="B2", state="runs/checkpoints/ghost.state")])
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    job = c.next_job(0)
    assert "build" not in job and Path(job["start"]).name == "bedroom.state"


def test_confirm_never_uses_the_picker(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mklib(root, [cp(build="B1"), cp(build="B2")])
    kept = mkjob(root, "seg:potion:1-0") / "bedroom.state"
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    job = c.next_job(0)
    assert job["kind"] == "confirm" and "build" not in job and job["start"] == str(kept)


# --- ingest records build/cell and counts tries ---------------------------------------------------------------
def test_ingest_records_build_cell_and_a_try(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    _jobdir_with_cell(root, "seg:potion:1-0")
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    doc = ss.empty_doc()
    assert seg_ingest.ingest(root, doc, quiet_s=0) == 1
    att0 = ss.stat(doc, "potion")["attempts"][0]
    assert att0["build"] == "B1" and att0["cell"] == "bedroom|B1"
    t = cells.read_tries(root)
    assert t["bedroom|B1"]["tries"] == 1 and t["bedroom|B1"]["solves"] == 1
    _jobdir_with_cell(root, "seg:potion:2-0")
    mkrun(root, "explore-b", meta(tag="seg:potion:2-0"), [], moves=(0x26,) * 1400)   # a fair failure
    seg_ingest.ingest(root, doc, quiet_s=0)
    t = cells.read_tries(root)
    assert t["bedroom|B1"]["tries"] == 2 and t["bedroom|B1"]["solves"] == 1


def test_attempt_without_job_record_reads_none(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mkjob(root, "seg:potion:1-0")                                # old-style record: no build/cell
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    doc = ss.empty_doc()
    seg_ingest.ingest(root, doc, quiet_s=0)
    att0 = ss.stat(doc, "potion")["attempts"][0]
    assert att0["build"] is None and att0["cell"] is None and cells.read_tries(root) == {}


# --- leg drills pick by build, never a violation --------------------------------------------------------------
def _mklegs(root):
    sd = root / "runs" / "legs" / "states"
    sd.mkdir(parents=True)
    rec = {"map": 14, "entry": [5, 3], "exit": [6, 3], "button": "RIGHT",
           "key": "14:5,3>6,3:RIGHT", "par_frames": 100.0, "samples": 5,
           "median_frames": 300.0, "best_frames": 200.0}
    (root / "runs" / "legs.json").write_text(json.dumps({"legs": {rec["key"]: rec}}))
    return sd


def leg_ent(name="14_5_3", build="A", verdict="clean", state="runs/legs/states/x.state"):
    return {"tier": "leg", "name": name, "segment": "to_route3", "state": state,
            "build": build, "verdict": verdict, "metrics": {"steps": 50, "readiness": 0.5}}


def test_drill_never_loads_a_violating_leg_state(tmp_path):
    sd = _mklegs(tmp_path)
    p = sd / "14_5_3.state"
    p.write_bytes(b"x")
    statefp.write(p, {"v": 1, "rule_violations": ["wild KAKUNA L7 (Harden only) in slot 1"]})
    assert leg_sched.pick(tmp_path, now=1e9) is None              # a gated state is never a drill start
    statefp.write(p, {"v": 1, "party": [[1, 5, 10, 10]]})         # verdict unknown: selectable again
    got = leg_sched.pick(tmp_path, now=1e9)
    assert got["state"].endswith("14_5_3.state")


def test_drill_picks_between_two_clean_builds(tmp_path):
    sd = _mklegs(tmp_path)
    (sd / "14_5_3.state").write_bytes(b"x")                        # the newest file, not a library state
    for s in ("14_5_3a.state", "14_5_3b.state", "14_5_3v.state"):
        (sd / s).write_bytes(b"s")
    mklib(tmp_path, [leg_ent(build="A", state="runs/legs/states/14_5_3a.state"),
                     leg_ent(build="B", state="runs/legs/states/14_5_3b.state"),
                     leg_ent(build="V", verdict="violation", state="runs/legs/states/14_5_3v.state")])
    got = leg_sched.pick(tmp_path, now=1e9)
    assert got is not None and Path(got["state"]).name in ("14_5_3a.state", "14_5_3b.state")


# --- the slow cut inside maybe_split ---------------------------------------------------------------------------
def _run_dir(root, name, rows):
    d = root / "runs" / name
    d.mkdir(parents=True)
    (d / "transitions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def _hop(step, frm, to):
    return {"step": step, "from": [frm, 0, 0], "to": [to, 0, 0], "moved": True}


def _slow_runs(tmp_path, n=6):
    rows = [_hop(100, 10, 20), _hop(700, 20, 30), _hop(900, 30, 40)]   # map 20 is the slow stretch
    return [_run_dir(tmp_path, f"r{i}", rows) for i in range(n)]


def test_long_segment_splits_at_the_slowest_transition(tmp_path):
    _slow_runs(tmp_path)
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"] = [att(True, frames=1000, run=f"r{i}") for i in range(6)]   # solves, but 10x par
    st["n"], st["solves"] = 6, 6
    assert seg_split.maybe_split(doc, root=tmp_path, par_fn=lambda s, st_: 100) == ["to_route2"]
    assert doc["splits"]["to_route2"] == [20]


def test_stalling_segment_splits_at_the_slowest_transition(tmp_path):
    _slow_runs(tmp_path)
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"] = ([att(False, run=f"r{i}", stalled=True, maps=[]) for i in range(3)]
                      + [att(True, frames=500, run=f"r{i + 3}") for i in range(3)])
    st["n"], st["solves"] = 6, 3
    assert seg_split.maybe_split(doc, root=tmp_path, par_fn=lambda s, st_: None) == ["to_route2"]
    assert doc["splits"]["to_route2"] == [20]


def test_failure_driven_cut_still_wins(tmp_path):
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"] = ([att(False, maps=(0x0C, 0x01, 0x0D), run=f"f{i}", stalled=True) for i in range(12)]
                      + [att(False, maps=(0x0C, 0x01, 0x99), run="w", stalled=True) for _ in range(6)]
                      + [att(True, run="ok") for _ in range(2)])
    st["n"], st["solves"] = 20, 2
    assert seg_split.maybe_split(doc, root=tmp_path, par_fn=lambda s, st_: 100) == ["to_route2"]
    assert doc["splits"]["to_route2"] == [0x01, 0x0D]   # the failure cut, not the slow cut
