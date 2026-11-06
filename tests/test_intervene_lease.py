"""Claude lease: blocks decisions and expires, press refreshes it, the watchdog skips a held agent, decisions.jsonl marks claude."""
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

from pokeagent.control_server import ControlServer
from pokeagent.intervene.lease import LEASE_FILE, ClaudeHold, lease_active
from pokeagent.snapshot import AgentSnapshot

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _load(name):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(f"tool_{name}_lease", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_lease_grant_expire_touch_release_and_clamp():
    c = Clock()
    h = ClaudeHold(clock=c)
    assert not h.active() and h.remaining() == 0
    assert h.grant(120) == 120 and h.active() and h.remaining() == 120
    c.t += 119
    assert h.active()
    c.t += 2
    assert not h.active() and h.remaining() == 0  # expired by itself
    assert h.grant(10_000) == 600 and h.grant(0) == 1  # clamped to 1..600
    h.grant(30)
    c.t += 25
    h.touch()  # a claude press re-arms the full lease
    assert h.remaining() == 30
    c.t += 31
    h.touch()  # no lease left: a press still holds the agent for a few seconds
    assert 2.9 < h.remaining() <= 30
    h.release()
    assert not h.active()


def test_lease_file_mirrors_the_lease_for_the_watchdog(tmp_path):
    c, wall = Clock(), Clock()
    wall.t = 5000.0
    h = ClaudeHold(tmp_path / LEASE_FILE, clock=c, wall=wall)
    assert not lease_active(tmp_path, wall)
    h.grant(60)
    assert lease_active(tmp_path, wall)
    wall.t += 61
    assert not lease_active(tmp_path, wall)
    h.grant(60)
    h.release()
    assert not (tmp_path / LEASE_FILE).exists()
    (tmp_path / LEASE_FILE).write_text("not json")
    assert not lease_active(tmp_path)


def test_control_server_validates_claude_hold_and_macro(tmp_path):
    got = []
    srv = ControlServer(lambda: AgentSnapshot(agent_id="x"), {"claude_hold": lambda seconds: got.append(seconds) or {"claude_hold_s": seconds},
                                                               "macro": lambda name, args=None: {"ok": False, "result": "stopped", "presses": 0}},
                        token="tok")
    srv.start()
    try:
        def post(body):
            req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/command", data=json.dumps(body).encode(), method="POST",
                                         headers={"X-PokeAgent-Token": "tok", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        assert post({"cmd": "claude_hold", "seconds": 90}) == (200, {"ok": True, "claude_hold_s": 90})
        assert post({"cmd": "claude_hold", "seconds": 0})[0] == 400 and post({"cmd": "claude_hold", "seconds": 601})[0] == 400
        assert post({"cmd": "claude_hold", "seconds": "5"})[0] == 400 and post({"cmd": "claude_hold"})[0] == 400
        code, body = post({"cmd": "macro", "name": "back_out", "args": {}})
        assert code == 200 and body["ok"] is False and body["result"] == "stopped"  # a handler's ok=False survives
        assert post({"cmd": "macro", "name": "bad name!"})[0] == 400 and post({"cmd": "macro", "name": "x", "args": "no"})[0] == 400
        assert got == [90]
    finally:
        srv.stop()


# --- the explorer view ----------------------------------------------------------------

def _view(tmp_path, with_log=True):
    from pokeagent.adapters.explorer_snapshot import ExplorerAgentView
    from pokeagent.emulator import FakeEmulator
    from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
    from pokeagent.explorer.decisions import DecisionLog
    from pokeagent.explorer.engine import Engine
    from pokeagent.explorer.memory import MapMemory
    from pokeagent.explorer.press import Presser
    emu = FakeEmulator({0xD35E: 0x26, 0xD367: 0})
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=run_dir)
    ctx.trans = open(run_dir / "transitions.jsonl", "a", encoding="utf-8")
    presser = Presser(ctx)
    log = DecisionLog(run_dir / "decisions.jsonl") if with_log else None
    engine = Engine(ctx, presser, decision_log=log)
    view = ExplorerAgentView(ctx, emu, ctx.mem, engine, presser, agent_id="ex", root=tmp_path, marshal=False)
    return view, run_dir, emu


def test_lease_blocks_the_agent_and_release_frees_it(tmp_path):
    view, run_dir, _ = _view(tmp_path)
    h = view.handlers()
    assert not view.held() and view.snapshot().claude_hold_s == 0
    out = h["claude_hold"](seconds=120)
    assert out["claude_hold_s"] == 120 and view.held()  # explore_demo skips engine.step() while held() is true
    snap = view.snapshot()
    assert snap.claude_hold_s > 119 and snap.to_dict()["claude_hold_s"] > 119
    assert lease_active(run_dir)  # the watchdog's view
    h["hold_release"]()
    assert not view.held() and not lease_active(run_dir) and view.snapshot().claude_hold_s == 0


def test_lease_expiry_and_human_hold_are_both_holds(tmp_path):
    view, _, _ = _view(tmp_path)
    c = Clock()
    view.claude_hold._clock = c
    view.claude_hold.grant(5)
    assert view.held()
    c.t += 6
    assert not view.held()
    view.handlers()["press"](button="A", source="human")
    assert view.held()  # the human hold still works as before
    view.handlers()["hold_release"]()
    assert not view.held()


def test_claude_press_refreshes_the_lease_and_marks_decisions_jsonl(tmp_path):
    view, run_dir, emu = _view(tmp_path)
    h = view.handlers()
    h["press"](button="B", source="claude")  # no lease granted: a press still holds for a few seconds
    assert view.held() and emu.presses
    h["claude_hold"](seconds=40)
    view.claude_hold._until -= 30  # 10 s left
    h["press"](button="A", source="claude")
    assert view.claude_hold.remaining() > 39
    rows = [json.loads(line) for line in (run_dir / "decisions.jsonl").read_text().splitlines()]
    assert [r["driver"] for r in rows] == ["claude", "claude"] and rows[0]["rule"] == "remote_press" and rows[0]["button"] == "B"
    assert view.snapshot().extra["decisions"][-1]["d"] == "claude"


def test_macro_command_runs_under_an_automatic_lease_and_journals_decisions(tmp_path):
    view, run_dir, _ = _view(tmp_path)
    out = view.handlers()["macro"](name="back_out", args={})
    assert out["ok"] and out["result"] == "overworld" and out["presses"] == 0 and out["final_screen"]["mode"] == "overworld"
    assert view.held()  # a macro always leaves the agent held for a moment
    out = view.handlers()["macro"](name="wait", args={"frames": 12})
    assert out["ok"] and out["result"] == "waited"
    out = view.handlers()["macro"](name="nonsense", args={})
    assert not out["ok"] and out["result"].startswith("unknown_macro")


def test_snapshot_extra_carries_the_digest_inputs(tmp_path):
    view, _, _ = _view(tmp_path)
    d = view.snapshot().to_dict()
    assert d["extra"]["map"] == 0x26 and d["extra"]["mode"] == "overworld" and d["extra"]["battle"] is None
    assert set(d["extra"]) >= {"x", "y", "bag", "decisions", "box_hist"}


# --- the swarm watchdog ----------------------------------------------------------------

def test_watchdog_skips_a_held_agent_and_restarts_its_clocks(tmp_path):
    sw = _load("swarm_watch")
    run = tmp_path / "runs" / "explore-1-1"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"seed": 7}))
    (run / "transitions.jsonl").write_text(json.dumps({"to": [13, 1, 1], "button": "A"}) + "\n")
    c = Clock()
    w = sw.ProgressWatch(tmp_path, 7, since_wall=0, clock=c)
    assert w.check() is None and w.presses == 1 and w.skipped == ""
    c.t += 500  # hung for ages...
    hold = ClaudeHold(run / LEASE_FILE)
    hold.grant(120)  # ...but Claude holds it
    assert w.check() is None and w.skipped == "claude hold"
    c.t += 119
    assert w.check() is None  # still held (clocks restart at every held check)
    hold.release()
    assert w.check() is None and w.skipped == ""  # just released: not killed on the spot
    c.t += 121
    assert "hung" in w.check()  # genuinely idle again after the lease: judged as usual


def test_watchdog_waiting_for_first_transition_is_also_skipped(tmp_path):
    sw = _load("swarm_watch")
    run = tmp_path / "runs" / "explore-2-2"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"seed": 9}))
    (run / "transitions.jsonl").write_text("")
    c = Clock()
    w = sw.ProgressWatch(tmp_path, 9, since_wall=0, clock=c)
    ClaudeHold(run / LEASE_FILE).grant(600)
    c.t += 1000
    assert w.check() is None and w.skipped == "claude hold"
