"""The stall bundle: one runs/stalls/<run>-<reason>-<press>.json per stall episode."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.goals import GOALS, is_unverified  # noqa: E402
from pokeagent.marathon import bundle, rules  # noqa: E402
from pokeagent.marathon.reader import RunView  # noqa: E402


def make_run(tmp_path, name="explore-1-1", tag="marathon-x"):
    d = tmp_path / "runs" / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"tag": tag, "seed": 7, "start": "bedroom", "steps": 99999}))
    return d


def presses(d, spec):
    with open(d / "transitions.jsonl", "a") as f:
        for m, n in spec:
            for i in range(n):
                f.write(json.dumps({"to": [m, i % 17, 0], "button": "A"}) + "\n")


def goals(d, *rows):
    with open(d / "goal_frames.jsonl", "a") as f:
        for g, s in rows:
            f.write(json.dumps({"goal": g, "step": s, "frame": s * 20}) + "\n")


def ladder_upto(d, name, step0=100):
    rows = [(g, step0 + i) for i, g in enumerate(GOALS) if not is_unverified(g)]
    goals(d, *rows[: [g for g, _ in rows].index(name) + 1])


def stalled_view(tmp_path):
    d = make_run(tmp_path)
    goals(d, ("ss_ticket", 100))
    presses(d, [(0x58, 4000)])
    with open(d / "console.log", "a") as f:
        for _ in range(9):
            f.write("thinking: no frontier: patrolling\n")
        f.write("thinking: a rarer thought\n")
    v = RunView(d).refresh()
    r = rules.evaluate(v)
    assert r["status"] == "stalled"
    return d, v, r


def test_bundle_names_the_pending_goal_and_repeated_thinking(tmp_path):
    d, v, r = stalled_view(tmp_path)
    path, created = bundle.write(v, r["reason"], r["hits"])
    assert created and path.name == "explore-1-1-map_dwell-4000.json"
    d_out = json.loads(path.read_text())
    assert d_out["current_goal"] == "to_route5"
    assert d_out["last_goal"] == "ss_ticket" and d_out["last_goal_step"] == 100
    assert d_out["map"] == 0x58 and d_out["reason"] == "map_dwell"
    assert d_out["thinking_top"][0]["text"] == "no frontier: patrolling"
    assert d_out["thinking_top"][0]["count"] == 9
    assert len(d_out["map_sequence"]) == 1 and d_out["map_sequence"][0]["first"] == 1
    assert d_out["tag"] == "marathon-x" and d_out["hits"] == ["map_dwell", "goal_budget"]


def test_bundle_is_once_per_episode_and_a_new_goal_rekeys_it(tmp_path):
    d, v, r = stalled_view(tmp_path)
    p1, c1 = bundle.write(v, r["reason"], r["hits"])
    p2, c2 = bundle.write(v, r["reason"], r["hits"])  # same episode: the existing file is reported
    assert c1 and not c2 and p1 == p2
    goals(d, ("to_route5", 4100))
    presses(d, [(0x58, 3000)])
    v.refresh()
    r = rules.evaluate(v)
    p3, c3 = bundle.write(v, r["reason"], r["hits"])  # a goal landed: a new episode, a new file
    assert c3 and p3 != p1 and len(list((tmp_path / "runs" / "stalls").glob("*.json"))) == 2


def test_bundle_does_not_collide_with_swarm_dossiers(tmp_path):
    d, v, r = stalled_view(tmp_path)
    dossier = tmp_path / "runs" / "stalls" / "explore-1-1.json"
    dossier.parent.mkdir(parents=True, exist_ok=True)
    dossier.write_text(json.dumps({"run": "explore-1-1"}))  # a pokeagent.stalls dossier, kept as is
    path, _ = bundle.write(v, r["reason"], r["hits"])
    assert dossier.read_text() == json.dumps({"run": "explore-1-1"})  # untouched
    again, created = bundle.write(v, r["reason"], r["hits"])
    assert again == path and not created  # the dossier's bare <run>.json was never mistaken for ours


def test_bundle_pending_goal_skips_unverified(tmp_path):
    """Diglett's fixture: ss_anne_2f landed, so the pending goal reads ss_anne_captain."""
    d = make_run(tmp_path)
    ladder_upto(d, "ss_anne_2f")
    presses(d, [(0x3C, 1000)])
    v = RunView(d).refresh()
    assert v.current_goal == "ss_anne_captain" and "rival_ss_anne" not in v.pending_goals
    out = bundle.build(v, "guard_stall", ["guard_stall"])
    assert out["current_goal"] == "ss_anne_captain" and "ss_anne_captain" not in out["next_goals"]


def test_pending_goal_ignores_out_of_order_initial_goal(tmp_path):
    """A to_bill checkpoint run lists to_route22 (an early Route 22 visit) in initial_goals; it must not settle the
    ladder up to index 116 - the agent's next goal is still vermilion_gym_entry."""
    d = make_run(tmp_path)
    prefix = list(GOALS[: GOALS.index("to_bill") + 1])
    meta = json.loads((d / "meta.json").read_text())
    meta["initial_goals"] = prefix + ["to_route22"]
    (d / "meta.json").write_text(json.dumps(meta))
    v = RunView(d).refresh()
    goals(d, *[(g, 100 + i) for i, g in enumerate(GOALS[GOALS.index("to_bill") + 1: GOALS.index("bicycle") + 1])
               if not is_unverified(g)])
    v = RunView(d).refresh()
    assert v.current_goal == "vermilion_gym_entry"
    assert "route22_gate" in v.pending_goals and "to_route22" not in v.pending_goals
