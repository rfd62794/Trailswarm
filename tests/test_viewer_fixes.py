"""Review fixes: emulator-thread marshalling, source merge, web hardening, supervisor, concurrency."""
import threading
import time
import urllib.error
import urllib.request

import pytest

from pokeagent.adapters.bridge import EmuBridge
from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.sources import FakeSource
from test_viewer_agents import FRAME, _explorer_ctx, snap


# --- emulator thread marshalling ----------------------------------------------------

def test_bridge_runs_jobs_on_ticking_thread_and_caches():
    builds = []
    bridge = EmuBridge(lambda: builds.append(threading.get_ident()) or len(builds), every=3, timeout=2)
    emu_thread = threading.get_ident()
    out = {}
    t = threading.Thread(target=lambda: out.update(who=bridge.call(threading.get_ident)))
    t.start()
    while t.is_alive():
        bridge.tick()
        time.sleep(0.01)
    assert out["who"] == emu_thread                     # ran where tick() ran, not on the HTTP thread
    assert set(builds) == {emu_thread}                  # snapshots are built on the emulator thread
    first = bridge.snapshot()
    assert bridge.snapshot() == first                   # served from cache between refreshes


def test_bridge_timeout_returns_error_and_skips_late_job():
    ran = []
    bridge = EmuBridge(lambda: 0, timeout=0.05)
    out = bridge.wrap(lambda **_: ran.append(1) or {})()
    assert "error" in out
    bridge.pump()
    assert ran == []                                    # cancelled job must not fire after the timeout


def test_explorer_handlers_marshalled(tmp_path):
    from pokeagent.adapters.explorer_snapshot import ExplorerAgentView
    from pokeagent.explorer.engine import Engine
    ctx, emu, mem, presser = _explorer_ctx(tmp_path)
    view = ExplorerAgentView(ctx, emu, mem, Engine(ctx, presser), presser, agent_id="m1", root=tmp_path)
    caller = threading.get_ident()
    seen = []
    orig = presser.press
    presser.press = lambda *a, **k: (seen.append(threading.get_ident()), orig(*a, **k))[1]
    res = {}
    t = threading.Thread(target=lambda: res.update(press=view.handlers()["press"](button="A", source="human"),
                                                  snap=view.snapshot()))
    t.start()
    while t.is_alive():
        view.tick()
        time.sleep(0.005)
    assert seen == [caller]                             # press executed on the pumping (emulator) thread
    assert isinstance(res["snap"], AgentSnapshot)
    assert view.snapshot().human_hold is True           # cache refreshed right after the command
    # nobody ticking -> timeout surfaces as an error dict, not a hang or a direct emulator touch
    view.bridge.timeout = 0.05
    assert "error" in view.handlers()["pause"]() and ctx.paused is False


def test_control_server_maps_error_to_504():
    from pokeagent.control_server import ControlServer
    srv = ControlServer(lambda: None, {"pause": lambda **_: {"error": "busy"}}, token="")
    assert srv.dispatch({"cmd": "pause"}) == (504, {"error": "busy", "ok": False})


def test_rl_snapshot_cached_from_trainer_thread(tmp_path):
    from pokeagent.adapters.rl_snapshot import RlAgentView
    from test_viewer_agents import _FakeRlEnv
    reads = []
    env = _FakeRlEnv()
    orig = env._obs
    env._obs = lambda: (reads.append(threading.get_ident()), orig())[1]
    view = RlAgentView(env, tmp_path / "s.json", agent_id="r", refresh_every=2)
    view.tick()                                          # trainer thread builds
    http = threading.Thread(target=lambda: [view.snapshot() for _ in range(5)])
    http.start()
    http.join()
    assert set(reads) == {threading.get_ident()}         # HTTP thread never read the env


# --- poller discovery ---------------------------------------------------------------

def test_merge_sources_over_cycles():
    from pokeagent.viewer.app import _Throttle, merge_sources
    cur: dict = {}
    a, b, c = FakeSource("a"), FakeSource("b"), FakeSource("c")
    assert merge_sources(cur, {"a": a, "b": b}) == (["a", "b"], [])
    ta = cur["a"]
    assert isinstance(ta, _Throttle)
    for _ in range(3):                                   # steady state: identities are kept
        assert merge_sources(cur, {"a": a, "b": b}) == ([], [])
        assert cur["a"] is ta
    assert merge_sources(cur, {"a": a, "c": c}) == (["c"], ["b"])
    assert set(cur) == {"a", "c"} and cur["a"] is ta


def test_poller_keeps_agents_across_rediscovery(monkeypatch):
    from pokeagent.viewer import app
    entries = {"x": {"id": "x"}, "y": {"id": "y"}}
    monkeypatch.setattr(app, "_sources_for", lambda root, fake: (
        {k: FakeSource(k, [snap(k)], [FRAME]) for k in entries}, dict(entries)))
    seen_ids = []

    class Win:
        def __init__(self, model, sources, **kw):
            self.model, self.sources = model, sources

        def run(self):
            time.sleep(1.0)                              # >= 2 rediscoveries (every 60 ticks at 120 fps)
            seen_ids.extend(self.model.ids())
            seen_ids.append(sorted(self.sources))

    import pokeagent.viewer.ui.window as w
    monkeypatch.setattr(w, "ViewerWindow", Win)
    app.run(".", fps=120)
    assert seen_ids == ["x", "y", ["x", "y"]]


# --- web hardening ------------------------------------------------------------------

def test_web_host_check_and_no_innerhtml():
    from pokeagent.viewer import web
    from pokeagent.viewer.model import ViewerModel
    assert "innerHTML" not in web._PAGE and "textContent" in web._PAGE
    model = ViewerModel()
    model.poll([FakeSource("a1", [snap("a1")], [FRAME])])
    httpd = web.make_server(model, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        ok = urllib.request.Request(f"http://127.0.0.1:{port}/data")
        assert urllib.request.urlopen(ok, timeout=5).status == 200
        for host in ("evil.example", f"evil.example:{port}", "127.0.0.1"):
            bad = urllib.request.Request(f"http://127.0.0.1:{port}/data", headers={"Host": host})
            with pytest.raises(urllib.error.HTTPError) as ei:
                urllib.request.urlopen(bad, timeout=5)
            assert ei.value.code == 403
        loc = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": f"localhost:{port}"})
        assert urllib.request.urlopen(loc, timeout=5).status == 200
    finally:
        httpd.shutdown()
        httpd.server_close()


# --- supervisor ---------------------------------------------------------------------

def test_supervisor_refuses_foreign_pid(monkeypatch):
    import os
    from pokeagent.supervisor import Supervisor
    killed = []
    monkeypatch.setattr(os, "kill", lambda *a: killed.append(a))
    sup = Supervisor()
    assert sup.stop(os.getpid()) is False and killed == []

    class P:
        terminated = False

        def terminate(self):
            self.terminated = True
    p = P()
    sup._procs[4242] = p
    assert sup.stop(4242) is True and p.terminated and killed == []


# --- UI sends off the UI thread ------------------------------------------------------

def test_window_sends_on_worker_thread():
    pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.ui.window import ViewerWindow
    threads = []

    class Src(FakeSource):
        def send(self, cmd, **args):
            threads.append(threading.get_ident())
            time.sleep(0.2)
            return super().send(cmd, **args)
    model = ViewerModel()
    src = Src("a", [snap("a")], [FRAME])
    model.poll([src])
    win = ViewerWindow(model, {"a": src})
    win.selected = "a"; win.toggle_focus("a")
    t0 = time.monotonic()
    win.send_to_targets("pause")
    win.key_button("Up")
    assert time.monotonic() - t0 < 0.1                   # caller returned without waiting on send
    win.flush_sends()
    assert [c for c, _ in src.sent] == ["steer", "pause", "press"] and threads[0] != threading.get_ident()


# --- concurrent polling -------------------------------------------------------------

def test_poll_hung_agent_does_not_starve_live_ones():
    from pokeagent.viewer.model import ViewerModel

    class Hung(FakeSource):
        def snapshot(self):
            time.sleep(0.5)
            return None
    model = ViewerModel()
    live = [FakeSource(f"l{i}", [snap(f"l{i}")], [FRAME]) for i in range(3)]
    srcs = [Hung("h1"), Hung("h2"), *live]
    t0 = time.monotonic()
    model.poll(srcs)
    assert time.monotonic() - t0 < 0.9                   # parallel: ~0.5 s, not 1.0 s+
    assert all(model.snapshot(f"l{i}") is not None for i in range(3))


def test_dead_agents_retried_rarely():
    from pokeagent.viewer.model import DEAD_AFTER, DEAD_EVERY, ViewerModel
    calls = []

    class Dead(FakeSource):
        def snapshot(self):
            calls.append(1)
            return None
    model, d = ViewerModel(), Dead("d")
    for _ in range(DEAD_AFTER + DEAD_EVERY * 2):
        model.poll([d])
    assert len(calls) < DEAD_AFTER + 4


def test_explorer_sees_has_rows(tmp_path):
    from pokeagent.adapters.explorer_snapshot import ExplorerAgentView
    from pokeagent.explorer.engine import Engine
    ctx, emu, mem, presser = _explorer_ctx(tmp_path)
    view = ExplorerAgentView(ctx, emu, mem, Engine(ctx, presser), presser, agent_id="s1", root=tmp_path,
                             marshal=False)
    sees = view.snapshot().sees
    assert sees.mode == "overworld" and len(sees.rows) >= 9     # 9 map rows (+ legend), not an empty Sees()


def test_toggle_pause_sends_pause_first():
    pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.ui.window import ViewerWindow
    model, src = ViewerModel(), FakeSource("a", [snap("a")], [FRAME])
    model.poll([src])
    win = ViewerWindow(model, {"a": src})
    win.selected = "a"
    win.toggle_pause()
    win.toggle_pause()
    win.flush_sends()
    assert [c for c, _ in src.sent] == ["pause", "resume"]


def test_theme_builds_under_context():
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.ui import theme
    dpg.create_context()
    try:
        theme.apply()                                    # raised "Incompatible parent" before the fix
    finally:
        dpg.destroy_context()
