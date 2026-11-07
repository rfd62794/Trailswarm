"""Segment curriculum: store stats, scheduler shares, daisy-chain starts, confirm gate, auto-split, budgets."""
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import seg_ingest  # noqa: E402
import seg_sched  # noqa: E402
import seg_split  # noqa: E402
import seg_store as ss  # noqa: E402
from pokeagent.segment_names import state_goal  # noqa: E402


def att(solved, frames=1000, steps=100, maps=(0x26,), **kw):
    return {"run": kw.pop("run", "r"), "solved": solved, "frames": frames if solved else 0, "steps": steps, "seed": 1,
            "starter": "squirtle", "explore_rate": 0.0, "box_pace": 8, "budget": 1500, "maps": list(maps), "tagged": True, "outside": 0, **kw}


def mkroot(tmp_path, have=("bedroom", "potion", "left_house", "first_pokemon")):
    for n in have:
        p = tmp_path / ("baselines/bedroom.state" if n == "bedroom" else f"runs/checkpoints/{n}.state")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"s")
    return tmp_path


def fill(doc, key, results):
    st = ss.stat(doc, key)
    st["attempts"] = [att(r) for r in results]
    st["n"] = len(results)
    st["solves"] = sum(results)


def mkrun(root, name, meta, goal_lines=(), moves=(), end=True):
    d = root / "runs" / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "transitions.jsonl").write_text("".join(json.dumps({"to": [m, 0, 0]}) + "\n" for m in moves))
    (d / "goal_frames.jsonl").write_text("".join(json.dumps(g) + "\n" for g in goal_lines))
    if end:
        (d / "end.state").write_bytes(b"END-" + name.encode())
    return d


def mkjob(root, tag, start="bedroom.state", content=b"s", sha=None):
    """What on_start keeps for a normal job: map memory + the exact start-state copy + job.json."""
    d = ss.job_dir(root, tag)
    d.mkdir(parents=True, exist_ok=True)
    (d / "maps.json").write_text("{}")
    (d / start).write_bytes(content)
    (d / "job.json").write_text(json.dumps({"start_name": start, "start_sha": sha or ss.sha256(d / start)}))
    return d


def meta(goal="potion", tag="seg:potion:1-0", **kw):
    return {"start": "baseline", "stop_at_goal": goal, "seed": 5, "starter": "squirtle", "explore_rate": 0.0,
            "box_pace": 8, "steps": 1500, "tag": tag, **kw}


# --- stats ---------------------------------------------------------------------------------------------------
def test_solved_needs_90_percent_over_full_window():
    st = ss.stat(ss.empty_doc(), "potion")
    st["attempts"] = [att(True)] * 10
    assert not ss.is_solved(st)  # too few attempts to call it solved
    st["attempts"] = [att(True)] * 18 + [att(False)] * 2
    assert ss.is_solved(st) and ss.rate(st) == 0.9
    st["attempts"] = [att(True)] * 17 + [att(False)] * 3
    assert not ss.is_solved(st)


def test_expected_frames_charge_failures():
    st = ss.stat(ss.empty_doc(), "potion")
    st["attempts"] = [att(True, frames=1000), att(False, steps=100)]
    assert ss.expected_frames(st) == 1000 + 100 * ss.FRAMES_PER_STEP + ss.PENALTY_FLOOR   # 0.5 x 1000 < the floor
    st["attempts"] = [att(True, frames=10000), att(False, steps=100)]
    assert ss.fail_penalty(st) == 5000   # proportional to the segment's typical solve
    st["attempts"] = [att(False)]
    assert ss.expected_frames(st) is None


def test_state_goal_names():
    assert state_goal("mt_moon_b2f.best") == "mt_moon_b2f"
    assert state_goal("to_route4@3c.best") == "to_route3"
    assert state_goal("potion@end") == ""


def test_best_checkpoint_beats_plain(tmp_path):
    root = mkroot(tmp_path)
    assert ss.ckpt(root, "potion").name == "potion.state"
    (root / "runs/checkpoints/potion.best.state").write_bytes(b"b")
    assert ss.ckpt(root, "potion").name == "potion.best.state"
    assert ss.ckpt(root, "bedroom").name == "bedroom.state"
    assert ss.ckpt(root, "nope") is None


def test_chain_total_sums_accepted_bests():
    doc = ss.empty_doc()
    for g, f, conf in (("potion", 100, True), ("left_house", 200, False)):
        st = ss.stat(doc, g)
        st["best"] = {"frames": f, "steps": 1}
        if conf:
            st["confirmed"] = st["best"]
    c = ss.chain(doc)
    assert c["total"] == 300 and not c["complete"]
    assert c["unconfirmed"] == ["left_house"] and c["missing"][0] == "first_pokemon"


def test_split_layout_chains_sub_segments():
    doc = ss.empty_doc()
    doc["splits"]["left_house"] = [0x25, 0x00]
    segs = [s for s in ss.layout(doc) if s.goal == "left_house"]
    assert [(s.key, s.start, s.end, s.stop_goal, s.stop_map) for s in segs] == [
        ("left_house@25", "potion", "left_house@25", None, 0x25),
        ("left_house@00", "left_house@25", "left_house@00", None, 0x00),
        ("left_house@end", "left_house@00", "left_house", "left_house", None)]


# --- scheduler -----------------------------------------------------------------------------------------------
def test_shares_70_20_10(tmp_path):
    root = mkroot(tmp_path)
    c = seg_sched.Curriculum(root, log=lambda m: None)
    fill(c.doc, "potion", [True] * 20)                       # solved -> polish pool
    fill(c.doc, "left_house", [True] * 10 + [False] * 10)    # unsolved
    fill(c.doc, "first_pokemon", [False] * 20)               # unsolved, weakest
    picks = [c.choose() for _ in range(20)]
    cats = [k for k, _ in picks]
    assert (cats.count("unsolved"), cats.count("frontier"), cats.count("polish")) == (14, 4, 2)
    assert {s.key for k, s in picks if k == "frontier"} == {"won_battle"}   # the segment after the furthest checkpoint
    assert {s.key for k, s in picks if k == "polish"} == {"potion"}
    order = [s.key for k, s in picks if k == "unsolved"]
    assert order.index("first_pokemon") < order.index("left_house")   # weakest first (0% before 50%)
    assert order.count("first_pokemon") > order.count("left_house")


def test_shares_renormalise_when_a_group_is_empty(tmp_path):
    root = mkroot(tmp_path, ("bedroom", "potion"))
    c = seg_sched.Curriculum(root, log=lambda m: None)
    cats = [c.choose()[0] for _ in range(9)]
    assert set(cats) == {"unsolved", "frontier"} and cats.count("frontier") == 2   # 70:20 renormalised over 9 picks


def test_segment_without_start_checkpoint_is_not_scheduled(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    c = seg_sched.Curriculum(root, log=lambda m: None)
    assert {s.key for _, s in (c.choose() for _ in range(5))} == {"potion"}


def test_budget_is_3x_best_clamped():
    st = ss.stat(ss.empty_doc(), "x")
    assert seg_sched.budget(st) == seg_sched.BUDGET_DEFAULT
    for steps, want in ((100, 1500), (700, 2100), (5000, 6000)):
        st["best"] = {"steps": steps, "frames": 1}
        assert seg_sched.budget(st) == want


def test_daisy_chain_starts_from_previous_best_checkpoint(tmp_path):
    root = mkroot(tmp_path)
    (root / "runs/checkpoints/left_house.best.state").write_bytes(b"best")
    c = seg_sched.Curriculum(root, log=lambda m: None)
    seg = next(s for s in ss.layout(c.doc) if s.key == "first_pokemon")
    job = c._job(seg, "unsolved", 0, ss.ckpt(root, seg.start), ss.stat(c.doc, "first_pokemon"))
    assert job["start"].endswith("left_house.best.state")
    assert job["stop"] == ["--stop-at-goal", "first_pokemon"] and job["tag"].startswith("seg:first_pokemon:")


def test_next_job_records_the_slot_share(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    job = c.next_job(0)
    assert job["key"] == "potion" and job["steps"] == seg_sched.BUDGET_DEFAULT
    assert ss.load(root)["stats"]["potion"]["jobs"] == 1


# --- confirm gate --------------------------------------------------------------------------------------------
def test_new_best_waits_for_a_replay(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    inp = ss.input_path(root, "seg:potion:1-0")
    mkjob(root, "seg:potion:1-0")
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    doc = ss.empty_doc()
    assert seg_ingest.ingest(root, doc, quiet_s=0) == 1
    st = ss.stat(doc, "potion")
    assert st["best"]["frames"] == 900 and not st["best"]["confirmed"] and st["confirmed"] is None
    assert st["best"]["start"].endswith("bedroom.state") and st["best"]["start_sha"] == ss.sha256(st["best"]["start"])
    assert not (root / "runs/explore-a/end.state").exists()                  # end.state kept only via the candidate copy
    assert Path(st["best"]["state"]).read_bytes() == b"END-explore-a"
    assert not (root / "runs/checkpoints/potion.best.state").exists()      # not accepted yet
    assert inp.exists()                                                      # kept for the replay
    mkrun(root, "explore-b", meta(tag="confirm:potion:explore-a"), [{"goal": "potion", "step": 30, "frame": 900}])
    seg_ingest.ingest(root, doc, quiet_s=0)
    assert st["confirmed"]["frames"] == 900 and st["n"] == 1                 # a replay is not an extra attempt
    assert (root / "runs/checkpoints/potion.best.state").read_bytes() == b"END-explore-a"
    assert not inp.exists() and not inp.parent.exists() and not Path(st["confirmed"]["state"] or "x").exists()


def test_failed_replay_rejects_and_reverts(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    doc = ss.empty_doc()
    st = ss.stat(doc, "potion")
    st["best"] = st["confirmed"] = {"frames": 1200, "steps": 40, "run": "old", "confirmed": True, "input": None}
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    seg_ingest.ingest(root, doc, quiet_s=0)
    assert st["best"]["frames"] == 900
    mkrun(root, "explore-b", meta(tag="confirm:potion:explore-a"), [], moves=(0x26,) * 1500)   # the replay used its budget, no solve
    seg_ingest.ingest(root, doc, quiet_s=0)
    assert st["best"]["frames"] == 1200 and st["confirmed"]["frames"] == 1200
    assert not (root / "runs/checkpoints/potion.best.state").exists()


def test_slower_solve_is_not_a_candidate(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    doc = ss.empty_doc()
    ss.stat(doc, "potion")["best"] = {"frames": 500, "steps": 9, "run": "old", "confirmed": False}
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    seg_ingest.ingest(root, doc, quiet_s=0)
    assert ss.stat(doc, "potion")["best"]["run"] == "old"


def test_pending_confirm_job_replays_seed_and_memory(tmp_path):
    root = mkroot(tmp_path)
    inp = ss.input_path(root, "seg:potion:1-0")
    kept = mkjob(root, "seg:potion:1-0") / "bedroom.state"
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    (root / "baselines/bedroom.state").write_bytes(b"CHANGED")   # the live checkpoint drifted after the candidate ran
    job = c.next_job(0)
    assert job["kind"] == "confirm" and job["seed"] == 5 and job["starter"] == "squirtle"
    assert job["start"] == str(kept)                            # replays the kept copy, never ckpt() at confirm time
    assert job["maps_in"] == str(inp) and job["steps"] == 1500 and job["tag"] == "confirm:potion:explore-a"
    assert c.pending_confirm() is None                 # in flight: not issued twice
    assert c.next_job(1)["kind"] != "confirm"


def test_replay_refused_when_kept_start_state_changed(tmp_path):
    root = mkroot(tmp_path)
    d = mkjob(root, "seg:potion:1-0")
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    c.refresh()
    assert c.pending_confirm() is not None
    (d / "bedroom.state").write_bytes(b"tampered")             # sha256 no longer matches the record
    assert c.pending_confirm() is None


def test_candidate_with_outside_input_is_not_a_best(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mkjob(root, "seg:potion:1-0")
    d = mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    (d / "transitions.jsonl").write_text(json.dumps({"to": [1, 0, 0], "source": "human"}) + "\n")
    doc = ss.empty_doc()
    seg_ingest.ingest(root, doc, quiet_s=0)
    st = ss.stat(doc, "potion")
    assert st["solves"] == 1 and st["best"] is None


def test_inconclusive_replay_is_retried_not_rejected(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mkjob(root, "seg:potion:1-0")
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    doc = ss.empty_doc()
    seg_ingest.ingest(root, doc, quiet_s=0)
    st = ss.stat(doc, "potion")
    st["best"]["tries"] = 1
    d = mkrun(root, "explore-b", meta(tag="confirm:potion:explore-a"), [])
    (d / "transitions.jsonl").write_text("".join(json.dumps({"to": [1, 0, 0], "source": "claude"}) + "\n" for _ in range(1500)))
    seg_ingest.ingest(root, doc, quiet_s=0)
    assert not st["best"]["rejected"] and st["best"]["tries"] == 0


def test_frames_per_press_calibrates_from_goal_frames(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    doc = ss.empty_doc()
    assert ss.fps(doc) == ss.FRAMES_PER_STEP                     # no evidence yet
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 1000, "frame": 20000},
                                      {"goal": "left_house", "step": 3000, "frame": 40000}])
    seg_ingest.ingest(root, doc, quiet_s=0)
    assert doc["calib"] == {"frames": 40000, "steps": 3000} and ss.fps(doc) == 40000 / 3000


def test_polish_goes_to_the_biggest_potential_gain(tmp_path):
    root = mkroot(tmp_path)
    c = seg_sched.Curriculum(root, log=lambda m: None)
    for key in ("potion", "left_house"):
        st = ss.stat(c.doc, key)
        st["attempts"] = [att(True, frames=1000) for _ in range(20)]
        st["best"] = {"frames": 1000, "steps": 10}
    ss.stat(c.doc, "left_house")["attempts"][0] = att(True, frames=9000)        # slow on average, best still 1000
    assert [s.key for s in c.groups()["polish"]][0] == "left_house"
    assert ss.potential_gain(ss.stat(c.doc, "potion")) == 0


def test_running_agents_are_not_ingested(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mkrun(root, "explore-a", meta(), [], moves=(0x26,) * 1500)
    doc = ss.empty_doc()
    assert seg_ingest.ingest(root, doc, quiet_s=3600) == 0 and doc["ingested"] == []
    assert seg_ingest.ingest(root, doc, {"seg:potion:1-0"}, quiet_s=3600) == 1   # its job finished: count it


def test_old_untagged_segment_runs_count_for_their_goal(tmp_path):
    root = mkroot(tmp_path)
    mkrun(root, "explore-a", {"start": "potion", "stop_at_goal": "left_house"}, [{"goal": "left_house", "step": 9, "frame": 700}])
    mkrun(root, "explore-b", {"start": "baseline", "stop_at_goal": "left_house"}, [])   # a full run: not a segment attempt
    doc = ss.empty_doc()
    assert seg_ingest.ingest(root, doc, quiet_s=0) == 1
    assert ss.stat(doc, "left_house")["solves"] == 1


# --- auto-split ----------------------------------------------------------------------------------------------
def _flaky(n_ok, wander=(0x0C, 0x01, 0x99), **kw):
    return ([att(False, maps=(0x0C, 0x01, 0x0D), **kw) for _ in range(12)]
            + [att(False, maps=wander, **kw) for _ in range(20 - 12 - n_ok)] + [att(True) for _ in range(n_ok)])


def test_split_cuts_at_maps_failed_attempts_reached():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = _flaky(2), 20
    assert seg_split.maybe_split(doc) == ["to_route2"]
    assert doc["splits"]["to_route2"] == [0x01, 0x0D]   # first entries along the furthest failed path (0x99 was a one-off)


def test_split_ignores_untagged_and_estimated_attempts():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = _flaky(2, tagged=False), 20
    assert seg_split.maybe_split(doc) == [] and st["split_retry_at"] == 40
    st["attempts"], st["n"] = _flaky(2, est=True), 40
    assert seg_split.maybe_split(doc) == []


def test_split_rejects_start_map_and_maps_from_earlier_segments():
    doc = ss.empty_doc()
    ss.stat(doc, "potion")["attempts"] = [att(True, maps=(0x26, 0x25, 0x00))]    # an earlier segment walked 0x25 and 0x00
    st = ss.stat(doc, "left_house")
    st["attempts"] = [att(False, maps=(0x26, 0x25, 0x00, 0x0C, 0x26, 0x0D)) for _ in range(20)]
    st["n"] = 20
    assert seg_split.maybe_split(doc) == ["left_house"]
    assert doc["splits"]["left_house"] == [0x0C, 0x0D]     # not 0x26 (start map), not 0x25/0x00 (earlier segment's)


def test_split_needs_two_attempts_to_reach_a_map():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"] = [att(False, maps=(0x0C,)) for _ in range(19)] + [att(False, maps=(0x0C, 0x01))]   # only ONE reached 0x01
    st["n"] = 20
    assert seg_split.maybe_split(doc) == [] and "to_route2" not in doc["splits"]


def test_no_split_above_30_percent_or_before_20_attempts():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = _flaky(7), 20             # 35% solved
    assert seg_split.maybe_split(doc) == []
    st["attempts"], st["n"] = _flaky(2)[:19], 19        # too few attempts
    assert seg_split.maybe_split(doc) == []


def test_reset_splits_drops_pieces_and_keeps_parent_history():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = _flaky(2), 20
    seg_split.maybe_split(doc)
    ss.stat(doc, "to_route2@01")
    assert seg_split.reset(doc) == ["to_route2"]
    assert doc["splits"] == {} and "to_route2@01" not in doc["stats"] and st["n"] == 20


# --- janitor -------------------------------------------------------------------------------------------------
def _age(path, t=1):
    import os
    for p in [path, *path.rglob("*")]:
        os.utime(p, (t, t))


def test_janitor_removes_stale_unreferenced_job_dirs_only(tmp_path):
    import os

    import seg_janitor
    root = mkroot(tmp_path)
    old, held, fresh, busy = (mkjob(root, t) for t in ("seg:a:1-0", "seg:b:1-1", "seg:c:1-2", "seg:d:1-3"))
    cand = root / "runs/segments/states/x.cand.state"
    cand.parent.mkdir(parents=True)
    cand.write_bytes(b"c")
    for p in (old, held, busy):
        _age(p)
    os.utime(cand, (1, 1))
    os.utime(busy / "maps.json", None)                       # an old dir whose newest FILE is fresh: a running job
    doc = ss.empty_doc()
    ss.stat(doc, "b")["best"] = {"input": str(held / "maps.json"), "frames": 1}
    now = os.path.getmtime(fresh / "maps.json") + 1
    would = seg_janitor.sweep(root, doc, now=now, dry_run=True)
    assert set(would) == {old.name, "x.cand.state"} and old.exists() and cand.exists()   # dry run deletes nothing
    gone = seg_janitor.sweep(root, doc, now=now)
    assert set(gone) == {old.name, "x.cand.state"}
    assert held.exists() and fresh.exists() and busy.exists() and not old.exists()


def test_remove_tree_refuses_paths_outside_runs_segments(tmp_path):
    root = mkroot(tmp_path)
    outside = tmp_path / "keep"
    outside.mkdir()
    logs = []
    assert ss.remove_tree(root, outside, logs.append) is False
    assert outside.exists() and "refusing" in logs[0]
    assert ss.remove_tree(root, root / "runs" / "segments", logs.append) is False     # the base itself is not a kept dir


# --- campaign gating ------------------------------------------------------------------------------------------
def _ladder():
    from pokeagent import campaign
    ids = campaign.goal_ids()
    gated = next(g["id"] for g in campaign.load_campaign() if g.get("needs") and g["detector"] != "unverified")
    unverified = next(g["id"] for g in campaign.load_campaign()[:ids.index(gated)] if g["detector"] == "unverified")
    return campaign, ids, gated, unverified


def test_layout_skips_gated_and_unverified_goals_and_bridges_the_gap():
    campaign, ids, gated, unverified = _ladder()
    keys = [s.key for s in ss.layout(ss.empty_doc())]
    assert gated not in keys and unverified not in keys and keys == [g for g in ids if campaign.selectable(g)]
    nxt = ids[ids.index(unverified) + 1]
    seg = next(s for s in ss.layout(ss.empty_doc()) if s.key == nxt)
    assert seg.start == [g for g in keys if ids.index(g) < ids.index(unverified)][-1]    # starts from the last selectable one


def test_scheduler_never_picks_gated_or_unverified_goals(tmp_path):
    campaign, ids, gated, unverified = _ladder()
    root = mkroot(tmp_path, ("bedroom", *ids))             # every checkpoint exists, so only gating can exclude a goal
    c = seg_sched.Curriculum(root, log=lambda m: None)
    picked = {s.key for _ in range(120) if (p := c.choose()) for s in [p[1]]}
    assert picked and not picked & {gated, unverified}
    assert not {s.key for g in c.groups().values() for s in g} & {gated, unverified}


def test_gated_and_unverified_goals_are_never_split(tmp_path):
    campaign, ids, gated, unverified = _ladder()
    doc = ss.empty_doc()
    for g in (gated, unverified):
        st = ss.stat(doc, g)
        st["attempts"], st["n"] = _flaky(2), 20
    assert seg_split.maybe_split(doc) == [] and doc["splits"] == {}


def test_capability_unlocks_a_gated_goal(monkeypatch):
    campaign, ids, gated, unverified = _ladder()
    monkeypatch.setenv("POKEAGENT_CAPS", ",".join(campaign.goal_spec(gated)["needs"]))
    assert gated in [s.key for s in ss.layout(ss.empty_doc())]


# --- concurrent supervisors / handoff ---------------------------------------------------------------------------
def test_two_supervisors_do_not_clobber_each_others_ingest(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    a = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    b = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)      # both loaded the empty doc
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    a.refresh()                                                          # A ingests and saves
    mkrun(root, "explore-b", meta(tag="seg:potion:2-0"), [{"goal": "potion", "step": 30, "frame": 800}])
    b.refresh()                                                          # B started from a stale doc, must re-read first
    doc = ss.load(root)
    assert ss.stat(doc, "potion")["n"] == 2 and set(doc["ingested"]) == {"explore-a", "explore-b"}


def test_stale_lock_is_broken_and_live_lock_times_out(tmp_path, monkeypatch):
    import os
    root = mkroot(tmp_path)
    lock = root / "runs" / "segments.lock"
    lock.write_text("")
    os.utime(lock, (1, 1))
    with ss.locked(root):
        pass                                                             # stale lock taken over
    lock.write_text("")
    monkeypatch.setattr(ss, "LOCK_WAIT_S", 0.2)
    try:
        with ss.locked(root):
            raise AssertionError("should not get the lock")
    except TimeoutError:
        pass


def test_adopted_replay_is_not_issued_twice(tmp_path):
    root = mkroot(tmp_path)
    mkjob(root, "seg:potion:1-0")
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    c.refresh()
    assert c.pending_confirm() is not None
    c.adopted({"job": {"kind": "confirm", "key": "potion"}})            # the old supervisor's replay is still running
    assert c.pending_confirm() is None


def test_on_start_refuses_a_missing_start_state(tmp_path):
    root = mkroot(tmp_path)
    c = seg_sched.Curriculum(root, log=lambda m: None)
    own = tmp_path / "own.json"
    own.write_text("{}")
    for kind in ("unsolved", "confirm"):
        cfg = {"own": own, "job": {"kind": kind, "tag": "seg:x:1", "start": str(tmp_path / "gone.state")}}
        try:
            c.on_start(cfg)
            raise AssertionError("expected FileNotFoundError")
        except FileNotFoundError:
            pass


def test_sub_segment_attempts_are_ingested_by_tag(tmp_path):
    root = mkroot(tmp_path, ("bedroom", "potion"))
    doc = ss.empty_doc()
    doc["splits"]["left_house"] = [0x00]
    mkrun(root, "explore-a", meta("left_house", "seg:left_house@00:1-3", start="potion", stop_at_goal=None, stop_at_map=0),
          [{"goal": "map:0x00", "step": 9, "frame": 400}])
    assert seg_ingest.ingest(root, doc, quiet_s=0) == 1
    assert ss.stat(doc, "left_house@00")["best"]["frames"] == 400
    assert (root / "runs/checkpoints/left_house@00.state").exists()   # the next sub-segment's start


# --- supervisor wiring (fake launcher) -----------------------------------------------------------------------
def test_supervisor_runs_curriculum_jobs_with_fake_launcher(tmp_path):
    import swarm_continuous as sc
    root = mkroot(tmp_path, ("bedroom",))
    shared = root / "maps.json"
    shared.write_text('{"v": 0}')
    plan = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    launched, t = [], [0.0]

    class Proc:
        rc = None

        def poll(self):
            return self.rc

        def kill(self):
            self.rc = -9

    def launch(cfg):
        launched.append(cfg)
        cfg["own"].write_text("{\"v\": 1}")   # the agent saved something
        return Proc()

    sup = sc.Supervisor(root, shared, 1, launch, lambda s, o: None, lambda: 9, steps=400, plan=plan,
                        clock=lambda: t[0], sleep=lambda s: None, log=lambda m: None, stop_file=root / "stop")
    sup.tick()
    cfg = launched[0]
    assert cfg["segment"] == "potion" and cfg["steps"] == seg_sched.BUDGET_DEFAULT and cfg["job"]["stop"] == ["--stop-at-goal", "potion"]
    assert ss.input_path(root, cfg["job"]["tag"]).exists()          # starting memory kept for a possible replay
    # the agent solved it: its run folder exists; finishing the slot ingests it and starts the replay
    mkrun(root, "explore-a", meta(tag=cfg["job"]["tag"]), [{"goal": "potion", "step": 30, "frame": 900}])
    t[0] += 100
    sup.slots[0].handle.rc = 0
    sup.tick()
    assert plan.doc["stats"]["potion"]["best"]["frames"] == 900
    assert launched[1]["job"]["kind"] == "confirm" and launched[1]["seed"] == 5
    assert launched[1]["job"]["maps_in"].endswith(".json")
    assert launched[1]["job"]["start"] == cfg["job"]["start"] and "inputs" in cfg["job"]["start"]   # the kept copy


def test_launcher_job_args_are_state_stop_and_tag():
    import swarm
    job = {"start": "x/a.best.state", "stop": ["--stop-at-map", "60"], "tag": "seg:k:1"}
    assert swarm.job_args(job) == ["--state", "x/a.best.state", "--stop-at-map", "60", "--tag", "seg:k:1"]


def test_killed_run_is_not_a_failed_attempt(tmp_path):
    root = mkroot(tmp_path, ("bedroom",))
    mkrun(root, "explore-a", meta(), [], moves=(0x26,) * 50)          # budget 1500, only 50 presses: killed
    mkrun(root, "explore-b", meta(), [], moves=(0x26,) * 1400)         # used its budget: a real failure
    doc = ss.empty_doc()
    assert seg_ingest.ingest(root, doc, quiet_s=0) == 1
    assert ss.stat(doc, "potion")["n"] == 1 and set(doc["ingested"]) == {"explore-a", "explore-b"}


def test_held_lock_never_crashes_the_supervisor_path(tmp_path, monkeypatch):
    root = mkroot(tmp_path, ("bedroom",))
    logs = []
    c = seg_sched.Curriculum(root, log=logs.append, quiet_s=0)
    (root / "runs" / "segments.lock").write_text("")          # another supervisor holds it, fresh (not stale)
    monkeypatch.setattr(ss, "LOCK_WAIT_S", 0.1)
    cfg = c.configure({"slot": 0, "steps": 400, "segment": None}, 0)       # no raise: a plain agent this slot
    assert "job" not in cfg and cfg["steps"] == 400
    c.configure({"slot": 0, "steps": 400, "segment": None}, 1)
    job = {"key": "potion", "kind": "unsolved", "tag": "seg:potion:1-0"}
    c.on_finish({"job": job}, 0)                                          # no raise either
    assert sum("skipped, will retry" in m for m in logs) == 1             # logged once per episode
    (root / "runs" / "segments.lock").unlink()
    assert c.configure({"slot": 0, "steps": 400, "segment": None}, 2)["job"]["key"] == "potion"   # recovered
    c.on_finish({"job": job}, 0)


# --- out-of-order checkpoints (live incident: bike_shop.state made `bicycle` the frontier) ----------------------------
def _chain_root(tmp_path, upto):
    """Checkpoints for the first `upto` selectable goals (a legacy contiguous chain) plus the stray bike_shop.state."""
    order = ss.selectable_goals()
    assert "bike_shop" in order and "bicycle" in order and upto < order.index("bike_shop") - 3
    root = mkroot(tmp_path, ("bedroom", *order[:upto], "bike_shop"))
    return root, order


def test_stray_bike_shop_checkpoint_does_not_become_the_frontier(tmp_path):
    root, order = _chain_root(tmp_path, 20)
    c = seg_sched.Curriculum(root, log=lambda m: None)
    groups = c.groups()
    assert [s.key for s in groups["frontier"]] == [order[20]]            # the earliest goal still missing
    picked = {s.key for _ in range(200) if (p := c.choose()) for s in [p[1]]}
    assert picked and not picked & {"bicycle", "bike_shop", "bike_voucher"}
    assert all(ss.ckpt_valid(root, s.start) for g in groups.values() for s in g)


def test_checkpoint_with_sidecar_missing_earlier_goals_is_rejected(tmp_path):
    from pokeagent import checkpoint_goals as cg
    root, order = _chain_root(tmp_path, 20)
    state = root / "runs/checkpoints/bike_shop.state"
    cg.write_completed(state, ["potion", "bike_shop"])                    # it only completed two goals
    assert not ss.ckpt_valid(root, "bike_shop")
    cg.write_completed(state, order[: order.index("bike_shop") + 1])      # now it really did everything before it
    assert ss.ckpt_valid(root, "bike_shop")


def test_legacy_chain_without_gap_is_valid_and_a_gap_is_not(tmp_path):
    root, order = _chain_root(tmp_path, 20)
    assert ss.ckpt_valid(root, order[19]) and not ss.ckpt_valid(root, "bike_shop")
    (root / "runs/checkpoints" / f"{order[5]}.state").unlink()           # punch a hole in the chain
    assert not ss.ckpt_valid(root, order[19])


def test_sub_segment_checkpoint_needs_only_goals_before_its_parent(tmp_path):
    from pokeagent import checkpoint_goals as cg
    order = ss.selectable_goals()
    g = order[3]
    assert cg.required(f"{g}@25", order) == list(order[:3]) and cg.required(g, order) == list(order[:4])


def test_end_state_sidecar_travels_with_the_checkpoint(tmp_path):
    from pokeagent import checkpoint_goals as cg
    root = mkroot(tmp_path, ("bedroom",))
    mkjob(root, "seg:potion:1-0")
    d = mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    cg.write_completed(d / "end.state", ["potion"])
    doc = ss.empty_doc()
    seg_ingest.ingest(root, doc, quiet_s=0)
    assert cg.read_completed(root / "runs/checkpoints/potion.state") == {"potion"}
    assert cg.read_completed(Path(ss.stat(doc, "potion")["best"]["state"])) == {"potion"}
    assert not cg.sidecar(d / "end.state").exists()


def test_completed_goals_uses_detectors_and_assumed_start_goals():
    from pokeagent import checkpoint_goals as cg
    assert cg.completed_goals({"b": True, "c": False}, {"a"}, ["a", "b", "c"]) == ["a", "b"]
