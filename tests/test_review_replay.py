"""``pokeagent review replay``: compare_streams, replay_command, locate_start_state, run_replay."""
import json
from pathlib import Path

from pokeagent.review import replay

FIX = Path(__file__).resolve().parent / "fixtures" / "review"
RUNS = FIX / "runs"
RUN_OK = "explore-20261107-150000-1001"       # tag seg:gyarados:1-1 -> has a kept inputs copy
RUN_STALL = "explore-20261107-151000-1002"    # tag seg:gyarados:1-2 -> no kept copy


def row(step, **kw):
    r = {"step": step, "button": "UP", "map": 35, "x": 10, "y": 20 - step,
         "outcome": "moved", "rule": "frontier", "behaviour": "frontier"}
    r.update(kw)
    return r


def test_compare_streams_identical():
    a = [row(i) for i in range(1, 6)]
    assert replay.compare_streams(a, list(a), 5) is None
    assert replay.compare_streams(a, a + [row(9)], 5) is None     # first n rows identical


def test_compare_streams_first_divergence():
    a = [row(i) for i in range(1, 6)]
    b = [row(i) for i in range(1, 6)]
    b[2]["button"] = "LEFT"
    b[2]["rule"] = "menu_back_out"
    d = replay.compare_streams(a, b, 5)
    assert d.step == 3 and d.field == "button" and d.agreed_steps == 2
    assert (d.rule_a, d.rule_b) == ("frontier", "menu_back_out")
    b[2]["button"], b[2]["map"] = "UP", 99
    d = replay.compare_streams(a, b, 5)
    assert d.field == "map"


def test_compare_streams_length_mismatch_and_extra_keys():
    a = [row(i) for i in range(1, 6)]
    d = replay.compare_streams(a, a[:3], 5)
    assert d.field == "length" and d.agreed_steps == 3 and d.b == {}
    a2 = [dict(r, extra_field="tolerated") for r in a]
    assert replay.compare_streams(a, a2, 5) is None


def test_replay_command_argv(tmp_path):
    state = tmp_path / "inputs" / "start.state"
    state.parent.mkdir()
    state.write_text("synthetic")
    meta = {"seed": 42, "starter": "bulbasaur", "stop_at_goal": "gyarados", "adaptive": True}
    cmd = replay.replay_command(meta, state, 50, tmp_path / "out")
    assert cmd[0] == "uv" and cmd[1] == "run" and cmd[2] == "python"
    assert cmd[3].endswith("explore_headless.py")
    assert cmd[cmd.index("--state") + 1] == str(state)
    assert cmd[cmd.index("--steps") + 1] == "50"
    assert cmd[cmd.index("--seed") + 1] == "42"
    assert cmd[cmd.index("--starter") + 1] == "bulbasaur"
    assert cmd[cmd.index("--stop-at-goal") + 1] == "gyarados"
    assert "--adaptive" in cmd and "--maps-copy" not in cmd
    (state.parent / "maps.json").write_text("{}")
    cmd = replay.replay_command(meta, state, 50, tmp_path / "out")
    assert cmd[cmd.index("--maps-copy") + 1] == str(state.parent / "maps.json")


def test_locate_start_state():
    meta = json.loads((RUNS / RUN_OK / "meta.json").read_text())
    got = replay.locate_start_state(meta, RUNS)
    assert got == RUNS / "segments" / "inputs" / "seg_gyarados_1-1" / "nugget_bridge.state"
    meta2 = json.loads((RUNS / RUN_STALL / "meta.json").read_text())
    assert replay.locate_start_state(meta2, RUNS) is None     # no kept inputs copy
    assert replay.locate_start_state({"tag": None}, RUNS) is None


def _load(name):
    return RUNS / name


def test_run_replay_identical_and_diverged():
    orig = [r for r in (json.loads(x) for x in
                        (RUNS / RUN_OK / "decisions.jsonl").read_text().splitlines()) if "event" not in r]
    rep = replay.run_replay(_load(RUN_OK), 5, RUNS, runner=lambda argv, out: orig[:5])
    assert rep.status == "identical" and rep.divergence is None
    changed = [dict(r) for r in orig[:5]]
    changed[2]["button"] = "LEFT"
    rep = replay.run_replay(_load(RUN_OK), 5, RUNS, runner=lambda argv, out: changed)
    assert rep.status == "diverged"
    assert rep.divergence.step == 3 and rep.divergence.field == "button" and rep.divergence.agreed_steps == 2


def test_run_replay_unrecoverable_and_unavailable():
    rep = replay.run_replay(_load(RUN_STALL), 5, RUNS, runner=lambda argv, out: [])
    assert rep.status == "start_state_unrecoverable"
    rep = replay.run_replay(_load(RUN_OK), 5, RUNS, runner=lambda argv, out: None)
    assert rep.status == "runner_unavailable" and rep.command is not None
    assert "--seed" in rep.command


def test_run_replay_git_sha_warning():
    orig = [r for r in (json.loads(x) for x in
                        (RUNS / RUN_OK / "decisions.jsonl").read_text().splitlines()) if "event" not in r]
    rep = replay.run_replay(_load(RUN_OK), 5, RUNS, runner=lambda argv, out: orig[:5],
                            head_sha="deadbeef" * 5)
    assert rep.status == "identical"
    assert rep.warning == "code differs: divergence is expected"
    rep = replay.run_replay(_load(RUN_OK), 5, RUNS, runner=lambda argv, out: orig[:5],
                            head_sha="aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111")
    assert rep.warning is None
