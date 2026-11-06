"""Claude lease: blocks decisions and expires, press refreshes it, the watchdog skips a held agent, decisions.jsonl marks claude."""
import importlib.util
import json
import os
import sys
import time
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
    c = Clock()
    f = tmp_path / LEASE_FILE
    h = ClaudeHold(f, clock=c)
    assert not lease_active(tmp_path)
    h.grant(60)
    assert lease_active(tmp_path)
    assert not lease_active(tmp_path, lambda: time.time() + 61)  # expired
    # a hung agent stops refreshing the mirror: an old mtime is not trusted even though `until` is still ahead
    f.write_text(json.dumps({"until": time.time() + 500}))
    os.utime(f, (time.time() - 100, time.time() - 100))
    assert not lease_active(tmp_path)
    h.grant(60)
    os.utime(f, (time.time() - 100, time.time() - 100))
    c.t += 4
    h.refresh()  # the agent's own loop re-writes it while held
    assert lease_active(tmp_path)
    # an `until` far past the mirror's mtime is nonsense
    f.write_text(json.dumps({"until": time.time() + 5000}))
    assert not lease_active(tmp_path)
    h.grant(60)
    h.release()
    assert not f.exists()
    f.write_text("not json")
    assert not lease_active(tmp_path)


def test_release_overwrites_the_mirror_when_it_cannot_unlink(tmp_path, monkeypatch):
    f = tmp_path / LEASE_FILE
    h = ClaudeHold(f)
    h.grant(60)
    real = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(PermissionError("locked")))
    h.release()
    monkeypatch.setattr(Path, "unlink", real)
    assert json.loads(f.read_text()) == {"until": 0} and not lease_active(tmp_path)


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
    assert not view.held() and not lease_active(run_dir)  # the automatic lease goes with the macro
    view.handlers()["claude_hold"](seconds=200)
    view.handlers()["macro"](name="back_out", args={})
    assert view.claude_hold.remaining() > 100  # an explicit hold survives a macro
    view.handlers()["hold_release"]()
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


def test_snapshot_extra_battle_block_never_mixes_two_pokemon(tmp_path):
    from pokeagent.intervene.names import species_name
    view, _, emu = _view(tmp_path)
    emu.memory.update({0xD057: 1, 0xD163: 1, 0xD16B: 0xB2, 0xCC2F: 0,           # wild battle, party of one, slot 0 in the fight
                       0xD16D: 17, 0xD18C: 5, 0xD18E: 17,                       # party mon: L5, 17/17
                       0xD014: 0, 0xD016: 11, 0xD022: 24, 0xD024: 57,           # wBattleMon not loaded yet: species 0, stale L24 11/57
                       0xCFE5: 0x6D, 0xCFE7: 8, 0xCFF3: 12, 0xCFF5: 20})       # wEnemyMon: 8/20 HP, L12
    b = view.snapshot().extra["battle"]
    assert b["kind"] == "wild" and view.snapshot().extra["mode"] == "battle"
    assert b["you"] == {"species": species_name(0xB2), "level": 5, "hp": 17, "max": 17}  # from the party, not the stale struct
    assert b["enemy"] == {"species": species_name(0x6D), "level": 12, "hp": 8, "max": 20}
    emu.memory[0xD014] = 0xB2  # battle loaded: the struct is authoritative
    assert view.snapshot().extra["battle"]["you"] == {"species": species_name(0xB2), "level": 24, "hp": 11, "max": 57}


def _marshalled_view(tmp_path, screens, agent_id):
    from pokeagent.adapters.explorer_snapshot import ExplorerAgentView
    from pokeagent.intervene.runner import MacroController
    from test_intervene_macros import Rig
    base, _, emu = _view(tmp_path)
    view = ExplorerAgentView(base.ctx, emu, base.ctx.mem, base.engine, base.presser, agent_id=agent_id, root=tmp_path,
                             refresh_every=1)
    view.macros = MacroController(view, rig_factory=lambda name: Rig(screens, emu))
    return view


def _drive(view, thread, frames=2000):
    """The emulator-side frame loop while an HTTP-side thread waits: returns (frames ticked, macro states seen)."""
    n, seen = 0, []
    while thread.is_alive() and n < frames:
        view.tick()
        n += 1
        st = view.snapshot().extra.get("macro_status")
        if st:
            seen.append(st["state"])
        time.sleep(0.001)
    thread.join(5)
    return n, seen


def test_macro_runs_on_the_frame_loop_without_freezing_it_and_reports_status(tmp_path):
    import threading
    from test_intervene_macros import scr
    screens = [scr([f"line {i}"], battle=False) for i in range(5)] + [scr([], battle=False, screen=[])]
    view = _marshalled_view(tmp_path, screens, "m")
    out: dict = {}
    t = threading.Thread(target=lambda: out.update(view.handlers()["macro"](name="back_out", args={})))
    t.start()
    frames, seen = _drive(view, t)
    assert out["ok"] and out["result"] == "overworld" and out["presses"] == 5
    assert frames > 5 and "running" in seen  # ticks kept coming between steps; the status was visible while it ran
    view.tick()  # the next frame refreshes the cached snapshot
    assert view.snapshot().extra["macro_status"]["state"] == "done" and not view.held()


def test_macro_pending_busy_and_cancel(tmp_path):
    import threading
    from test_intervene_macros import scr
    view = _marshalled_view(tmp_path, [scr([f"line {i}"], battle=False) for i in range(500)], "m2")
    h = view.handlers()

    def call(fn, sink, **kw):
        t = threading.Thread(target=lambda: sink.append(fn(**kw)))
        t.start()
        return t

    results: list = []
    t = call(h["macro"], results, name="back_out", args={}, wait_s=0.05)
    _drive(view, t, 400)
    assert results[0]["result"] == "pending" and results[0]["macro_status"]["state"] == "running"  # the 504 does not hide it
    assert view.snapshot().extra["macro_status"]["state"] == "running"
    busy: list = []
    _drive(view, call(h["macro"], busy, name="wait", args={}), 400)
    assert busy[0]["result"] == "macro_busy"
    cancel: list = []
    _drive(view, call(h["macro_cancel"], cancel), 400)
    for _ in range(5):
        view.tick()
    st = view.snapshot().extra["macro_status"]
    assert cancel[0]["cancelling"] == "back_out" and st["state"] == "stopped" and st["result"] == "cancelled"
    assert not view.held()
