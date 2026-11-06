import json
import os

import pytest

from pokeagent import resources as R
from pokeagent.agent_registry import list_agents, register


def test_max_agents_ram_bound():
    # (8000 free - 2048 reserve) // 350 = 17 -> cap 6 wins; with 3000 free: 952 // 350 = 2
    assert R.max_agents(free_mb=8000, cpus=16, rss_mb=350) == 6
    assert R.max_agents(free_mb=3000, cpus=16, rss_mb=350) == 2


def test_max_agents_cpu_bound_and_floor():
    assert R.max_agents(free_mb=64000, cpus=4, rss_mb=350, cap=20) == 2  # cpus - 2
    assert R.max_agents(free_mb=100, cpus=1, rss_mb=350) == 1  # never below one


def test_max_agents_cap_arg_and_env(monkeypatch):
    assert R.max_agents(cap=3, free_mb=64000, cpus=16, rss_mb=350) == 3
    monkeypatch.setenv("POKEAGENT_MAX_AGENTS", "4")
    assert R.max_agents(free_mb=64000, cpus=16, rss_mb=350) == 4


def test_max_agents_uses_measured_rss(tmp_path):
    R.save_rss(tmp_path, 900.0)
    assert R.load_rss(tmp_path) == 900.0
    # 6000 free: (6000-2048)//900 = 4
    assert R.max_agents(root=tmp_path, free_mb=6000, cpus=16) == 4
    assert R.load_rss(tmp_path / "nope") == R.DEFAULT_RSS_MB


def test_measure_rss_median_of_live_agents(tmp_path):
    register(tmp_path, "a", "explorer", 1, "s", pid=os.getpid())
    register(tmp_path, "b", "explorer", 2, "s", pid=os.getpid())
    sizes = {os.getpid(): 400.0}
    got = R.measure_agent_rss(tmp_path, reader=lambda pid: sizes.get(pid))
    assert got == 400.0
    data = json.loads((tmp_path / "runs" / "resources.json").read_text())
    assert data["per_agent_rss_mb"] == 400.0 and data["samples"] == 2
    assert R.measure_agent_rss(tmp_path, reader=lambda pid: None) is None


def test_live_agent_count_counts_registry_not_processes(tmp_path):
    register(tmp_path, "a", "explorer", 1, "s", pid=os.getpid())
    register(tmp_path, "b", "explorer", 2, "s", pid=2 ** 22 + 12345)  # dead
    assert R.live_agent_count(tmp_path) == 1


def test_room_for_clips_and_explains(tmp_path):
    register(tmp_path, "a", "explorer", 1, "s", pid=os.getpid())
    n, why = R.room_for(5, root=tmp_path, cap=3, free_mb=64000, cpus=16, rss_mb=350)
    assert n == 2 and "max 3" in why and "1 live" in why and "processes" in why
    n, _ = R.room_for(1, root=tmp_path, cap=1, free_mb=64000, cpus=16, rss_mb=350)
    assert n == 0


def test_lock_excludes_second_holder_and_steals_stale(tmp_path):
    with R.spawn_lock(tmp_path):
        with pytest.raises(R.LockBusy):
            with R.spawn_lock(tmp_path, wait_s=0.2):
                pass
    with R.spawn_lock(tmp_path):  # released
        pass
    lock = tmp_path / "runs" / "spawn.lock"
    lock.write_text("999999999", encoding="utf-8")  # dead pid
    with R.spawn_lock(tmp_path):
        pass


def test_registry_prunes_dead_files(tmp_path):
    register(tmp_path, "dead", "rl", 1, "s", pid=2 ** 22 + 777)
    register(tmp_path, "live", "rl", 2, "s", pid=os.getpid())
    assert [e["id"] for e in list_agents(tmp_path)] == ["live"]
    assert not (tmp_path / "runs" / "agents" / "dead.json").exists()


def test_register_removes_stale_same_port(tmp_path):
    register(tmp_path, "old", "explorer", 8801, "s", pid=2 ** 22 + 5)
    register(tmp_path, "new", "explorer", 8801, "s", pid=os.getpid())
    assert not (tmp_path / "runs" / "agents" / "old.json").exists()
    assert [e["id"] for e in list_agents(tmp_path)] == ["new"]


@pytest.mark.skipif(os.name != "nt", reason="Windows memory API")
def test_real_rss_reader_reads_own_process():
    mb = R.process_rss_mb(os.getpid())
    assert mb is not None and mb > 5


def test_prune_keeps_file_when_process_state_unknown(tmp_path, monkeypatch):
    from pokeagent import agent_registry as ar
    register(tmp_path, "denied", "rl", 1, "s", pid=4242)
    register(tmp_path, "gone", "rl", 2, "s", pid=4243)
    monkeypatch.setattr(ar, "process_state", lambda pid: "unknown" if pid == 4242 else "gone")
    assert [e["id"] for e in ar.list_agents(tmp_path)] == ["denied"]  # access denied: still counted, kept
    d = tmp_path / "runs" / "agents"
    assert (d / "denied.json").exists() and not (d / "gone.json").exists()


def test_process_state_real():
    from pokeagent.registry import process_state
    assert process_state(os.getpid()) == "alive"
    assert process_state(2 ** 22 + 99991) == "gone"


def test_room_for_ram_not_double_counted(tmp_path):
    for i in range(2):
        register(tmp_path, f"a{i}", "explorer", i, "s", pid=os.getpid())
    # free RAM already reflects the 2 live agents: (4500-2048)//350 = 7 more fit; cpu room = 16-2-2 = 12; cap 10-2 = 8
    n, _ = R.room_for(20, root=tmp_path, cap=10, free_mb=4500, cpus=16, rss_mb=350)
    assert n == 7
    # cpu room subtracts live: 6 cpus - 2 - 2 live = 2
    n, _ = R.room_for(20, root=tmp_path, cap=10, free_mb=64000, cpus=6, rss_mb=350)
    assert n == 2


def test_first_agent_always_allowed(tmp_path):
    n, _ = R.room_for(3, root=tmp_path, cap=6, free_mb=10, cpus=1, rss_mb=350)
    assert n == 1


def test_lock_takeover_is_exclusive(tmp_path):
    import threading
    import time as _t
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "spawn.lock").write_text("999999999", encoding="utf-8")  # stale
    holders, worst, errs = [0], [0], []

    def worker():
        try:
            with R.spawn_lock(tmp_path, wait_s=10):
                holders[0] += 1
                worst[0] = max(worst[0], holders[0])
                _t.sleep(0.05)
                holders[0] -= 1
        except Exception as e:  # pragma: no cover
            errs.append(e)
    ts = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and worst[0] == 1
    assert not list((tmp_path / "runs").glob("spawn.lock*"))  # no tombstones left behind


def test_lock_held(tmp_path):
    assert R.lock_held(tmp_path) is False
    with R.spawn_lock(tmp_path):
        assert R.lock_held(tmp_path) is True
    assert R.lock_held(tmp_path) is False
