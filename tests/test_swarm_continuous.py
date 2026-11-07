import importlib.util
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sc = _load("swarm_continuous")


class FakeProc:
    def __init__(self, cfg, world):
        self.cfg, self.rc, self.killed = cfg, None, False
        world.procs.append(self)

    def poll(self):
        return self.rc

    def kill(self):
        self.killed = True
        self.rc = -9


class World:
    def __init__(self, tmp_path, n=2, limit=99, **kw):
        self.untouched = False
        self.procs, self.merges, self.logs, self.t = [], [], [], 0.0
        self.shared = tmp_path / "maps.json"
        self.shared.write_text(json.dumps({"v": 0}))

        def launch(cfg):
            if not self.untouched:  # the agent saved something new
                cfg["own"].write_text(self.shared.read_text() + " ")
            return FakeProc(cfg, self)

        def merge(shared, own):
            self.merges.append(own.name)
            d = json.loads(shared.read_text())
            d["v"] += 1
            shared.write_text(json.dumps(d))

        self.sup = sc.Supervisor(tmp_path, self.shared, n, launch, merge, lambda: limit, clock=lambda: self.t,
                                 sleep=lambda s: None, log=self.logs.append, on_stall=_load('swarm_watch').record_stall, stop_file=tmp_path / "swarm.stop", **kw)

    def live(self):
        return [p for p in self.procs if p.rc is None]

    def end(self, proc, rc=0, after=100.0):
        self.t += after
        proc.rc = rc


def test_fills_to_n_and_refills_on_exit_with_merge(tmp_path):
    w = World(tmp_path, n=3)
    w.sup.tick()
    assert len(w.live()) == 3 and "3/3 running" in w.logs[-1]
    w.end(w.procs[1])
    w.sup.tick()
    assert len(w.live()) == 3 and len(w.procs) == 4
    assert w.merges == ["agent1-1.json"]
    assert any("1 finished, 1 merged" in line for line in w.logs)


def test_replacement_starts_from_freshest_memory(tmp_path):
    w = World(tmp_path, n=1)
    w.sup.tick()
    first = w.procs[0]
    w.end(first)
    w.sup.tick()
    assert json.loads(w.shared.read_text())["v"] == 1  # merged before the replacement copied it
    assert json.loads(w.procs[1].cfg["own"].read_text())["v"] == 1


def test_cap_respected(tmp_path):
    w = World(tmp_path, n=4, limit=2)
    w.sup.tick()
    assert len(w.live()) == 2
    w.end(w.procs[0])
    w.sup.tick()
    assert len(w.live()) == 2  # replacement, never a third


def test_seed_starter_rotation(tmp_path):
    w = World(tmp_path, n=2)
    w.sup.tick()
    for _ in range(4):
        w.end(w.live()[0])
        w.sup.tick()
    seeds = [p.cfg["seed"] for p in w.procs]
    assert seeds == sorted(set(seeds)) == [1000 + i for i in range(len(seeds))]
    assert [p.cfg["starter"] for p in w.procs[:4]] == ["bulbasaur", "charmander", "squirtle", "bulbasaur"]
    assert {p.cfg["role"] for p in w.procs} == {"exploiter", "explorer"}


def test_fixed_starter_and_segment_rotation(tmp_path):
    w = World(tmp_path, n=2, starter="squirtle", segment=lambda n: ["a", "b"][n % 2])
    w.sup.tick()
    assert [p.cfg["starter"] for p in w.procs] == ["squirtle"] * 2
    assert [p.cfg["segment"] for p in w.procs] == ["a", "b"]


def test_crash_loop_pauses_slot_five_minutes(tmp_path):
    w = World(tmp_path, n=1)
    w.sup.tick()
    w.end(w.procs[0], rc=1, after=5)
    w.sup.tick()
    assert len(w.procs) == 2  # first fast failure: retried
    w.end(w.procs[1], rc=1, after=5)
    w.sup.tick()
    assert len(w.procs) == 2 and any("paused 300s" in line and "2 fast failures" in line for line in w.logs)
    w.t += 299
    w.sup.tick()
    assert len(w.procs) == 2  # still paused
    w.t += 2
    w.sup.tick()
    assert len(w.procs) == 3  # pause served


def test_slow_or_clean_exit_resets_streak(tmp_path):
    w = World(tmp_path, n=1)
    w.sup.tick()
    w.end(w.procs[0], rc=1, after=5)
    w.sup.tick()
    w.end(w.procs[1], rc=0, after=100)  # full-length clean run
    w.sup.tick()
    w.end(w.procs[2], rc=1, after=5)  # streak restarted at 1
    w.sup.tick()
    assert len(w.procs) == 4 and not any("paused" in line for line in w.logs)


def test_stop_file_lets_agents_finish_then_merges_without_refill(tmp_path):
    w = World(tmp_path, n=2)
    w.sup.tick()
    (tmp_path / "swarm.stop").write_text("")
    w.sup.tick()
    assert len(w.live()) == 2 and w.sup.stopping  # not killed
    w.end(w.procs[0])
    w.end(w.procs[1], after=0)
    w.sup.tick()
    assert len(w.procs) == 2 and len(w.merges) == 2 and w.sup.running() == 0


def test_stop_now_kills_and_merges(tmp_path):
    w = World(tmp_path, n=2, stop_now=True)
    w.sup.tick()
    (tmp_path / "swarm.stop").write_text("")
    w.sup.tick()
    assert all(p.killed for p in w.procs)
    w.sup.tick()
    assert w.sup.running() == 0 and len(w.merges) == 2


def test_run_clears_stale_stop_file_and_honours_deadline(tmp_path):
    (tmp_path / "swarm.stop").write_text("")
    w = World(tmp_path, n=1, deadline=50.0)
    ticks = []

    def sleep(_):
        ticks.append(1)
        w.t += 20
        for p in w.live():
            if w.sup.stopping:
                p.rc = 0

    w.sup.sleep = sleep
    w.sup.run()
    assert w.sup.stopping and any("duration reached" in line for line in w.logs)
    assert w.live() == [] and not (tmp_path / "swarm.stop").exists() and "swarm done" in w.logs[-1]


def test_unmergeable_exit_is_logged_and_slot_refilled(tmp_path):
    w = World(tmp_path, n=1)
    w.sup.tick()
    w.procs[0].cfg["own"].unlink()
    w.end(w.procs[0])
    w.sup.tick()
    assert len(w.procs) == 2 and any("not merged" in line for line in w.logs)


def test_merge_file_into_is_atomic_and_locked(tmp_path):
    sm = _load("swarm_merge")
    shared, own = tmp_path / "maps.json", tmp_path / "own.json"
    own.write_text(json.dumps({"maps": {"1": {"visited": {"1,1": 3}}}, "team_best_level": 7}))
    dst = sm.merge_file_into(shared, own)
    assert dst["maps"]["1"]["visited"]["1,1"] == 3 and json.loads(shared.read_text())["team_best_level"] == 7
    assert not shared.with_suffix(".lock").exists() and not shared.with_suffix(".json.tmp").exists()


def test_untouched_memory_copy_is_skipped_not_merged(tmp_path):
    w = World(tmp_path, n=1)
    w.untouched = True
    w.sup.tick()
    w.end(w.procs[0], rc=1, after=5)
    w.sup.tick()
    assert w.merges == [] and w.sup.merged == 0 and w.sup.finished == 1
    assert any("untouched, skipped" in line for line in w.logs) and len(w.procs) == 2


def test_kill_tree_leaves_no_grandchild(tmp_path):
    import os
    import subprocess
    import time
    sp = _load("swarm_proc")
    pidfile = tmp_path / "gc.pid"
    h = sp.TreeProc([sys.executable, str(TOOLS / "swarm_proc.py"), str(pidfile)])
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text():
            break
        time.sleep(0.1)
    gc = int(pidfile.read_text())

    def alive(pid):
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
            return str(pid) in out
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    assert alive(gc)
    h.kill()
    for _ in range(50):
        if not alive(gc):
            break
        time.sleep(0.1)
    assert h.poll() is not None and not alive(gc)


def test_heartbeat_called_every_tick_and_keeps_old_lock_fresh(tmp_path):
    import os
    import time
    from pokeagent import resources
    (tmp_path / "runs").mkdir()
    with resources.spawn_lock(tmp_path):
        lock = tmp_path / "runs" / "spawn.lock"
        w = World(tmp_path, n=1, heartbeat=lambda: os.utime(lock))
        old = time.time() - 8 * 3600
        os.utime(lock, (old, old))
        assert resources._stale(lock)  # an 8 h old lock looks stale to a rival swarm...
        w.sup.tick()
        assert not resources._stale(lock)  # ...until the supervisor's heartbeat touches it


def test_merge_retries_permission_error_then_succeeds(tmp_path, monkeypatch):
    sm = _load("swarm_merge")
    monkeypatch.setattr(sm, "_sleep", lambda s: None)
    real, calls = sm.os.replace, []

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 4:
            raise PermissionError("reader has it open")
        return real(a, b)

    monkeypatch.setattr(sm.os, "replace", flaky)
    own = tmp_path / "own.json"
    own.write_text(json.dumps({"maps": {}, "team_best_level": 5}))
    sm.merge_file_into(tmp_path / "maps.json", own)
    assert len(calls) == 4 and json.loads((tmp_path / "maps.json").read_text())["team_best_level"] == 5


def test_final_merge_failure_keeps_agent_memory_for_recovery(tmp_path):
    w = World(tmp_path, n=1)

    def bad_merge(shared, own):
        raise PermissionError("locked")

    w.sup.merge = bad_merge
    w.sup.tick()
    w.end(w.procs[0])
    w.sup.tick()
    kept = tmp_path / "runs" / "swarm" / "unmerged" / "agent0-0.json"
    assert kept.exists() and any("kept in" in line for line in w.logs) and w.sup.merged == 0


def test_fast_clean_exit_short_of_budget_backs_off(tmp_path):
    w = World(tmp_path, n=1, steps=400)  # 400 steps cannot finish in 3 s
    w.sup.tick()
    w.end(w.procs[0], rc=0, after=3)
    w.sup.tick()
    w.end(w.procs[1], rc=0, after=3)
    w.sup.tick()
    assert len(w.procs) == 2 and any("paused 300s" in line for line in w.logs)


def test_launcher_exception_feeds_backoff_not_crash(tmp_path):
    w = World(tmp_path, n=1)

    def boom(cfg):
        raise OSError("no free port")

    w.sup.launch = boom
    w.sup.tick()
    w.sup.tick()
    w.sup.tick()
    assert w.sup.running() == 0 and sum("failed to start" in line for line in w.logs) == 2
    assert any("paused 300s" in line and "no free port" in line for line in w.logs)


def test_missing_segment_checkpoint_warns_every_refill(tmp_path):
    w = World(tmp_path, n=1, segment=lambda n: "won_battle", segment_ok=lambda g: False)
    w.sup.tick()
    w.end(w.procs[0])
    w.sup.tick()
    assert sum("segment won_battle: no checkpoint, running a full agent" in line for line in w.logs) == 2


class FakeWatch:
    def __init__(self):
        self.reason, self.last_pos, self.presses, self.run_dir = None, [13, 2, 3], 5, None

    def check(self):
        return self.reason


def test_stalled_agent_is_stopped_merged_logged_and_replaced(tmp_path):
    watchers = []
    w = World(tmp_path, n=1, watch=lambda cfg: watchers.append(FakeWatch()) or watchers[-1])
    w.sup.tick()
    watchers[0].reason = "no new goal and only 2 new tiles in the last 600 presses"
    w.t += 20
    w.sup.tick()
    assert w.procs[0].killed and w.merges == ["agent0-0.json"]
    assert any("slot 0 stalled: no new goal" in line and "[13, 2, 3]" in line for line in w.logs)
    row = json.loads((tmp_path / "runs" / "swarm" / "stalls.jsonl").read_text())
    assert row["slot"] == 0 and row["pos"] == [13, 2, 3]
    assert len(w.live()) == 1 and len(w.procs) == 2  # refilled with a fresh agent and a fresh watcher
    assert len(watchers) == 2


def test_claude_held_agent_is_not_killed_and_the_skip_is_logged_once(tmp_path):
    watchers = []
    w = World(tmp_path, n=1, watch=lambda cfg: watchers.append(FakeWatch()) or watchers[-1], watch_s=15.0)
    w.sup.tick()
    watchers[0].skipped = "claude hold"  # ProgressWatch.check() returns None and says why while a lease is on
    for _ in range(3):
        w.t += 20
        w.sup.tick()
    assert not w.procs[0].killed
    assert sum("stall check skipped: claude hold" in line for line in w.logs) == 1
    watchers[0].skipped = ""
    w.t += 20
    w.sup.tick()
    watchers[0].skipped = "claude hold"
    w.t += 20
    w.sup.tick()
    assert sum("stall check skipped: claude hold" in line for line in w.logs) == 2  # logged again for a new lease


def test_healthy_agent_not_stopped_and_watch_is_rate_limited(tmp_path):
    watchers = []
    w = World(tmp_path, n=1, watch=lambda cfg: watchers.append(FakeWatch()) or watchers[-1], watch_s=15.0)
    w.sup.tick()
    watchers[0].reason = "x"
    w.t += 5
    w.sup.tick()  # first look happened at t=0; the next is due at 15
    assert not w.procs[0].killed


def test_trivially_solved_segment_not_repicked_for_ten_minutes(tmp_path):
    w = World(tmp_path, n=1, segment=lambda n: ["a", "b"][n % 2])
    w.sup.tick()
    assert w.procs[0].cfg["segment"] == "a"
    w.end(w.procs[0], rc=0, after=5)  # segment a finished in 5 s: already solved
    w.sup.tick()
    assert w.procs[1].cfg["segment"] == "b" or w.procs[1].cfg["segment"] is None
    assert any("segment a finished in 5s (already solved)" in line for line in w.logs)
    w.end(w.procs[1], rc=0, after=100)
    w.sup.tick()
    assert w.procs[2].cfg["segment"] != "a"  # still inside the 10 minutes
    w.t += 700
    w.end(w.procs[2], rc=0, after=100)
    w.sup.tick()
    assert w.procs[3].cfg["segment"] in ("a", "b")


def test_grind_atlas_refresh_only_on_every_fifth_finish(tmp_path, monkeypatch):
    import pokeagent.grind.refresh as gr
    calls = []
    monkeypatch.setattr(gr, "refresh", lambda runs_dir, *a, **k: calls.append(runs_dir) or {"folded": 2})
    w = World(tmp_path, n=1)
    w.sup.tick()
    for _ in range(4):
        w.end(w.procs[-1])
        w.sup.tick()
    assert w.sup.finished == 4 and calls == []
    w.end(w.procs[-1])
    w.sup.tick()
    assert w.sup.finished == 5 and calls == [str(tmp_path)]
    assert any("grind atlas refreshed: 2 battles folded" in line for line in w.logs)


def test_grind_atlas_refresh_exception_is_logged_and_swallowed(tmp_path, monkeypatch):
    import pokeagent.grind.refresh as gr

    def boom(runs_dir, *a, **k):
        raise RuntimeError("atlas corrupt")

    monkeypatch.setattr(gr, "refresh", boom)
    w = World(tmp_path, n=1)
    w.sup.tick()
    for _ in range(5):
        w.end(w.procs[-1])
        w.sup.tick()  # must not raise
    assert w.sup.finished == 5 and len(w.procs) == 6
    assert any("grind atlas not refreshed" in line and "atlas corrupt" in line for line in w.logs)


def test_economy_refresh_only_on_every_fifth_finish(tmp_path, monkeypatch):
    import pokeagent.explorer.economy.atlas as ea
    calls = []
    monkeypatch.setattr(ea, "refresh", lambda runs_dir, *a, **k: calls.append(runs_dir) or {"battles": 1, "runs": 2, "offset": 3})
    w = World(tmp_path, n=1)
    w.sup.tick()
    for _ in range(4):
        w.end(w.procs[-1])
        w.sup.tick()
    assert w.sup.finished == 4 and calls == []
    w.end(w.procs[-1])
    w.sup.tick()
    assert w.sup.finished == 5 and calls == [str(tmp_path)]
    assert any("economy ledger refreshed" in line for line in w.logs)


def test_economy_refresh_exception_is_logged_and_swallowed(tmp_path, monkeypatch):
    import pokeagent.explorer.economy.atlas as ea

    def boom(runs_dir, *a, **k):
        raise RuntimeError("ledger corrupt")

    monkeypatch.setattr(ea, "refresh", boom)
    w = World(tmp_path, n=1)
    w.sup.tick()
    for _ in range(5):
        w.end(w.procs[-1])
        w.sup.tick()  # must not raise
    assert w.sup.finished == 5 and len(w.procs) == 6
    assert any("economy ledger not refreshed" in line and "ledger corrupt" in line for line in w.logs)
