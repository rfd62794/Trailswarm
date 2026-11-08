"""seg_sched grade-driven allocation: effective shares, explore by frontier health, broken-first
regression replay, stale-first polish, identical-to-today with no grade data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_sched  # noqa: E402
import seg_store as ss  # noqa: E402
from pokeagent import segment_grades as sg  # noqa: E402
from test_segment_curriculum import att, fill, mkjob, mkroot  # noqa: E402

NOW = 1_800_000_000.0


def test_no_grade_data_is_identical_to_today(tmp_path):
    root = mkroot(tmp_path)
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    cats = [k for k, _ in [c.choose() for _ in range(20)]]
    assert (cats.count("unsolved"), cats.count("frontier"), cats.count("polish")) == (9, 11, 0)
    job = c.next_job(0)
    assert "explore_rate" not in job                  # every grade column unknown: unchanged explore


def test_polish_share_scales_and_floors(tmp_path):
    root = mkroot(tmp_path)
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    assert sg.effective_shares(list(c._grade_map().values()), seg_sched.SHARES) == dict(seg_sched.SHARES)
    fill(c.doc, "potion", [True] * 20)
    ss.stat(c.doc, "potion")["confirmed"] = {"frames": 800, "run": "r", "steps": 9}
    c.doc["stats"]["potion"]["attempts"] = ([att(True, frames=800, run="r", ts=NOW)]
                                           + [att(True, frames=800, ts=NOW)] * 19)
    eff = sg.effective_shares(list(c._grade_map().values()), seg_sched.SHARES)
    assert eff["polish"] > seg_sched.SHARE_POLISH and abs(sum(eff.values()) - 1.0) < 1e-9
    gm = c._grade_map()
    gm["potion"] = gm["potion"].__class__(**{**gm["potion"].__dict__, "optimized": True})
    assert sg.effective_shares(list(gm.values()), seg_sched.SHARES)["polish"] == sg.POLISH_MIN


def test_explore_rate_rises_as_frontier_health_falls(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    fill(c.doc, "potion", [False] * 20)          # frontier, health ~0 -> explore high
    c.doc["stats"]["potion"]["attempts"] = [att(False, ts=NOW)] * 20
    ss.save(root, c.doc)                             # next_job reloads the doc inside its txn
    job = c.next_job(0)
    assert job["kind"] in ("unsolved", "frontier") and job["explore_rate"] > 0.4
    c2 = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    st = ss.stat(c2.doc, "potion")
    st["attempts"] = [att(True, frames=100, ts=NOW)] * 20
    st["n"], st["solves"] = 20, 20
    st["best"] = st["confirmed"] = {"frames": 100, "steps": 9, "run": "r",
                                   "confirmed": True, "rejected": False, "tries": 2}
    ss.save(root, c2.doc)
    job2 = c2.next_job(0)
    assert job2["explore_rate"] < job["explore_rate"]   # healthy frontier exploits


def _broken_replayable(c, key="potion"):
    st = ss.stat(c.doc, key)
    st["attempts"] = [att(True, git_sha="a")] * 15 + [att(False, git_sha="b")] * 5
    st["n"], st["solves"] = 20, 15
    d = mkjob(c.root, "seg:potion:1-0")
    st["best"] = {"frames": 900, "steps": 30, "run": "explore-a", "confirmed": False, "rejected": False,
                  "tries": 2, "seed": 5, "starter": "squirtle", "explore_rate": 0.0, "box_pace": 8,
                  "budget": 1500, "input": str(d / "maps.json"), "start": str(d / "bedroom.state"),
                  "start_sha": ss.sha256(d / "bedroom.state"), "state": None}


def test_broken_replayable_gets_regression_replay_once_per_window(tmp_path):
    root = mkroot(tmp_path)
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    _broken_replayable(c)
    ss.save(root, c.doc)                              # next_job reloads the doc inside its txn
    job = c.next_job(0)
    assert job["kind"] == "confirm" and job["key"] == "potion" and job["tag"] == "confirm:potion:explore-a"
    c.confirming.clear()
    job2 = c.next_job(1)
    assert not (job2["kind"] == "confirm" and job2["key"] == "potion")   # once per BROKEN_RECHECK_HOURS


def test_stale_first_within_polish(tmp_path):
    root = mkroot(tmp_path)
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0, clock=lambda: NOW)
    for key, ts in (("potion", NOW - 4 * 86400), ("left_house", NOW)):
        st = ss.stat(c.doc, key)
        st["attempts"] = [att(True, frames=1000 + i, ts=ts) for i in range(20)]
        st["n"], st["solves"] = 20, 20
        st["best"] = {"frames": 1000, "steps": 10}
    order = [s.key for s in c.groups()["polish"]]
    assert order[0] == "potion"   # stale ahead of fresh, all else equal
