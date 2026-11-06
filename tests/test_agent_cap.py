import os
import subprocess
import sys

import pytest

from pokeagent import supervisor as sv
from pokeagent.agent_registry import register
from pokeagent.viewer.view_cap import SpawnGuard, clamp_view_max, page_ids


class _P:
    pid = os.getpid()

    def poll(self):
        return None


def test_supervisor_refuses_beyond_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    register(tmp_path, "a", "explorer", 1, "s", pid=os.getpid())
    sup = sv.Supervisor(tmp_path, limits={"cap": 1, "free_mb": 64000, "cpus": 16, "rss_mb": 350})
    with pytest.raises(sv.SpawnRefused) as e:
        sup.spawn("explorer")
    assert "max 1" in str(e.value)


def test_supervisor_spawns_under_cap_and_counts_pending(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: started.append(argv) or _P())
    sup = sv.Supervisor(tmp_path, limits={"cap": 1, "free_mb": 64000, "cpus": 16, "rss_mb": 350})
    sup.spawn("explorer")
    assert len(started) == 1
    with pytest.raises(sv.SpawnRefused):  # first agent has not registered yet but is alive: still counts
        sup.spawn("explorer")
    assert len(started) == 1


def test_spawn_guard_debounce_and_inflight():
    t = [100.0]
    g = SpawnGuard(clock=lambda: t[0])
    assert g.begin() is True
    assert g.begin() is False  # in flight
    g.end()
    assert g.begin() is False  # inside 2 s debounce
    t[0] += 2.1
    assert g.begin() is True


def test_page_ids_caps_and_cycles():
    ids = [f"a{i}" for i in range(11)]
    vis, more, page = page_ids(ids, 8, 0)
    assert vis == ids[:8] and more == 3 and page == 0
    vis, more, page = page_ids(ids, 8, 1)
    assert vis == ids[8:] and more == 8 and page == 1
    vis, more, page = page_ids(ids, 8, 2)  # wraps
    assert vis == ids[:8] and page == 0
    assert page_ids(ids[:5], 8, 3) == (ids[:5], 0, 0)
    assert page_ids([], 8, 0) == ([], 0, 0)


def test_clamp_view_max():
    assert clamp_view_max(3) == 6 and clamp_view_max(20) == 12 and clamp_view_max(8) == 8
    assert clamp_view_max("x") == 8


def _load_tool(name):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"tool_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_swarm_clips_to_room(tmp_path):
    swarm = _load_tool("swarm")
    register(tmp_path, "a", "explorer", 1, "s", pid=os.getpid())
    n, why = swarm.plan_agents(tmp_path, 4, cap=3, free_mb=64000, cpus=16, rss_mb=350)
    assert n == 2 and "max 3" in why
    n, _ = swarm.plan_agents(tmp_path, 4, cap=1, free_mb=64000, cpus=16, rss_mb=350)
    assert n == 0


def test_overnight_clips_agents():
    overnight = _load_tool("overnight")
    assert overnight.round_agents(8, cap=6, free_mb=64000, cpus=16, rss_mb=350) == 6
    assert overnight.round_agents(8, cap=6, free_mb=100, cpus=16, rss_mb=350) == 1


def test_page_ids_pins_selected_agent():
    ids = [f"a{i}" for i in range(11)]
    vis, more, _ = page_ids(ids, 8, 0, pin="a10")
    assert "a10" in vis and len(vis) == 8 and more == 3
    vis, _, _ = page_ids(ids, 8, 1, pin="a10")  # already on this page: unchanged
    assert vis == ids[8:]
    vis, _, _ = page_ids(ids, 8, 1, pin="a0")
    assert "a0" in vis and len(vis) == 3
    assert page_ids(ids, 8, 0, pin="zzz")[0] == ids[:8]  # unknown pin ignored


def test_spawn_control_message_when_swarm_holds_lock(tmp_path):
    from pokeagent.viewer.spawn_control import SpawnControl
    register(tmp_path, "a", "explorer", 1, "s", pid=os.getpid())
    sup = sv.Supervisor(tmp_path, limits={"cap": 6, "free_mb": 64000, "cpus": 16, "rss_mb": 350})
    t = [0.0]
    ctl = SpawnControl(sup, tmp_path, clock=lambda: t[0], limits=sup._limits)
    from pokeagent import resources
    with resources.spawn_lock(tmp_path):
        ctl.refresh(force=True)
        assert ctl.capped and "swarm is running (1 agents)" in ctl.message
        assert "spawning disabled until it ends" in ctl.message


def test_spawn_control_caches_status(tmp_path):
    from pokeagent.viewer.spawn_control import SpawnControl
    calls = []
    t = [0.0]
    ctl = SpawnControl(None, tmp_path, clock=lambda: t[0], probe=lambda root, **k: calls.append(1) or (0, 6, 6))
    ctl.refresh(force=True)
    ctl.refresh(); ctl.refresh()
    assert len(calls) == 1 and ctl.capped and "agent limit" in ctl.message
    t[0] += 2.1
    ctl.refresh(force=True)
    assert len(calls) == 2
