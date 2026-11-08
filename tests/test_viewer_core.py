import time

from pokeagent.control_server import ControlServer
from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.commands import KEYMAP, next_speed, press_for_key, targets
from pokeagent.viewer.layout import CARD_ASPECT, FocusState, grid
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.sources import FakeSource, HttpShmSource, discover
from pokeagent.agent_registry import register


def test_http_source_live_and_closed():
    got = []
    srv = ControlServer(lambda: AgentSnapshot(agent_id="h", step=3),
                        {"pause": lambda: got.append("p") or {}}, token="tk")
    port = srv.start()
    try:
        assert HttpShmSource({"id": "h", "port": port, "frame_slot": "", "token": "bad"}).snapshot() is None
        src = HttpShmSource({"id": "h", "port": port, "frame_slot": "", "token": "tk"})
        assert src.snapshot().step == 3
        assert src.frame() is None
        assert src.send("pause")["ok"] is True and got == ["p"]
        assert src.send("nope")["ok"] is False
    finally:
        srv.stop()
    dead = HttpShmSource({"id": "h", "port": port, "frame_slot": "pokeagent_frames_h"})
    t = time.time()
    assert dead.snapshot() is None
    assert time.time() - t < 1.0
    t = time.time()
    assert dead.send("pause")["ok"] is False
    assert time.time() - t < 1.0


def test_discover(tmp_path):
    register(tmp_path, "d1", "rl", 1234, "pokeagent_frames_d1")
    assert [s.agent_id for s in discover(tmp_path)] == ["d1"]


def test_fake_source_records():
    f = FakeSource("f", [AgentSnapshot(agent_id="f", step=1), AgentSnapshot(agent_id="f", step=2)])
    assert [f.snapshot().step for _ in range(3)] == [1, 2, 2]
    f.send("speed", n=2)
    assert f.sent == [("speed", {"n": 2})]


def test_model_staleness():
    t = [100.0]
    m = ViewerModel(clock=lambda: t[0])
    m.set_wants(frames={"a": 10.0})                       # frames only for agents the views declared
    f = FakeSource("a", [AgentSnapshot(agent_id="a")], [(b"x", 1, 1)])
    assert m.staleness("a") == "lost"
    m.poll([f]); m.drain()
    assert m.staleness("a") == "live" and m.frame("a") == (b"x", 1, 1)
    t[0] = 102.5
    assert m.staleness("a") == "stale"
    t[0] = 111.0
    assert m.staleness("a") == "lost"
    s = m.snapshot("a")
    s.step = 99
    assert m.snapshot("a").step == 0  # copies
    m.poll([FakeSource("a")]); m.drain()  # failed poll keeps last snapshot, does not refresh
    assert m.snapshot("a") is not None and m.staleness("a") == "lost"
    assert m.ids() == ["a"]


def test_grid_maximal():
    aw, ah = CARD_ASPECT
    ratio = ah / aw  # card_h / card_w = 63/80 (two 10:9 panels over a 0.75-frame text block)
    for n in range(1, 13):
        cols, rows, w, h = grid(n, 1920, 1000)
        assert cols * rows >= n and cols * w <= 1920 and rows * h <= 1000
        assert abs(w * ah - h * aw) <= aw  # cards keep the 80:63 aspect (int rounding)
        for c in range(1, n + 1):
            r = -(-n // c)
            cw = int(min(1920 / c, 1000 / (r * ratio)))
            assert w * h >= cw * int(cw * ratio)
    assert grid(1, 1920, 1000)[0] == 1
    assert grid(0, 1920, 1000) == (0, 0, 0, 0)


def test_grid_columns():
    cols = {n: grid(n, 1920, 1000)[0] for n in range(1, 13)}
    assert cols == {1: 1, 2: 2, 3: 3, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 3, 10: 4, 11: 4, 12: 4}


def test_focus_toggle():
    f = FocusState()
    assert f.focused is None
    f.toggle("a")
    assert f.focused == "a"
    f.toggle("b")
    assert f.focused == "b"
    f.toggle("b")
    assert f.focused is None
    f.focus("c")
    f.back()
    assert f.focused is None


def test_commands():
    assert press_for_key("Return", True) == "START" and press_for_key("Return", False) is None
    assert press_for_key("z", True) is None and KEYMAP["s"] == "B"
    assert targets("a", ["a", "b"], "selected") == ["a"] and targets(None, ["a"], "selected") == []
    assert targets("a", ["a", "b"], "all") == ["a", "b"]
    assert [next_speed(x) for x in (1, 2, 4, 8, 3)] == [2, 4, 8, 1, 1]


def test_model_forget_and_prune():
    t = [0.0]
    m = ViewerModel(clock=lambda: t[0])
    m.set_wants(frames={"a": 10.0})
    m.poll([FakeSource("a", [AgentSnapshot(agent_id="a")], [(b"x", 1, 1)]),
            FakeSource("b", [AgentSnapshot(agent_id="b")])]); m.drain()
    t[0] = 50.0
    m.poll([FakeSource("b", [AgentSnapshot(agent_id="b")])]); m.drain()
    t[0] = 61.0
    assert m.prune() == ["a"] and m.ids() == ["b"]
    assert m.snapshot("a") is None and m.frame("a") is None
    t[0] = 200.0
    assert m.prune(after_s=500) == []
    m.forget("b")
    m.forget("b")
    assert m.ids() == []


def test_refresh_sources_forgets_exited_agents_immediately():
    from pokeagent.viewer.app import refresh_sources
    from pokeagent.viewer.model import ViewerModel
    m = ViewerModel()
    m._last_ok.update({"a": 1.0, "b": 1.0})  # both seen once
    holder = {"sources": {"a": object(), "b": object()}, "entries": {"a": {}, "b": {}}}
    gone = refresh_sources(holder, m, {"a": object()}, {"a": {"id": "a"}})
    assert gone == ["b"] and m.ids() == ["a"] and list(holder["sources"]) == ["a"] and list(holder["entries"]) == ["a"]


def test_refresh_sources_drops_dead_agents_from_the_world_view():
    from pokeagent.viewer.app import refresh_sources
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.world.model import WorldModel
    w = WorldModel()
    for aid in ("a", "b", "old"):
        w.ingest(aid, [])
    holder = {"sources": {"a": object(), "b": object()}, "entries": {}}
    refresh_sources(holder, ViewerModel(), {"a": object()}, {"a": {"id": "a"}}, w)
    assert w.ids() == ["a"]
