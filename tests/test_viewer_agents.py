"""Viewer agents: explorer/RL adapters, supervisor argv, web routes, UI smoke, CLI help."""
import json
import urllib.request
from pathlib import Path

import pytest

from pokeagent.snapshot import AgentSnapshot, Event, Goal, Screen, Sees, Segment, Thinking
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.sources import FakeSource


def snap(aid: str, **kw) -> AgentSnapshot:
    base = dict(agent_id=aid, kind="explorer", state="running", step=3,
                segment=Segment(id="S1", name="seg", steps=3),
                goals=[Goal(id="g", name="g", status="current")],
                thinking=Thinking(want="w", plan="p", driver="explorer", button="A", result="ok"),
                sees=Sees(rows=["~~@~~"], mode="overworld"), screen=Screen(), recent=[])
    base.update(kw)
    return AgentSnapshot(**base)


FRAME = (bytes(range(256)) * 270, 160, 144)  # 69120 bytes = 160*144*3 RGB


# --- explorer adapter ---------------------------------------------------------

def _explorer_ctx(tmp_path):
    from pokeagent.emulator import FakeEmulator
    from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
    from pokeagent.explorer.memory import MapMemory
    from pokeagent.explorer.press import Presser
    emu = FakeEmulator({0xD35E: 0x26, 0xD367: 0})
    mem = MapMemory(tmp_path / "maps.json")
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path)
    ctx.trans = open(tmp_path / "transitions.jsonl", "a", encoding="utf-8")  # presser writes one line per press
    return ctx, emu, mem, Presser(ctx)


def test_explorer_adapter_snapshot_and_hold(tmp_path):
    from pokeagent.adapters.explorer_snapshot import ExplorerAgentView
    from pokeagent.explorer.engine import Engine
    ctx, emu, mem, presser = _explorer_ctx(tmp_path)
    engine = Engine(ctx, presser)
    view = ExplorerAgentView(ctx, emu, mem, engine, presser, agent_id="ex1", root=tmp_path, marshal=False)
    s = view.snapshot()
    assert s.agent_id == "ex1" and s.kind == "explorer" and s.state == "running"
    assert s.sees is not None and s.screen is not None and s.thinking.driver == "explorer"
    # human press -> 3s hold -> snapshot reports it; agent-side hold_release clears it
    view.handlers()["press"](button="A", source="human")
    assert view.hold.active() and view.snapshot().human_hold is True
    assert emu.presses, "presser should have pressed a button"
    view.handlers()["hold_release"]()
    assert not view.hold.active()
    # pause/resume/speed map onto ctx fields
    view.handlers()["pause"](); assert ctx.paused is True
    view.handlers()["resume"](); assert ctx.paused is False
    view.handlers()["speed"](n=4); assert ctx.speed == 4
    view.close()


def test_explorer_adapter_serve_registers(tmp_path):
    from pokeagent.adapters.explorer_snapshot import ExplorerAgentView
    from pokeagent.agent_registry import list_agents
    from pokeagent.explorer.engine import Engine
    ctx, emu, mem, presser = _explorer_ctx(tmp_path)
    engine = Engine(ctx, presser)
    view = ExplorerAgentView(ctx, emu, mem, engine, presser, agent_id="ex2", root=tmp_path, marshal=False)
    port = view.serve(port=0)
    try:
        entries = list_agents(tmp_path)
        assert [e["id"] for e in entries] == ["ex2"] and entries[0]["port"] == port
        body = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"http://127.0.0.1:{port}/snapshot",
                                   headers={"X-PokeAgent-Token": entries[0]["token"]}), timeout=5).read())
        assert body["agent_id"] == "ex2" and body["kind"] == "explorer"
    finally:
        view.close()
    assert list_agents(tmp_path) == []


# --- RL adapter -----------------------------------------------------------------

class _FakeRlEnv:
    def __init__(self):
        from pokeagent.emulator import FakeEmulator
        self.emu = FakeEmulator()
        self.steps = 7

    def _obs(self):
        return (0x26, 3, 4)

    def allowed_actions(self):
        return [0, 1, 2]


def test_rl_adapter_brain_and_status(tmp_path):
    from pokeagent.adapters.rl_snapshot import RlAgentView
    status = tmp_path / "rlstatus_9999.json"
    status.write_text(json.dumps({"episode": 4, "wins": 2, "epsilon": 0.35, "phase": "TRAIN",
                                  "instance": 9999, "pid": 1, "tag": "", "generation": 4,
                                  "schema": "s", "git_sha": "x", "actions": 3, "evaluation": None,
                                  "updated_at": 0.0, "outcomes": {}, "rewards": {}, "current_steps": 7,
                                  "steps_total": 100, "steps_avg": 25.0, "steps_best": 20,
                                  "steps_worst": 30, "win_avg": 24.0}))
    view = RlAgentView(_FakeRlEnv(), status, agent_id="rl1", segment="left_house", marshal=False,
                       brain_fn=lambda obs: "OVERWORLD -> A(0.07)")
    s = view.snapshot()
    assert s.kind == "rl" and s.step == 7
    assert s.thinking.brain == "OVERWORLD -> A(0.07)"
    assert s.thinking.driver == "rl" and s.drivers_available == ["rl"]
    assert s.segment.id == "left_house" and s.goals[0].name == "left_house"
    assert any("obs" in row for row in s.sees.rows)
    with pytest.raises(ValueError):
        view.handlers()["press"](button="A")
    view.handlers()["pause"]()
    assert view.snapshot().state == "paused"


# --- supervisor -----------------------------------------------------------------

def test_supervisor_argv():
    from pokeagent.supervisor import build_argv
    ex = build_argv("explorer", ["--steps", "50"], 4567, Path("."))
    assert ex[1].endswith("explore_demo.py") and "--headless" in ex and "--frame-share" in ex
    assert ex[ex.index("--control-port") + 1] == "4567" and ex[-2:] == ["--steps", "50"]
    rl = build_argv("rl", ["--segment", "left_house"], 4568, Path("."))
    assert rl[1].endswith("rl_train.py") and rl[rl.index("--frame-port") + 1] == "4568"
    assert rl[-2:] == ["--segment", "left_house"]
    with pytest.raises(ValueError):
        build_argv("bogus", [], 1, Path("."))


# --- web view --------------------------------------------------------------------

def test_web_routes(tmp_path):
    from pokeagent.viewer import web
    model = ViewerModel()
    sources = [FakeSource("a1", [snap("a1")], [FRAME]), FakeSource("a2", [snap("a2", kind="rl")], [FRAME])]
    model.set_wants(frames={"a1": 10.0, "a2": 10.0})      # the page declares every card visible here
    model.poll(sources); model.drain()
    httpd = web.make_server(model, 0)
    port = httpd.server_address[1]
    import threading
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "pokeagent" in page and "/data" in page
        data = json.loads(urllib.request.urlopen(base + "/data", timeout=5).read())
        assert {a["id"] for a in data["agents"]} == {"a1", "a2"}
        assert data["agents"][0]["frame"] is True
        png = urllib.request.urlopen(base + "/frame.png?id=a1", timeout=5).read()
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        with pytest.raises(Exception):
            urllib.request.urlopen(urllib.request.Request(base + "/data", data=b"{}", method="POST"), timeout=5)
    finally:
        httpd.shutdown()
        httpd.server_close()


# --- UI smoke ---------------------------------------------------------------------

def test_ui_smoke_fakes():
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.ui.window import ViewerWindow
    model = ViewerModel()
    sources = {f"a{i}": FakeSource(f"a{i}", [snap(f"a{i}")] * 3, [FRAME] * 3) for i in range(6)}
    model.poll(list(sources.values())); model.drain()
    win = ViewerWindow(model, sources)
    try:
        win._build()
        dpg.setup_dearpygui()  # fonts/groups resolve only after setup; may fail headless -> skip
        win._populate()
    except Exception as e:
        pytest.skip(f"Dear PyGui cannot build widgets without a viewport: {e}")
    try:
        win.tick()
        assert len(win._grid.cards) == 6
        win.focus.focus("a0")
        win.tick()
        assert win._focus_view.card is not None
        win.focus.back()
        win.tick()
        for _ in range(3):  # tick exercises sync/update/texture uploads; render needs a real GL context
            win.tick()
    finally:
        dpg.destroy_context()


# --- CLI -------------------------------------------------------------------------

def test_cli_view_help(capsys):
    from pokeagent.cli import main
    with pytest.raises(SystemExit) as ei:
        main(["view", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--fake" in out and "--web" in out and "--root" in out
