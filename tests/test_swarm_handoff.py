import json
import os
import sys

import pytest
from test_swarm_continuous import World, _load

sh = _load("swarm_handoff")
NEW = 4242  # the requesting (new) supervisor's pid in these tests


class FakeProcs:
    """pid -> 'alive' | 'gone' (registry.process_state) plus process identity; kills are recorded."""

    def __init__(self):
        self.state, self.killed, self.start, self.cmd = {}, [], {}, {}

    def __call__(self, pid):
        return self.state.get(pid, "gone")

    def kill(self, pid):
        self.killed.append(pid)
        self.state[pid] = "gone"

    def created(self, pid):
        return self.start.get(pid)

    def cmdline(self, pid):
        return self.cmd.get(pid)


def _ask(w, pid=NEW, lock=True):
    w.sup.handoff_file.parent.mkdir(parents=True, exist_ok=True)
    w.sup.handoff_file.write_text(json.dumps({"pid": pid}))
    if lock:  # the old supervisor owns the spawn lock
        (w.sup.handoff_file.parent / "spawn.lock").write_text(str(os.getpid()))


def _world_with_pids(tmp_path, n=2, **kw):
    w = World(tmp_path, n=n, **kw)
    w.sup.ident = w.sup.state = FakeProcs()
    w.sup.state.state[NEW] = "alive"  # the requester is alive
    w.sup.tick()
    for i, p in enumerate(w.procs):
        p.pid = 500 + i
        w.sup.ident.start[p.pid] = 1000 + i
    return w


def _handed(tmp_path, n=2, **kw):
    w = _world_with_pids(tmp_path, n, **kw)
    _ask(w)
    w.sup.tick()
    return w, sh.read_adopt(w.sup.swarm_dir, NEW)


def _new_world(tmp_path, n, fp, **kw):
    w2 = World(tmp_path, n=n, **kw)
    w2.sup.state, w2.sup.kill_pid, w2.sup.ident = fp, fp.kill, fp
    return w2


def _fp(*pids):
    fp = FakeProcs()
    for i, p in enumerate(pids):
        fp.state[p], fp.start[p], fp.cmd[p] = "alive", 1000 + i, "python tools/explore_demo.py --headless"
    return fp


def test_handoff_writes_adopt_json_and_exits_without_killing(tmp_path):
    w = _world_with_pids(tmp_path)
    _ask(w)
    w.sup.run()  # ends by itself after handing over
    assert w.sup.handed_over and not any(p.killed for p in w.procs)
    data = sh.read_adopt(w.sup.swarm_dir, NEW)
    assert [a["pid"] for a in data["agents"]] == [500, 501]
    a = data["agents"][0]
    assert {"slot", "seed", "own", "hash", "role", "cfg", "run_dir", "ident"} <= set(a)
    assert a["ident"]["created"] == 1000 and "explore_demo" in a["ident"]["sig"]
    assert not w.sup.handoff_file.exists() and w.merges == []
    assert len(w.procs) == 2  # no refills after handover


def test_unreadable_request_waits_for_next_tick(tmp_path):
    w = _world_with_pids(tmp_path)
    w.sup.handoff_file.parent.mkdir(parents=True, exist_ok=True)
    w.sup.handoff_file.write_text("")  # claimed but not written yet
    w.sup.tick()
    assert not w.sup.handed_over
    _ask(w)
    w.sup.tick()
    assert w.sup.handed_over


def test_agent_exited_before_handoff_is_merged_once_by_old_supervisor(tmp_path):
    w = _world_with_pids(tmp_path)
    w.end(w.procs[0])  # exits between ticks
    _ask(w)
    w.sup.tick()
    assert w.merges == ["agent0-0.json"]
    data = sh.read_adopt(w.sup.swarm_dir, NEW)
    assert [a["pid"] for a in data["agents"]] == [501]
    fp = _fp(501)
    fp.start[501] = 1001
    w2 = _new_world(tmp_path, 2, fp)
    w2.sup.adopt(data)
    w2.sup.tick()
    assert w2.merges == [] and len(w2.procs) == 1  # not merged twice; its slot is refilled by the new supervisor


def test_adopt_merges_on_exit_and_refills_on_new_code(tmp_path):
    w, data = _handed(tmp_path)
    fp = _fp(500, 501)
    w2 = _new_world(tmp_path, 2, fp)
    w2.sup.adopt(data)
    w2.sup.tick()
    assert w2.sup.running() == 2 and w2.procs == []
    fp.state[500] = "gone"
    w2.sup.tick()
    assert w2.merges == ["agent0-0.json"] and len(w2.procs) == 1
    assert w2.procs[0].cfg["seq"] >= 2  # no filename/seed collision with adopted agents
    assert w2.sup.running() == 2


def test_dead_adopted_agent_unchanged_memory_is_skipped(tmp_path):
    w, data = _handed(tmp_path, n=1)
    fp = _fp(500)
    w2 = _new_world(tmp_path, 1, fp)
    w2.sup.adopt(data)
    own = w2.sup.slots[0].cfg["own"]
    own.write_text(json.dumps({"v": 0}))  # byte-identical to the memory copy it started from
    from hashlib import sha256
    w2.sup.slots[0].cfg["hash"] = sha256(own.read_bytes()).hexdigest()
    fp.state[500] = "gone"
    w2.sup.tick()
    assert w2.merges == [] and any("memory untouched, skipped" in line for line in w2.logs)


def test_dead_adopted_agent_with_changed_memory_is_merged(tmp_path):
    w, data = _handed(tmp_path, n=1)
    fp = _fp(500)
    w2 = _new_world(tmp_path, 1, fp)
    w2.sup.adopt(data)
    fp.state[500] = "gone"  # crashed; its file differs from the start hash (the fake agent wrote to it)
    w2.sup.tick()
    assert w2.merges == ["agent0-0.json"]


def test_request_handoff_refuses_when_old_supervisor_silent(tmp_path):
    t = [0.0]
    got = sh.request_handoff(tmp_path, wait_s=30, pid=NEW, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + 5))
    assert got is None
    assert not (tmp_path / "runs" / "swarm.handoff").exists()  # request withdrawn: no half-state


def test_request_handoff_returns_adopt_data_keyed_to_pid(tmp_path):
    sd = tmp_path / "runs" / "swarm"
    sd.mkdir(parents=True)
    (sd / "adopt-999.json").write_text(json.dumps({"agents": [], "next_seq": 99}))  # someone else's answer

    def answer(_s):
        (sd / f"adopt-{NEW}.json").write_text(json.dumps({"agents": [], "next_seq": 3}))

    got = sh.request_handoff(tmp_path, wait_s=30, pid=NEW, sleep=answer)
    assert got == {"agents": [], "next_seq": 3}
    assert (sd / "adopt-999.json").exists()  # never unlinks another requester's file


def test_concurrent_requesters_second_is_refused_and_first_untouched(tmp_path):
    runs = tmp_path / "runs"
    (runs / "swarm").mkdir(parents=True)
    (runs / "swarm.handoff").write_text(json.dumps({"pid": 111}))
    (runs / "swarm" / "adopt-111.json").write_text("{}")
    got = sh.request_handoff(tmp_path, wait_s=30, pid=222, alive=lambda p: p == 111, sleep=lambda s: None)
    assert got is None
    assert json.loads((runs / "swarm.handoff").read_text()) == {"pid": 111}
    assert (runs / "swarm" / "adopt-111.json").exists()


def test_dead_requesters_claim_is_replaced(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "swarm.handoff").write_text(json.dumps({"pid": 111}))
    sd = runs / "swarm"
    sd.mkdir()

    def answer(_s):
        (sd / "adopt-222.json").write_text(json.dumps({"agents": []}))

    assert sh.request_handoff(tmp_path, wait_s=30, pid=222, alive=lambda p: False, sleep=answer) == {"agents": []}


def test_late_answer_after_timeout_is_still_adopted(tmp_path):
    sd = tmp_path / "runs" / "swarm"
    sd.mkdir(parents=True)
    calls = []

    def clock():
        calls.append(1)
        if len(calls) == 2:  # the loop check: out of time, and the old supervisor answers just now
            (sd / f"adopt-{NEW}.json").write_text(json.dumps({"agents": [], "next_seq": 7}))
            return 99.0
        return 0.0

    assert sh.request_handoff(tmp_path, wait_s=30, pid=NEW, clock=clock, sleep=lambda s: None)["next_seq"] == 7


def test_lock_is_transferred_not_released(tmp_path, monkeypatch):
    w = _world_with_pids(tmp_path)
    lock = tmp_path / "runs" / "spawn.lock"
    lock.parent.mkdir(exist_ok=True)
    lock.write_text(str(os.getpid()))
    _ask(w)
    w.sup.tick()
    assert lock.read_text() == str(NEW)  # never free in between
    monkeypatch.setattr(os, "getpid", lambda: NEW)
    with sh.adopt_lock(tmp_path):
        assert lock.exists()
    assert not lock.exists()


def test_adopt_lock_refuses_when_lock_not_ours(tmp_path):
    from pokeagent import resources
    lock = tmp_path / "runs" / "spawn.lock"
    lock.parent.mkdir()
    lock.write_text("1")
    with pytest.raises(resources.LockBusy), sh.adopt_lock(tmp_path):
        pass


def test_old_spawn_lock_exit_leaves_transferred_lock(tmp_path):
    from pokeagent import resources
    with resources.spawn_lock(tmp_path):
        sh.transfer_lock(tmp_path, NEW)
    assert (tmp_path / "runs" / "spawn.lock").read_text() == str(NEW)


def test_reused_pid_is_treated_as_gone_and_never_killed(tmp_path):
    w, data = _handed(tmp_path, n=2)
    fp = _fp(500, 501)
    fp.start[500] = 99999  # pid 500 now belongs to a different (newer) process
    fp.cmd[501] = "notepad.exe"  # same start stamp, but not an explore_demo agent
    w2 = _new_world(tmp_path, 2, fp, stop_now=True)
    w2.sup.adopt(data)
    assert any("pid reused" in line for line in w2.logs)
    w2.sup.tick()
    assert fp.killed == []
    w2.sup.request_stop("test")
    assert fp.killed == []  # never kill a mismatched pid


def test_slot_count_change(tmp_path):
    w, data = _handed(tmp_path, n=3)
    fp = _fp(500, 501, 502)
    fewer = _new_world(tmp_path, 2, fp)
    fewer.sup.adopt(data)
    fewer.sup.tick()
    assert fewer.sup.running() == 3  # slot 2 retires when its agent finishes
    fp.state[502] = "gone"
    fewer.sup.tick()
    assert len(fewer.sup.slots) == 2 and fewer.procs == []
    fp.state[502] = "alive"
    more = _new_world(tmp_path, 5, fp)
    more.sup.adopt(data)
    more.sup.tick()
    assert more.sup.running() == 5 and len(more.procs) == 2  # extra slots fill from the new supervisor


def test_adopted_agents_keep_old_settings_and_it_is_logged(tmp_path):
    w, data = _handed(tmp_path, n=1)
    w2 = _new_world(tmp_path, 1, _fp(500), steps=123)
    w2.sup.adopt(data)
    assert any("keeps its old settings" in line for line in w2.logs)


def test_watchdog_applies_to_adopted_agents(tmp_path):
    w, data = _handed(tmp_path, n=1)
    fp = _fp(500)

    class Dog:
        last_pos, presses, run_dir = None, 0, None

        def check(self):
            return "no progress"

    w2 = _new_world(tmp_path, 1, fp, watch=lambda cfg: Dog())
    w2.sup.adopt(data)
    w2.sup.tick()
    w2.t += 30
    w2.sup.tick()
    assert 500 in fp.killed and any("stalled" in line for line in w2.logs)
    assert len(w2.procs) == 1  # slot refilled


def test_stop_now_kills_adopted_tree(tmp_path):
    w, data = _handed(tmp_path, n=1)
    fp = _fp(500)
    w2 = _new_world(tmp_path, 1, fp, stop_now=True)
    w2.sup.adopt(data)
    w2.sup.request_stop("test")
    assert fp.killed == [500]


def test_unknown_identity_is_never_killed(tmp_path):
    h = lambda rec, fp: sh.ProcHandle(500, fp, fp.kill, fp, rec)  # noqa: E731
    fp = _fp(500)
    fp.start.pop(500)  # created() unreadable
    h({"created": 1000, "sig": "explore_demo"}, fp).kill()
    fp = _fp(500)
    fp.cmd.pop(500)  # cmdline() unreadable
    h({"created": 1000, "sig": "explore_demo"}, fp).kill()
    h({"sig": "explore_demo"}, _fp(500)).kill()  # nothing recorded to match against
    h({}, fp).kill()
    assert fp.killed == []
    fp = _fp(500)
    h({"created": 1000, "sig": "explore_demo"}, fp).kill()
    assert fp.killed == [500]  # positive match on both: killed


def test_lock_not_ours_refuses_handoff_and_keeps_running(tmp_path):
    w = _world_with_pids(tmp_path)
    _ask(w)
    (tmp_path / "runs" / "spawn.lock").write_text("1")
    w.sup.tick()
    assert not w.sup.handed_over and not w.sup.stopping
    assert sh.read_adopt(w.sup.swarm_dir, NEW) is None and w.sup.handoff_file.exists()
    assert w.sup.running() == 2 and any("refused" in line for line in w.logs)
    w.sup.tick()
    assert sum("refused" in line for line in w.logs) == 1  # logged once, not every tick


def test_old_supervisor_backs_off_when_requester_gone_or_claim_changed(tmp_path):
    w = _world_with_pids(tmp_path)
    _ask(w)
    w.sup.state.state[NEW] = "gone"  # requester died / gave up
    w.sup.tick()
    assert not w.sup.handed_over and (tmp_path / "runs" / "spawn.lock").read_text() == str(os.getpid())
    w.sup.state.state[NEW] = "alive"
    w.sup.handoff_file.write_text(json.dumps({"pid": 7}))  # claim now someone else's, who is not alive
    w.sup.tick()
    assert not w.sup.handed_over


def test_empty_old_claim_is_replaced_but_fresh_empty_claim_blocks(tmp_path):
    runs = tmp_path / "runs"
    (runs / "swarm").mkdir(parents=True)
    req = runs / "swarm.handoff"
    req.write_text("")
    assert sh.request_handoff(tmp_path, wait_s=30, pid=NEW, alive=lambda p: True, sleep=lambda s: None) is None
    assert req.exists()  # fresh empty claim: its writer may still be writing
    old = req.stat().st_mtime - 60
    os.utime(req, (old, old))

    def answer(_s):
        (runs / "swarm" / f"adopt-{NEW}.json").write_text(json.dumps({"agents": []}))

    assert sh.request_handoff(tmp_path, wait_s=30, pid=NEW, alive=lambda p: True, sleep=answer) == {"agents": []}


def test_dead_claim_replacement_is_serialised_by_replacer_lock(tmp_path):
    req = tmp_path / "swarm.handoff"
    req.write_text(json.dumps({"pid": 111}))
    rl = tmp_path / "swarm.handoff.replace"
    rl.write_text("")  # another replacer is mid-replace
    assert sh.claim(req, NEW, lambda p: False) is False
    assert json.loads(req.read_text()) == {"pid": 111}  # untouched
    old = rl.stat().st_mtime - 120
    os.utime(rl, (old, old))  # its holder died: stale replacer lock is cleared
    assert sh.claim(req, NEW, lambda p: False) is True
    assert json.loads(req.read_text())["pid"] == NEW and not rl.exists()
    assert sh.claim(req, 5, lambda p: True) is False  # now live: never replaced


def test_withdraw_only_removes_own_claim(tmp_path):
    req = tmp_path / "swarm.handoff"
    req.write_text(json.dumps({"pid": 7}))
    sh.withdraw(req, NEW)
    assert json.loads(req.read_text()) == {"pid": 7}
    sh.withdraw(req, 7)
    assert not req.exists() and [p.name for p in tmp_path.iterdir()] == []


def test_unowned_live_kill_keeps_handle_and_starts_no_replacement(tmp_path):
    w, data = _handed(tmp_path, n=1)
    fp = _fp(500)
    fp.cmd.pop(500)  # identity unreadable: alive but not provably ours
    w2 = _new_world(tmp_path, 1, fp)
    w2.sup.adopt(data)
    w2.t += 10000  # past the per-agent timeout
    w2.sup.tick()
    assert fp.killed == [] and w2.sup.slots[0].handle is not None and w2.procs == []
    assert any("not provably our agent" in line for line in w2.logs)
    w2.sup.tick()
    assert sum("not provably" in line for line in w2.logs) == 1 and w2.procs == []
    fp.state[500] = "gone"  # it exits on its own: normal finish and refill
    w2.sup.tick()
    assert len(w2.procs) == 1


def test_withdrawn_between_check_and_lock_move_puts_lock_back(tmp_path, monkeypatch):
    w = _world_with_pids(tmp_path)
    _ask(w)
    live = sys.modules["swarm_handoff"]  # the module the supervisor really calls
    real = live.transfer_lock

    def move_then_withdraw(root, new_pid, expect=None):
        ok = real(root, new_pid, expect)
        if expect is None:
            w.sup.handoff_file.unlink()  # the requester withdraws right after the lock moved
        return ok

    monkeypatch.setattr(live, "transfer_lock", move_then_withdraw)
    w.sup.tick()
    lock = tmp_path / "runs" / "spawn.lock"
    assert lock.read_text() == str(os.getpid())
    assert not w.sup.handed_over and not w.sup.stopping and sh.read_adopt(w.sup.swarm_dir, NEW) is None
    assert w.sup.running() == 2


def test_failure_after_lock_move_rolls_back(tmp_path, monkeypatch):
    w = _world_with_pids(tmp_path)
    _ask(w)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(sys.modules["swarm_handoff"], "write_atomic", boom)
    w.sup.tick()
    assert (tmp_path / "runs" / "spawn.lock").read_text() == str(os.getpid())
    assert not w.sup.handed_over and not w.sup.stopping and any("lock restored" in line for line in w.logs)
    assert w.sup.running() == 2


def test_lock_failure_after_answer_still_supervises_loudly(tmp_path, monkeypatch):
    import contextlib
    from pokeagent import resources

    def busy(root, wait_s=0.0):
        raise resources.LockBusy("held")

    monkeypatch.setattr(resources, "spawn_lock", busy)
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "spawn.lock").write_text("1")
    said = []
    with contextlib.ExitStack() as stack:
        assert sh.acquire_after_handoff(stack, tmp_path, [500, 501], said.append, tries=2, wait_s=0) is False
    assert said and "500" in said[0] and "WITHOUT" in said[0]


def test_withdraw_is_atomic_rename_and_late_answer_after_lock_move_is_adopted(tmp_path):
    runs = tmp_path / "runs"
    sd = runs / "swarm"
    sd.mkdir(parents=True)
    t = [0.0]
    moved = []

    def sleep(_s):
        t[0] += 5
        if t[0] >= 30 and not moved:  # past the wait: the old side moves the lock, answers a moment later
            moved.append(1)
            (runs / "spawn.lock").write_text(str(NEW))
        elif moved:
            (sd / f"adopt-{NEW}.json").write_text(json.dumps({"agents": [], "next_seq": 5}))

    got = sh.request_handoff(tmp_path, wait_s=30, pid=NEW, clock=lambda: t[0], sleep=sleep)
    assert got == {"agents": [], "next_seq": 5}
    assert not (runs / "swarm.handoff").exists()
    assert [p.name for p in runs.iterdir() if "handoff" in p.name] == []  # no stray withdrawn/tomb files
