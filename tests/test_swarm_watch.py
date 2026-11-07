import importlib.util
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _load(name):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(f"tool_{name}", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sw = _load("swarm_watch")


def make_run(root, seed=7, name="explore-1-1"):
    d = root / "runs" / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"seed": seed}))
    (d / "transitions.jsonl").write_text("")
    return d


def add(d, tiles):
    with open(d / "transitions.jsonl", "a") as f:
        for t in tiles:
            f.write(json.dumps({"to": [13, t[0], t[1]], "button": "A"}) + "\n")


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def watch(tmp_path, **kw):
    d = make_run(tmp_path)
    c = Clock()
    return d, c, sw.ProgressWatch(tmp_path, 7, since_wall=0, clock=c, **kw)


def test_stuck_loop_is_a_stall(tmp_path):
    d, c, w = watch(tmp_path)
    add(d, [(i % 3, 0) for i in range(700)])  # mashing A around 3 tiles
    r = w.check()
    assert r and "only 0 new tiles" in r and w.last_pos is not None


def test_exploring_is_healthy(tmp_path):
    d, c, w = watch(tmp_path)
    add(d, [(i, 0) for i in range(700)])
    assert w.check() is None


def test_old_tiles_outside_window_do_not_count_as_new(tmp_path):
    d, c, w = watch(tmp_path)
    add(d, [(i, 0) for i in range(100)] + [(i % 3, 0) for i in range(700)])
    assert w.check() is not None  # the 100 fresh tiles were first seen >600 presses ago


def test_goal_in_window_is_healthy_and_trainer_is_exempt(tmp_path):
    d, c, w = watch(tmp_path)
    add(d, [(i % 3, 0) for i in range(300)])
    w.check()
    (d / "goal_frames.jsonl").write_text(json.dumps({"goal": "potion", "step": 5, "frame": 9}) + chr(10))
    w.check()
    add(d, [(i % 3, 0) for i in range(500)])
    assert w.check() is None  # a goal landed 500 presses ago: inside the window
    d2 = tmp_path / "x"
    d2.mkdir()
    d3, c3, t = watch(d2, )
    add(d3, [(i % 3, 0) for i in range(900)])
    t.trainer = True
    assert t.check() is None


def test_hung_agent_with_no_new_transition(tmp_path):
    d, c, w = watch(tmp_path)
    add(d, [(0, 0), (1, 0)])
    assert w.check() is None
    c.t = 119
    assert w.check() is None
    c.t = 125
    assert "hung" in w.check()
    add(d, [(2, 0)])
    assert w.check() is None  # progress resumed


def test_run_dir_found_by_seed(tmp_path):
    make_run(tmp_path, seed=1, name="explore-a")
    d = make_run(tmp_path, seed=2, name="explore-b")
    assert sw.find_run_dir(tmp_path, 2, 0) == d and sw.find_run_dir(tmp_path, 3, 0) is None


def test_stall_record_has_last_position(tmp_path):
    d, c, w = watch(tmp_path)
    add(d, [(4, 5)])
    w.check()
    sw.record_stall(tmp_path / "runs" / "swarm", 2, 7, "why", w)
    row = json.loads((tmp_path / "runs" / "swarm" / "stalls.jsonl").read_text())
    assert row["pos"] == [13, 4, 5] and row["slot"] == 2 and row["run"] == "explore-1-1"


def test_startup_grace_before_first_transition(tmp_path):
    d, c, w = watch(tmp_path)  # run dir exists but no transition yet (slow ROM / checkpoint load)
    c.t = 170
    assert w.check() is None
    c.t = 185
    assert "no first transition" in w.check()


def test_hung_clock_starts_at_first_transition_and_unfound_run_dir_waits_out_grace(tmp_path):
    d, c, w = watch(tmp_path)
    c.t = 170
    add(d, [(0, 0)])
    assert w.check() is None  # first transition lands late; the 120 s clock starts now
    c.t = 250
    assert w.check() is None
    c.t = 295
    assert "hung: no new transition" in w.check()
    c2 = Clock()
    lost = sw.ProgressWatch(tmp_path / "nowhere", 99, since_wall=0, clock=c2)
    c2.t = 100
    assert lost.check() is None  # run dir not found yet: grace, not hung


def test_dungeon_gets_a_longer_window(tmp_path):
    d, c, w = watch(tmp_path)
    with open(d / "transitions.jsonl", "a") as f:
        for i in range(1000):
            f.write(json.dumps({"to": [0x3D, i % 3, 0], "button": "A"}) + "\n")  # Mt Moon B2F, looping
    assert w.check() is None and w.window_now() == sw.DUNGEON_WINDOW_PRESSES
    with open(d / "transitions.jsonl", "a") as f:
        for i in range(600):
            f.write(json.dumps({"to": [0x3D, i % 3, 0], "button": "A"}) + "\n")
    r = w.check()
    assert r and f"last {sw.DUNGEON_WINDOW_PRESSES} presses" in r  # still caught, just later
