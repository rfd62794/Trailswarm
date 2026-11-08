"""``pokeagent review run``: the event timeline, loops, rules, end reasons and exit-code data."""
import json
import shutil
from pathlib import Path

from pokeagent.review import load, timeline
from pokeagent.review.loops import BREAK_LOOP_ROWS, find_loops

FIX = Path(__file__).resolve().parent / "fixtures" / "review"
RUNS = FIX / "runs"
RUN_OK = "explore-20261107-150000-1001"
RUN_OK_B = "explore-20261107-150100-1006"
RUN_STALL = "explore-20261107-151000-1002"
RUN_ALREADY = "explore-20261107-152000-1003"
RUN_BLACKOUT = "explore-20261107-153000-1004"
RUN_CRASH = "explore-20261107-154000-1005"


def summary(name, runs=RUNS, **kw):
    return timeline.summarise(load.load_run(runs / name), **kw)


def copy_runs(tmp_path):
    dst = tmp_path / "runs"
    shutil.copytree(RUNS, dst)
    return dst


def test_run_ok_events_and_header():
    s = summary(RUN_OK)
    h = s["header"]
    assert h["segment"]["tag"] == "seg:gyarados:1-1" and h["segment"]["stop_at_goal"] == "gyarados"
    assert (h["start"], h["starter"], h["seed"]) == ("nugget_bridge", "bulbasaur", 42)
    assert (h["steps"], h["budget"]) == (35, 60)
    assert h["presses_by_source"] == {"agent": 34, "claude": 1}
    assert h["frames"] == 420
    kinds = [e["kind"] for e in s["events"]]
    bounce = next(e for e in s["events"] if e["kind"] == "map_bounce")
    assert (bounce["step"], bounce["map_a"], bounce["map_b"], bounce["count"]) == (9, 35, 36, 1)
    warp = next(e for e in s["events"] if e["kind"] == "map")
    assert (warp["step"], warp["from"], warp["to"]) == (15, 35, 37)
    battles = [e for e in s["events"] if e["kind"] == "battle"]
    assert len(battles) == 2
    trainer, wild = battles
    assert (trainer["battle_kind"], trainer["outcome"], trainer["enemy_species"]) == (2, "trainer_win", 130)
    assert (trainer["hp_delta"], trainer["turns"]) == (3, 2)   # hp before 23 - after 20; positive = lost
    assert (wild["battle_kind"], wild["hp_delta"]) == (1, 5)
    heal = next(e for e in s["events"] if e["kind"] == "heal")
    buy = next(e for e in s["events"] if e["kind"] == "buy")
    assert (heal["step"], heal["presses"], heal["rule"]) == (26, 3, "heal_use")
    assert (buy["step"], buy["presses"], buy["rule"]) == (29, 2, "restock_buy")
    goal = next(e for e in s["events"] if e["kind"] == "goal")
    assert (goal["goal"], goal["step"], goal["frame"]) == ("gyarados", 32, 420)
    levels = [e for e in s["events"] if e["kind"] == "level"]
    assert levels[0]["changes"] == [{"species": 133, "level_from": 9, "level_to": 10, "exp_gain": 162}]
    assert levels[1]["changes"] == [{"species": 133, "level_from": 10, "level_to": 10, "exp_gain": 200}]
    assert any(e["kind"] == "after_victory" for e in s["events"])
    assert "stall" not in kinds and "loop" not in kinds


def test_goal_firsts_from_milestones_when_goal_frames_absent(tmp_path):
    runs = copy_runs(tmp_path)
    (runs / RUN_OK / "goal_frames.jsonl").unlink()
    s = summary(RUN_OK, runs)
    goal = next(e for e in s["events"] if e["kind"] == "goal")
    assert (goal["goal"], goal["step"], goal["frame"]) == ("gyarados", 32, None)
    assert s["end"]["reason"] == "solved"


def test_rules_top_and_unclassified():
    s = summary(RUN_OK)
    rules = s["rules"]
    assert rules[0]["rule"] == "frontier" and rules[0]["presses"] == 23
    assert [r["rule"] for r in rules] == ["frontier", "battle_fight", "heal_use", "restock_buy"]
    assert rules[1]["behaviour"] == "battle" and rules[1]["share"] == 7 / 35
    # frontier is over 5% of presses and battle_fight is not heal/buy-adjacent: neither is a gap
    assert s["unclassified_rules"] == []


def test_blocked_loop_episode_and_break():
    s = summary(RUN_STALL)
    assert s["loops"] == [{"kind": "blocked_loop", "step": 21, "end_step": 60, "count": 1,
                           "total_presses": 40, "max_presses": 40, "long": True,
                           "key": {"button": "UP", "map": 35, "x": 10, "y": 8}, "rule": "frontier"}]
    assert s["long_loops"] == 1
    loop_event = next(e for e in s["events"] if e["kind"] == "loop")
    assert (loop_event["loop_kind"], loop_event["presses"]) == ("blocked_loop", 40)
    stall = next(e for e in s["events"] if e["kind"] == "stall")
    assert stall["likely_cause"].startswith("blocked by a learned wall")
    assert stall["signature_key"] == "35|frontier|frontier|UP|blocked|False"
    assert s["end"]["reason"] == "stalled"
    assert s["breaks"] == [{"kind": "blocked_loop", "step": 21, "presses": 40}]


def test_already_out_episode_under_break_rows_is_clean():
    s = summary(RUN_ALREADY)
    assert len(s["loops"]) == 1   # the 5-row blocked repeat (steps 3-7) is NOT an episode
    ep = s["loops"][0]
    assert (ep["kind"], ep["step"], ep["total_presses"], ep["rule"]) == ("already_out", 10, 12, "bring_out")
    assert ep["key"] == {"button": "B", "text": "bulbasaur is already out!"}
    assert s["end"]["reason"] == "solved"
    assert s["breaks"] == []


def test_blackout_event_and_break():
    s = summary(RUN_BLACKOUT)
    ev = next(e for e in s["events"] if e["kind"] == "blackout")
    assert (ev["step"], ev["end_map"], ev["enemy_species"], ev["hp_delta"]) == (8, 5, 19, 20)
    assert s["breaks"] == [{"kind": "blackout", "step": 8, "end_map": 5}]


def test_crash_seam_files():
    s = summary(RUN_CRASH)
    assert s["end"]["reason"] == "crashed"
    assert s["breaks"] == [{"kind": "crashed"}]


def test_end_reason_step_budget(tmp_path):
    runs = copy_runs(tmp_path)
    meta = json.loads((runs / RUN_OK_B / "meta.json").read_text())
    meta["steps"] = 12
    (runs / RUN_OK_B / "meta.json").write_text(json.dumps(meta))
    assert summary(RUN_OK_B, runs)["end"]["reason"] == "step_budget"


def test_end_reason_ended_early():
    s = summary(RUN_OK_B)
    assert s["end"]["reason"] == "ended_early"
    assert (s["end"]["last_step"], s["end"]["position"]) == (12, [35, 9, 27])


def test_stall_only_is_not_a_break(tmp_path):
    runs = copy_runs(tmp_path)
    dossier = json.loads((runs / "stalls" / f"{RUN_STALL}.json").read_text())
    dossier["run"] = RUN_OK_B
    (runs / "stalls" / f"{RUN_OK_B}.json").write_text(json.dumps(dossier))
    s = summary(RUN_OK_B, runs)
    assert s["end"]["reason"] == "stalled"
    assert s["breaks"] == []          # a stall is a result, not a break


def test_corrupt_line_skipped_and_counted(tmp_path):
    runs = copy_runs(tmp_path)
    p = runs / RUN_OK / "decisions.jsonl"
    p.write_text(p.read_text() + "this is not json {{{\n")
    s = summary(RUN_OK, runs)
    assert s["skipped_rows"] == {"decisions.jsonl": 1}
    assert s["header"]["steps"] == 35  # press count unaffected


def test_find_loops_boundary_at_min_rows():
    row = {"step": 0, "from": [1, 1, 1], "button": "UP", "to": [1, 1, 1],
           "moved": False, "textbox": "none", "text": ""}
    five = [dict(row, step=i) for i in range(5)]
    six = [dict(row, step=i) for i in range(6)]
    assert find_loops(five) == []
    assert len(find_loops(six)) == 1


def test_break_loop_rows_threshold():
    assert BREAK_LOOP_ROWS == 30
