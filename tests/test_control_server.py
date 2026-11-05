import json
import urllib.error
import urllib.request

import pytest

from pokeagent.control_server import COMMAND_ARGS, ControlServer
from pokeagent.snapshot import AgentSnapshot


TOKEN = "tok"


def post(port, body, headers=None, token=TOKEN):
    h = {"Content-Type": "application/json", "X-PokeAgent-Token": token}
    h.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{port}/command", data=body if isinstance(body, bytes)
                                 else json.dumps(body).encode(), method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get_req(port, **headers):
    return urllib.request.Request(f"http://127.0.0.1:{port}/snapshot", headers={"X-PokeAgent-Token": TOKEN, **headers})


def get_code(req):
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


@pytest.fixture
def server():
    calls = []
    def make(name):
        return lambda **kw: calls.append((name, kw)) or {"got": kw}
    handlers = {name: make(name) for name in COMMAND_ARGS}

    def boom(**kw):
        raise RuntimeError("kaboom")
    handlers["load_state"] = boom
    srv = ControlServer(lambda: AgentSnapshot(agent_id="x", step=7), handlers, token=TOKEN)
    port = srv.start()
    yield port, calls
    srv.stop()


def test_snapshot(server):
    port, _ = server
    with urllib.request.urlopen(get_req(port), timeout=2) as r:
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


def test_generated_token():
    srv = ControlServer(lambda: AgentSnapshot(agent_id="x"), {})
    assert len(srv.token) >= 24 and srv.token != ControlServer(lambda: None, {}).token


def test_token_required(server):
    port, calls = server
    assert get_code(urllib.request.Request(f"http://127.0.0.1:{port}/snapshot")) == 403
    assert get_code(get_req(port, **{"X-PokeAgent-Token": "wrong"})) == 403
    assert post(port, {"cmd": "pause"}, token="wrong") == (403, {"ok": False, "error": "forbidden"})
    assert post(port, {"cmd": "pause"}, token="")[0] == 403
    assert calls == []


def test_origin_and_host_rejected(server):
    port, calls = server
    assert get_code(get_req(port, Origin="http://evil.example")) == 403
    assert post(port, {"cmd": "pause"}, headers={"Origin": "http://evil.example"})[0] == 403
    assert post(port, {"cmd": "pause"}, headers={"Host": "evil.example"})[0] == 403
    assert post(port, {"cmd": "pause"}, headers={"Host": f"evil.example:{port}"})[0] == 403
    assert get_code(get_req(port, Host=f"localhost:{port}")) == 200
    assert calls == []


def test_content_type_required(server):
    port, calls = server
    assert post(port, {"cmd": "pause"}, headers={"Content-Type": "text/plain"})[0] == 415
    assert post(port, {"cmd": "pause"}, headers={"Content-Type": "application/json; charset=utf-8"})[0] == 200
    assert len(calls) == 1


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "", "x" * 65, "a b", "a.b"])
def test_state_name_validated(server, name):
    port, calls = server
    for cmd in ("save_state", "load_state"):
        assert post(port, {"cmd": cmd, "name": name})[0] == 400
    assert calls == []


def raw_post(port, head_extra, body=b""):
    import socket
    req = (f"POST /command HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-PokeAgent-Token: {TOKEN}\r\n"
           f"Content-Type: application/json\r\n{head_extra}\r\n").encode() + body
    with socket.create_connection(("127.0.0.1", port), timeout=3) as c:
        c.sendall(req)
        return int(c.recv(200).split()[1])


@pytest.mark.parametrize("cl", ["abc", "-1", "65537"])
def test_bad_content_length(server, cl):
    port, calls = server
    assert raw_post(port, f"Content-Length: {cl}\r\n") == 400
    assert calls == []


def test_error_replies_with_body_are_stable(server):
    port, _ = server
    for _ in range(30):
        assert post(port, {"cmd": "pause"}, headers={"Content-Type": "text/plain"})[0] == 415
        assert post(port, {"cmd": "pause"}, token="bad")[0] == 403
