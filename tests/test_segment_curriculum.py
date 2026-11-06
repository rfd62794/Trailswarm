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
            "starter": "squirtle", "explore_rate": 0.0, "box_pace": 8, "budget": 1500, "maps": list(maps), **kw}


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
    assert ss.expected_frames(st) == 1000 + 100 * ss.FRAMES_PER_STEP + ss.FAIL_PENALTY_FRAMES
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
    inp.parent.mkdir(parents=True)
    inp.write_text("{}")
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    doc = ss.empty_doc()
    assert seg_ingest.ingest(root, doc, quiet_s=0) == 1
    st = ss.stat(doc, "potion")
    assert st["best"]["frames"] == 900 and not st["best"]["confirmed"] and st["confirmed"] is None
    assert not (root / "runs/checkpoints/potion.best.state").exists()      # not accepted yet
    assert inp.exists()                                                      # kept for the replay
    mkrun(root, "explore-b", meta(tag="confirm:potion:explore-a"), [{"goal": "potion", "step": 30, "frame": 900}])
    seg_ingest.ingest(root, doc, quiet_s=0)
    assert st["confirmed"]["frames"] == 900 and st["n"] == 1                 # a replay is not an extra attempt
    assert (root / "runs/checkpoints/potion.best.state").read_bytes() == b"END-explore-a"
    assert not inp.exists()


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
    inp.parent.mkdir(parents=True)
    inp.write_text("{}")
    mkrun(root, "explore-a", meta(), [{"goal": "potion", "step": 30, "frame": 900}])
    c = seg_sched.Curriculum(root, log=lambda m: None, quiet_s=0)
    job = c.next_job(0)
    assert job["kind"] == "confirm" and job["seed"] == 5 and job["starter"] == "squirtle"
    assert job["maps_in"] == str(inp) and job["steps"] == 1500 and job["tag"] == "confirm:potion:explore-a"
    assert c.pending_confirm() is None                 # in flight: not issued twice
    assert c.next_job(1)["kind"] != "confirm"


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
def _flaky(n_ok, wander=(0x0C, 0x01, 0x99)):
    return ([att(False, maps=(0x0C, 0x01, 0x0D)) for _ in range(12)] + [att(False, maps=wander) for _ in range(20 - 12 - n_ok)]
            + [att(True) for _ in range(n_ok)])


def test_split_cuts_at_maps_failed_attempts_reached():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = _flaky(2), 20
    assert seg_split.maybe_split(doc) == ["to_route2"]
    assert doc["splits"]["to_route2"] == [0x01, 0x0D]   # first entries along the furthest failed path (0x99 was a one-off)


def test_no_split_above_30_percent_or_before_20_attempts():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = _flaky(7), 20             # 35% solved
    assert seg_split.maybe_split(doc) == []
    st["attempts"], st["n"] = _flaky(2)[:19], 19        # too few attempts
    assert seg_split.maybe_split(doc) == []


def test_unsplittable_segment_retries_later():
    doc = ss.empty_doc()
    st = ss.stat(doc, "to_route2")
    st["attempts"], st["n"] = [att(False, maps=(0x0C,)) for _ in range(20)], 20   # never left the first map
    assert seg_split.maybe_split(doc) == [] and st["split_retry_at"] == 40
    st["n"] = 25
    assert seg_split.maybe_split(doc) == []


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
