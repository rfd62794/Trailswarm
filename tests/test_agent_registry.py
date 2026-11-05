import subprocess
import sys

from pokeagent.agent_registry import list_agents, register, unregister


def test_register_list_unregister(tmp_path):
    p = register(tmp_path, "b", "rl", 8801, "pokeagent_frames_b")
    register(tmp_path, "a", "explorer", 8800, "pokeagent_frames_a")
    assert p.exists() and not list(p.parent.glob("*.tmp"))
    es = list_agents(tmp_path)
    assert [e["id"] for e in es] == ["a", "b"] and es[0]["port"] == 8800
    unregister(tmp_path, "a")
    unregister(tmp_path, "a")
    assert [e["id"] for e in list_agents(tmp_path)] == ["b"]


def test_dead_pid_and_garbage_dropped(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    register(tmp_path, "dead", "rl", 1, "s", pid=proc.pid)
    (tmp_path / "runs" / "agents" / "bad.json").write_text("{nope", encoding="utf-8")
    assert list_agents(tmp_path) == []


def test_missing_dir(tmp_path):
    assert list_agents(tmp_path) == []


def test_token_written(tmp_path):
    import json
    import os
    p = register(tmp_path, "t", "rl", 1, "s", token="secret")
    assert json.loads(p.read_text())["token"] == "secret"
    assert list_agents(tmp_path)[0]["token"] == "secret"
    if os.name != "nt":
        assert p.stat().st_mode & 0o777 == 0o600
