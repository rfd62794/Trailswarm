"""seg_split: long-solve trigger, event-ranked cuts, cut_hints, should_rejoin + rejoin probes."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_sched  # noqa: E402
import seg_split  # noqa: E402
import seg_store as ss  # noqa: E402
from pokeagent import segment_grades as sg  # noqa: E402
from test_segment_curriculum import att, fill, mkroot  # noqa: E402


def _flaky(n_ok, wander=(0x0C, 0x01, 0x99), **kw):
    return ([att(False, maps=(0x0C, 0x01, 0x0D), **kw) for _ in range(12)]
            + [att(False, maps=wander, **kw) for _ in range(20 - 12 - n_ok)] + [att(True) for _ in range(n_ok)])


def test_long_solve_trigger_needs_par_and_solves():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = [att(True, frames=900, steps=90)] * 10 + [att(True, frames=900, steps=90)] * 10, 20
    assert not seg_split.should_split_long(st, None)            # no par: skipped, never guessed
    assert seg_split.should_split_long(st, 200.0)               # median 900 > 3x200
    assert not seg_split.should_split_long(st, 400.0)
    st["attempts"] = [att(True, frames=900)] * 4 + [att(False)] * 16
    assert not seg_split.should_split_long(st, 200.0)           # too few solves to trust the median


def test_maybe_split_long_trigger_fires_with_par_fn():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = _flaky(8)[:15] + [att(True, frames=900) for _ in range(5)], 20
    got = seg_split.maybe_split(doc, par_fn=lambda s, st_: 200.0)
    assert got == ["to_route2"] and doc["splits"]["to_route2"] == [0x01, 0x0D]


def _run_with_events(root, name, events_steps):
    d = root / "runs" / name
    d.mkdir(parents=True)
    (d / "transitions.jsonl").write_text("".join(json.dumps({"step": s, "from": [m0, 0, 0], "to": [m1, 0, 0]}) + "\n"
                                                for m0, m1, s in events_steps))
    return d


def test_event_ranked_cut_prefers_a_cut_after_a_heal(tmp_path):
    root = tmp_path
    # candidate maps 0x01..0x06 (> MAX_CUTS); run enters a POKECENTER (41) just before map 0x05
    maps = [0x0C] + [0x01, 0x02, 0x03, 0x04, 41, 0x05, 0x06]
    fails = [att(False, maps=maps, run="explore-a") for _ in range(3)]
    steps = [(0x0C, 0x01, 10), (0x01, 0x02, 20), (0x02, 0x03, 30), (0x03, 0x04, 40), (0x04, 41, 50), (41, 0x05, 60), (0x05, 0x06, 70)]
    rd = _run_with_events(root, "explore-a", steps)
    cuts = seg_split.cut_maps(fails, run_dirs=[rd])
    assert 41 in cuts and len(cuts) == 4 and 0x06 not in cuts        # the heal-supported cut survives the cap
    assert cuts == sorted(cuts, key=maps.index)                      # emitted in travel order


def test_cut_hints_reports_non_mappable_event_cuts(tmp_path):
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = [att(False, maps=[0x0C, 0x01], run="explore-a") for _ in range(3)], 3
    rd = _run_with_events(tmp_path, "explore-a", [(0x0C, 0x01, 100)])
    (rd / "decisions.jsonl").write_text(json.dumps({"step": 50, "rule": "item_pickup", "map": 0x0C}) + "\n")
    hints = seg_split.cut_hints(st, tmp_path)
    assert hints and hints[0]["kind"] == "item" and hints[0]["map"] == 0x0C and hints[0]["step"] == 50


def _solved_pieces(doc, goal="to_route2"):
    doc["splits"][goal] = [0x01]
    for key in (f"{goal}@01", f"{goal}@end"):
        st = ss.stat(doc, key)
        st["attempts"] = [att(True, frames=400, run="best")] + [att(True, frames=400)] * 19
        st["n"], st["solves"] = 20, 20
        st["confirmed"] = st["best"] = {"frames": 400, "steps": 10, "run": "best",
                                       "confirmed": True, "rejected": False, "tries": 2}


def _grades_for(doc):
    segs = {s.key: s for s in ss.layout(doc)}
    return [sg.grade_segment(s, ss.stat(doc, s.key), ss.FRAMES_PER_STEP, None, 1e12) for s in segs.values()]


def test_should_rejoin_and_reset(tmp_path):
    doc = ss.empty_doc()
    _solved_pieces(doc)
    pieces = [s for s in ss.layout(doc) if s.goal == "to_route2"]
    grades = _grades_for(doc)
    gmap = {g.key: g for g in grades}
    assert all(gmap[p.key].solved and gmap[p.key].optimized for p in pieces)
    parent_st = ss.stat(doc, "to_route2")
    assert not seg_split.should_rejoin(doc, "to_route2", grades, pieces)   # no probes yet
    parent_st["attempts"] = [att(True, frames=800, rejoin=True)] + [att(True, frames=790, rejoin=True)]
    assert seg_split.should_rejoin(doc, "to_route2", grades, pieces)       # 2 probes within 10% of 800
    parent_st["attempts"].append(att(True, frames=500, rejoin=True))
    parent_st["attempts"].append(att(True, frames=800, rejoin=True))
    assert not seg_split.should_rejoin(doc, "to_route2", grades, pieces)   # last 2 must BOTH be in tolerance
    parent_st["attempts"].append(att(True, frames=800, rejoin=True))
    assert seg_split.should_rejoin(doc, "to_route2", grades, pieces)       # last 2 = [800, 800]
    assert seg_split.reset(doc, ["to_route2"]) == ["to_route2"]
    assert "to_route2" not in doc["splits"] and "to_route2@01" not in doc["stats"]


def test_rejoin_probe_job_tag_and_rate(tmp_path):
    # the parent segment's start is 'deliver_parcel': every earlier goal needs a checkpoint for it to be valid
    root = mkroot(tmp_path, ("bedroom", "potion", "left_house", "first_pokemon", "won_battle",
                             "to_route1", "to_viridian", "oaks_parcel", "deliver_parcel"))
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    _solved_pieces(c.doc)
    ss.save(root, c.doc)                            # next_job reloads the doc inside its txn
    job = None
    for n in range(30):
        j = c.next_job(n)
        if j and j["kind"] == "rejoin_probe":
            job = j
            break
    assert job is not None and "rejoin" in job["tag"] and job["explore_rate"] == 0.0
    assert job["stop"] == ["--stop-at-goal", "to_route2"]
