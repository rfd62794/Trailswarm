import json

from test_swarm_continuous import World, _load

sh = _load("swarm_handoff")


class FakeProcs:
    """pid -> 'alive' | 'gone', standing in for registry.process_state; kills are recorded."""

    def __init__(self):
        self.state, self.killed = {}, []

    def __call__(self, pid):
        return self.state.get(pid, "gone")

    def kill(self, pid):
        self.killed.append(pid)
        self.state[pid] = "gone"


def _world_with_pids(tmp_path, n=2, **kw):
    w = World(tmp_path, n=n, **kw)
    w.sup.tick()
    for i, p in enumerate(w.procs):
        p.pid = 500 + i
    return w


def _new_world(tmp_path, n, fp, **kw):
    w2 = World(tmp_path, n=n, **kw)
    w2.sup.state, w2.sup.kill_pid = fp, fp.kill
    return w2


def test_handoff_writes_adopt_json_and_exits_without_killing(tmp_path):
    w = _world_with_pids(tmp_path)
    (tmp_path / "runs").mkdir(exist_ok=True)
    w.sup.handoff_file.parent.mkdir(parents=True, exist_ok=True)
    w.sup.handoff_file.write_text("{}")
    w.sup.run()  # ends by itself after handing over
    assert w.sup.handed_over and not any(p.killed for p in w.procs)
    data = json.loads((w.sup.swarm_dir / "adopt.json").read_text())
    assert [a["pid"] for a in data["agents"]] == [500, 501]
    a = data["agents"][0]
    assert {"slot", "seed", "own", "hash", "role", "cfg", "run_dir"} <= set(a)
    assert not w.sup.handoff_file.exists() and w.merges == []
    assert len(w.procs) == 2  # no refills after handover


def test_adopt_merges_on_exit_and_refills_on_new_code(tmp_path):
    w = _world_with_pids(tmp_path)
    w.sup.handoff_file.parent.mkdir(parents=True, exist_ok=True)
    w.sup.handoff_file.write_text("{}")
    w.sup.tick()
    data = sh.read_adopt(w.sup.swarm_dir)
    fp = FakeProcs(); fp.state.update({500: "alive", 501: "alive"})
    w2 = _new_world(tmp_path, 2, fp)
    w2.sup.adopt(data)
    w2.sup.tick()
    assert w2.sup.running() == 2 and w2.procs == []
    fp.state[500] = "gone"
    w2.sup.tick()
    assert w2.merges == ["agent0-0.json"] and len(w2.procs) == 1  # merged, refilled by the new supervisor
    assert w2.procs[0].cfg["seq"] >= 2  # no filename/seed collision with adopted agents
    assert w2.sup.running() == 2


def test_dead_adopted_agent_unchanged_memory_is_skipped(tmp_path):
    w = _world_with_pids(tmp_path, n=1)
    w.sup.handoff_file.parent.mkdir(parents=True, exist_ok=True)
    w.sup.handoff_file.write_text("{}")
    w.sup.tick()
    fp = FakeProcs(); fp.state[500] = "alive"
    w2 = _new_world(tmp_path, 1, fp)
    w2.sup.adopt(sh.read_adopt(w.sup.swarm_dir))
    w2.sup.slots[0].cfg["own"].write_text(w2.shared.read_text())  # as at launch: nothing learned
    # digest is of launch content; make the file equal to hash source
    fp.state[500] = "gone"
    w2.sup.tick()
    assert any("slot 0 finished" in line for line in w2.logs)


def test_request_handoff_refuses_when_old_supervisor_silent(tmp_path):
    t = [0.0]
    got = sh.request_handoff(tmp_path, wait_s=30, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + 5))
    assert got is None
    assert not (tmp_path / "runs" / "swarm.handoff").exists()  # request withdrawn: no half-state


def test_request_handoff_returns_adopt_data(tmp_path):
    sd = tmp_path / "runs" / "swarm"; sd.mkdir(parents=True)

    def answer(_s):
        (sd / "adopt.json").write_text(json.dumps({"agents": [], "next_seq": 3}))

    got = sh.request_handoff(tmp_path, wait_s=30, sleep=answer)
    assert got == {"agents": [], "next_seq": 3}


def test_slot_count_change(tmp_path):
    w = _world_with_pids(tmp_path, n=3)
    w.sup.handoff_file.parent.mkdir(parents=True, exist_ok=True)
    w.sup.handoff_file.write_text("{}")
    w.sup.tick()
    data = sh.read_adopt(w.sup.swarm_dir)
    fp = FakeProcs(); fp.state.update({500: "alive", 501: "alive", 502: "alive"})
    fewer = _new_world(tmp_path, 2, fp)
    fewer.sup.adopt(data)
    fewer.sup.tick()
    assert fewer.sup.running() == 3  # slot 2 retires when its agent finishes
    fp.state[502] = "gone"
    fewer.sup.tick()
    assert len(fewer.sup.slots) == 2 and fewer.procs == []
    more = _new_world(tmp_path, 5, fp)
    fp.state[502] = "alive"
    more.sup.adopt(data)
    more.sup.tick()
    assert more.sup.running() == 5 and len(more.procs) == 2  # extra slots fill from the new supervisor


def test_watchdog_applies_to_adopted_agents(tmp_path):
    w = _world_with_pids(tmp_path, n=1)
    w.sup.handoff_file.parent.mkdir(parents=True, exist_ok=True)
    w.sup.handoff_file.write_text("{}")
    w.sup.tick()
    fp = FakeProcs(); fp.state[500] = "alive"

    class Dog:
        last_pos, presses, run_dir = None, 0, None

        def check(self):
            return "no progress"

    w2 = _new_world(tmp_path, 1, fp, watch=lambda cfg: Dog())
    w2.sup.adopt(sh.read_adopt(w.sup.swarm_dir))
    w2.sup.tick()
    w2.t += 30
    w2.sup.tick()
    assert 500 in fp.killed and any("stalled" in line for line in w2.logs)
    assert len(w2.procs) == 1  # slot refilled


def test_stop_now_kills_adopted_tree(tmp_path):
    w = _world_with_pids(tmp_path, n=1)
    w.sup.handoff_file.parent.mkdir(parents=True, exist_ok=True)
    w.sup.handoff_file.write_text("{}")
    w.sup.tick()
    fp = FakeProcs(); fp.state[500] = "alive"
    w2 = _new_world(tmp_path, 1, fp, stop_now=True)
    w2.sup.adopt(sh.read_adopt(w.sup.swarm_dir))
    w2.sup.request_stop("test")
    assert fp.killed == [500]
