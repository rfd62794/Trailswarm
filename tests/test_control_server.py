import json
import urllib.error
import urllib.request

import pytest

from pokeagent.control_server import COMMAND_ARGS, ControlServer
from pokeagent.snapshot import AgentSnapshot


def post(port, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/command", data=body if isinstance(body, bytes)
                                 else json.dumps(body).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def server():
    calls = []
    def make(name):
        return lambda **kw: calls.append((name, kw)) or {"got": kw}
    handlers = {name: make(name) for name in COMMAND_ARGS}

    def boom(**kw):
        raise RuntimeError("kaboom")
    handlers["load_state"] = boom
    srv = ControlServer(lambda: AgentSnapshot(agent_id="x", step=7), handlers)
    port = srv.start()
    yield port, calls
    srv.stop()


def test_snapshot(server):
    port, _ = server
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/snapshot", timeout=2) as r:
        d = json.loads(r.read())
    assert d["agent_id"] == "x" and d["step"] == 7


@pytest.mark.parametrize("body,expect", [
    ({"cmd": "pause"}, ("pause", {})),
    ({"cmd": "resume"}, ("resume", {})),
    ({"cmd": "hold_release"}, ("hold_release", {})),
    ({"cmd": "speed", "n": 4}, ("speed", {"n": 4})),
    ({"cmd": "press", "button": "A"}, ("press", {"button": "A", "source": "human"})),
    ({"cmd": "press", "button": "UP", "source": "rl"}, ("press", {"button": "UP", "source": "rl"})),
    ({"cmd": "steer", "on": True}, ("steer", {"on": True})),
    ({"cmd": "hand_to", "driver": "rl"}, ("hand_to", {"driver": "rl"})),
    ({"cmd": "save_state", "name": "s1"}, ("save_state", {"name": "s1"})),
])
def test_commands_reach_handlers(server, body, expect):
    port, calls = server
    code, out = post(port, body)
    assert code == 200 and out["ok"] is True
    assert calls[-1] == expect


def test_errors(server):
    port, calls = server
    code, out = post(port, {"cmd": "nope"})
    assert code == 400 and out == {"ok": False, "error": "unknown command nope"}
    for bad in ({"cmd": "speed", "n": 3}, {"cmd": "speed", "n": "4"}, {"cmd": "speed"},
                {"cmd": "press", "button": "X"}, {"cmd": "steer", "on": 1}, {"cmd": "pause", "extra": 1}):
        code, out = post(port, bad)
        assert code == 400 and out["ok"] is False, bad
    assert post(port, b"{not json")[0] == 400
    assert calls == []
    code, out = post(port, {"cmd": "load_state", "name": "s"})
    assert code == 500 and out == {"ok": False, "error": "kaboom"}
