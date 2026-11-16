"""Marathon stall rules on fake run dirs: the five observed stalls plus the healthy cases."""
import importlib.util
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.goals import GOALS, is_unverified  # noqa: E402
from pokeagent.marathon import rules  # noqa: E402
from pokeagent.marathon.reader import RunView  # noqa: E402

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _load(name):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(f"tool_{name}", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def make_run(tmp_path, name="explore-1-1", tag="marathon-x", start="bedroom", meta=None):
    d = tmp_path / "runs" / name
    d.mkdir(parents=True)
    m = {"tag": tag, "seed": 7, "start": start, "steps": 99999}
    m.update(meta or {})
    (d / "meta.json").write_text(json.dumps(m))
    return d


def presses(d, spec):
    """spec: [(map, n)] - n presses per map in order; x varies so tiles keep trickling in."""
    with open(d / "transitions.jsonl", "a") as f:
        for m, n in spec:
            for i in range(n):
                f.write(json.dumps({"to": [m, i % 17, 0], "button": "A"}) + "\n")


def goals(d, *rows):
    with open(d / "goal_frames.jsonl", "a") as f:
        for g, s in rows:
            f.write(json.dumps({"goal": g, "step": s, "frame": s * 20}) + "\n")


def ladder_upto(d, name, step0=100):
    """goal_frames for every verified ladder goal through ``name`` (unverified ones never land)."""
    rows = [(g, step0 + i) for i, g in enumerate(GOALS) if not is_unverified(g)]
    goals(d, *rows[: [g for g, _ in rows].index(name) + 1])


def level_gain(d, step, exp):
    with open(d / "levels.jsonl", "a") as f:
        f.write(json.dumps({"step": step, "party": [[25, 20, exp, 50, 50]]}) + "\n")


def thinking(d, lines):
    with open(d / "console.log", "a") as f:
        for ln in lines:
            f.write("thinking: " + ln + "\n")


def stalls(d, n, start_step=845, end_step=4000, map_id=0x3C):
    """n in-run StallGuard escalations, spread between the two presses."""
    with open(d / "console.log", "a") as f:
        for i in range(1, n + 1):
            s = start_step + (end_step - start_step) * (i - 1) // max(n - 1, 1)
            f.write(f"--- step {s}/99999  map={map_id:#06x} pos=(0,0) facing UP\n")
            f.write(f"thinking: STALL #{i} detected here - escalating with 4\n")


def view(d):
    return RunView(d).refresh()


# -- the five observed marathon stalls ----------------------------------------------------------


def test_bills_house_patrol_flags_map_dwell(tmp_path):
    """1: ss_ticket landed, then 4000 patrol presses on Bill's map 0x58, to_route5 pending."""
    d = make_run(tmp_path)
    goals(d, ("ss_ticket", 100))
    presses(d, [(0x58, 4000)])
    thinking(d, ["no frontier: patrolling"] * 3)
    v = view(d)
    r = rules.evaluate(v)
    assert v.current_goal == "to_route5"
    assert r["status"] == "stalled" and r["reason"] == "map_dwell"
    assert r["hits"] == ["map_dwell", "goal_budget"] and "0x58" in r["detail"]


def test_bike_shop_drift_flags_goal_budget(tmp_path):
    """2: 1250 patrolling presses across maps is fine; past the budget it flags, never map_dwell."""
    d = make_run(tmp_path)
    goals(d, ("ss_ticket", 100))
    presses(d, [(0x42, 300), (0x03, 300), (0x42, 300), (0x03, 300), (0x42, 150)])
    r = rules.evaluate(view(d))
    assert r["status"] == "ok"  # 1250 presses since the goal: inside the budget
    presses(d, [(0x03, 300), (0x42, 300), (0x03, 300), (0x42, 400)])
    r = rules.evaluate(view(d))
    assert r["reason"] == "goal_budget" and "to_route5" in r["detail"]
    assert "map_dwell" not in r["hits"] and "oscillation" not in r["hits"]


def test_cerulean_route5_ping_pong_flags_oscillation(tmp_path):
    """3: thousands of presses crossing Cerulean <-> Route 5, no goal."""
    d = make_run(tmp_path)
    goals(d, ("ss_ticket", 100))
    for _ in range(57):  # ~57 map hops in 3200 presses: the pair is crossed >40x per 1500
        presses(d, [(0x03, 28), (0x10, 28)])
    v = view(d)
    r = rules.evaluate(v)
    assert r["reason"] == "oscillation" and r["hits"] == ["oscillation", "goal_budget"]
    assert "0x03" in r["detail"] and "0x10" in r["detail"]


def test_route24_xp_does_not_forgive_outside_a_grind_stage(tmp_path):
    """4: 4500 presses on Route 24 with XP every ~300 presses - a non-grind goal, so it flags."""
    d = make_run(tmp_path)
    goals(d, ("ss_ticket", 100))
    level_gain(d, 100, 1000)
    for s in range(300, 4500, 300):
        presses(d, [(0x23, 300)])
        level_gain(d, 100 + s, 1000 + s)
    v = view(d)
    r = rules.evaluate(v)
    assert v.train_at > 0  # the XP rows landed - and still do not forgive a non-grind stage
    assert r["reason"] == "map_dwell" and r["hits"] == ["map_dwell", "goal_budget"]


def test_digletts_cave_flags_guard_stall(tmp_path):
    """5: 30 STALL escalations from step 845 to 4000 while ss_anne_captain is pending."""
    d = make_run(tmp_path)
    ladder_upto(d, "ss_anne_2f")
    for _ in range(8):  # 3200 presses wandering short map segments: no dwell, no oscillation
        presses(d, [(0x3C, 200), (0x26, 200)])
    stalls(d, 30)
    v = view(d)
    r = rules.evaluate(v)
    assert v.current_goal == "ss_anne_captain"  # rival_ss_anne is unverified: skipped, not pending
    assert r["reason"] == "guard_stall" and r["hits"] == ["guard_stall", "goal_budget"]


# -- the healthy runs it must not touch ----------------------------------------------------------


def test_team_ready_grind_with_xp_is_healthy(tmp_path):
    """A floor stage grinding thousands of presses on one map, gaining XP every ~400: ok."""
    d = make_run(tmp_path)
    ladder_upto(d, "nugget_bridge")  # pending: team_ready (the ladder's hold goal)
    level_gain(d, 200, 1000)
    for s in range(400, 5000, 400):
        presses(d, [(0x23, 400)])
        level_gain(d, 200 + s, 1000 + s)
    v = view(d)
    r = rules.evaluate(v)
    assert v.current_goal == "team_ready" and v.current_goal in rules.GRIND_GOALS
    assert r["status"] == "ok", r


def test_steady_progress_is_ok(tmp_path):
    d = make_run(tmp_path)
    for i, g in enumerate(["potion", "left_house", "first_pokemon", "won_battle", "to_route1"]):
        presses(d, [(0x0C + i, 800)])
        goals(d, (g, 800 * (i + 1)))
    r = rules.evaluate(view(d))
    assert r["status"] == "ok" and r["reason"] == "ok"


def test_held_and_young_runs_are_not_judged(tmp_path):
    d = make_run(tmp_path)
    presses(d, [(0x58, 4000)])  # would stall - but the claude lease wins
    (d / "claude_hold.json").write_text(json.dumps({"until": time.time() + 300}))
    assert rules.evaluate(view(d))["status"] == "held"
    d2 = make_run(tmp_path / "b", name="explore-2-2")
    presses(d2, [(0x58, 100)])
    assert rules.evaluate(view(d2))["status"] == "young"


def test_grind_goals_come_from_the_training_tables():
    """Not a hand list: every TRAIN_LEVEL_BY_GOAL boss floor plus the ladder's own hold."""
    from pokeagent.explorer.training import TRAIN_LEVEL_BY_GOAL
    assert "team_ready" in rules.GRIND_GOALS and "beat_surge" in rules.GRIND_GOALS
    assert set(TRAIN_LEVEL_BY_GOAL) <= set(rules.GRIND_GOALS)
    assert tuple(sorted(rules.GRIND_GOALS, key=GOALS.index)) == rules.GRIND_GOALS


def test_hung_delegates_to_progress_watch(tmp_path):
    """The swarm's own hung rule is reused (injected): a stalled file flags once the clock passes."""
    sw = _load("swarm_watch")
    d = make_run(tmp_path)

    class C:
        t = 0.0

        def __call__(self):
            return self.t

    c = C()
    w = sw.ProgressWatch(tmp_path, 7, since_wall=0, clock=c)
    presses(d, [(0x58, 400)])
    v = view(d)
    assert rules.evaluate(v, hung_check=w.check)["status"] == "ok"
    c.t = 125  # 125s without a new transition
    r = rules.evaluate(v, hung_check=w.check)
    assert r["status"] == "stalled" and r["reason"] == "hung" and "no new transition" in r["detail"]


def test_incremental_refresh_and_torn_lines(tmp_path):
    """refresh() folds only new bytes; a half-written tail waits for the next look."""
    d = make_run(tmp_path)
    goals(d, ("ss_ticket", 50))
    presses(d, [(0x58, 1000)])
    v = view(d)
    assert v.presses == 1000 and rules.evaluate(v)["status"] == "ok"
    presses(d, [(0x58, 1500)])
    with open(d / "transitions.jsonl", "a") as f:  # a torn line: no newline yet
        f.write('{"to": [88, 1, 1]')
    v.refresh()
    assert v.presses == 2500  # the torn line did not count
    with open(d / "transitions.jsonl", "a") as f:
        f.write(', "button": "A"}\n')
    v.refresh()
    assert v.presses == 2501
    r = rules.evaluate(v)
    assert r["reason"] == "map_dwell"
