"""agentctl and the MCP tools against fake agents (real ControlServers + registry files, no emulator)."""
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from pokeagent import agent_registry
from pokeagent.control_server import ControlServer
from pokeagent.intervene import client
from pokeagent.intervene.client import AgentError
from pokeagent.intervene.mcp_tools import AgentTools
from pokeagent.goals import GOALS, SIDE_GOALS
from pokeagent.snapshot import AgentSnapshot, Goal, PartyMon, Screen

LADDER = [g for g in GOALS if g not in SIDE_GOALS]
TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _agentctl():
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("tool_agentctl_t", TOOLS / "agentctl.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeAgent:
    """A ControlServer that records commands and serves a configurable snapshot."""

    def __init__(self, root, aid, done, step=10, battle=None, decisions=None, box=""):
        self.aid, self.done, self.step, self.battle, self.decisions, self.box = aid, done, step, battle, decisions or [], box
        self.cmds: list[dict] = []
        self.held = 0.0
        self.macro_results = {"back_out": {"ok": True, "result": "battle_menu" if battle else "overworld", "presses": 2},
                              "battle_run": {"ok": True, "result": "escaped", "presses": 3}}
        handlers = {"claude_hold": self.h_hold, "hold_release": self.h_release, "macro": self.h_macro, "press": self.h_press,
                    "macro_cancel": self.h_cancel}
        self.srv = ControlServer(self.snap, handlers, token=f"tok-{aid}")
        port = self.srv.start()
        agent_registry.register(root, aid, "explorer", port, "", pid=os.getpid(), token=self.srv.token)

    def h_hold(self, seconds):
        self.cmds.append({"cmd": "claude_hold", "seconds": seconds})
        self.held = float(seconds)
        return {"claude_hold_s": self.held}

    def h_cancel(self):
        self.cmds.append({"cmd": "macro_cancel"})
        return {"cancelling": "back_out"}

    def h_release(self):
        self.cmds.append({"cmd": "hold_release"})
        self.held = 0.0
        return {}

    def h_macro(self, name, args=None):
        self.cmds.append({"cmd": "macro", "name": name, "args": args or {}})
        if name == "back_out" and self.battle:
            pass
        elif name == "battle_run":
            self.battle = None  # we got away
        return dict(self.macro_results.get(name, {"ok": False, "result": "unknown", "presses": 0}))

    def h_press(self, button, source="human"):
        self.cmds.append({"cmd": "press", "button": button, "source": source})
        return {}

    def snap(self):
        goals = [Goal(id=g, name=g, status="done" if i < self.done else ("current" if i == self.done else "ahead"))
                 for i, g in enumerate(LADDER)]
        s = AgentSnapshot(agent_id=self.aid, kind="explorer", step=self.step, goals=goals, claude_hold_s=self.held,
                          screen=Screen(box_text=self.box, in_battle=bool(self.battle), money=500,
                                        party=[PartyMon(species="WARTORTLE", level=24, hp=11, max_hp=57)]))
        s.extra = {"map": 59, "x": 4, "y": 5, "mode": "battle" if self.battle else "overworld", "battle": self.battle,
                   "bag": {"POTION": 0}, "decisions": self.decisions, "box_hist": []}
        return s

    def stop(self):
        self.srv.stop()


WILD = {"kind": "wild", "you": {"species": "WARTORTLE", "level": 24, "hp": 11, "max": 57},
        "enemy": {"species": "RATTATA", "level": 12, "hp": 8, "max": 20}}
LOOP = [{"s": i, "r": "item_open", "b": "A", "m": 59, "x": 4, "y": 5, "o": "box", "bx": True, "bt": True, "d": "agent"} for i in range(12)]


@pytest.fixture
def swarm(tmp_path):
    agents = [FakeAgent(tmp_path, "explore-111", done=3, step=50),
              FakeAgent(tmp_path, "explore-20120", done=18, step=900, battle=WILD, decisions=LOOP,
                        box="It won't have any effect."),
              FakeAgent(tmp_path, "explore-333", done=10, step=400)]
    yield tmp_path, {a.aid: a for a in agents}
    for a in agents:
        a.stop()


def run(argv, tmp_path):
    out: list[str] = []
    rc = _agentctl().main(["--root", str(tmp_path), *argv], out=out.append)
    return rc, "\n".join(out)


def test_ls_is_ranked_and_shows_stuck_and_battle(swarm):
    root, _ = swarm
    rc, text = run(["ls"], root)
    rows = text.splitlines()
    assert rc == 0 and [r.split()[0] for r in rows] == ["explore-20120", "explore-333", "explore-111"]
    assert "battle/wild" in rows[0] and "STUCK:" in rows[0] and "item_loop" in rows[0] and "rule_repeat" in rows[0]
    assert "STUCK" not in rows[1] and rows[1].rstrip().endswith("ok")


def test_selectors(swarm):
    root, _ = swarm
    assert client.resolve(root, "closest")["id"] == "explore-20120"
    assert client.resolve(root, "stuck")["id"] == "explore-20120"
    assert client.resolve(root, "explore-333")["id"] == "explore-333"
    assert client.resolve(root, "333")["id"] == "explore-333"  # unique fragment
    with pytest.raises(AgentError, match="ambiguous"):
        client.resolve(root, "explore")
    with pytest.raises(AgentError, match="no match"):
        client.resolve(root, "zzz")
    rc, text = run(["show", "stuck"], root)
    assert rc == 0 and text.startswith("explore-20120") and "item_loop" in text and "wild: WARTORTLE" in text
    rc, text = run(["show", "nobody"], root)
    assert rc == 2


def test_no_stuck_agent_is_an_error(tmp_path):
    a = FakeAgent(tmp_path, "explore-1", done=2)
    try:
        assert run(["show", "stuck"], tmp_path)[0] == 2
        assert run(["show", "closest"], tmp_path)[0] == 0
    finally:
        a.stop()


def test_hold_release_press_macro_and_the_journal(swarm):
    root, agents = swarm
    a = agents["explore-20120"]
    rc, text = run(["hold", "closest", "90"], root)
    assert rc == 0 and a.cmds[-1] == {"cmd": "claude_hold", "seconds": 90} and "HELD: claude 90s" in text.split("-- after")[1]
    rc, text = run(["macro", "explore-20120", "use_item", "item=POTION", "on=2"], root)
    assert a.cmds[-1] == {"cmd": "macro", "name": "use_item", "args": {"item": "POTION", "on": 2}} and rc == 1  # unknown -> not ok
    run(["release", "explore-20120"], root)
    assert a.cmds[-1] == {"cmd": "hold_release"}
    a.cmds.clear()
    rc, _ = run(["press", "explore-20120", "b", "UP"], root)
    assert rc == 0
    assert [c["cmd"] for c in a.cmds] == ["claude_hold", "press", "press", "hold_release"]
    assert [c.get("button") for c in a.cmds if c["cmd"] == "press"] == ["B", "UP"] and all(
        c["source"] == "claude" for c in a.cmds if c["cmd"] == "press")
    rows = [json.loads(line) for line in (root / "runs" / "agent_interventions.jsonl").read_text().splitlines()]
    assert [r["action"] for r in rows] == ["hold", "macro", "release", "press"]
    r = rows[0]
    assert set(r) == {"ts", "agent", "by", "action", "args", "result", "digest_before", "digest_after"}
    assert r["agent"] == "explore-20120" and r["by"] == "claude" and r["digest_before"]["claude_hold_s"] == 0
    assert r["digest_after"]["claude_hold_s"] == 90


def test_nudge_runs_from_a_wild_battle_then_releases(swarm):
    root, agents = swarm
    a = agents["explore-20120"]
    rc, text = run(["nudge", "closest"], root)
    assert rc == 0
    assert [(c["cmd"], c.get("name")) for c in a.cmds] == [("claude_hold", None), ("macro", "back_out"), ("macro", "battle_run"),
                                                           ("hold_release", None)]
    assert a.cmds[0]["seconds"] == 120 and a.held == 0
    assert "-- before" in text and "-- after" in text
    before, after = text.split("-- before")[1].split("-- after")
    assert "battle: wild" in before and "battle: wild" not in after  # the battle is gone afterwards
    row = json.loads((root / "runs" / "agent_interventions.jsonl").read_text().splitlines()[-1])
    assert row["action"] == "nudge" and [s["step"] for s in row["result"]["steps"]] == ["hold", "back_out", "battle_run", "release"]


def test_nudge_without_a_battle_only_backs_out_and_releases(swarm):
    root, agents = swarm
    a = agents["explore-333"]
    rc, _ = run(["--by", "tobor", "nudge", "explore-333"], root)
    assert rc == 0 and [(c["cmd"], c.get("name")) for c in a.cmds] == [("claude_hold", None), ("macro", "back_out"), ("hold_release", None)]
    assert json.loads((root / "runs" / "agent_interventions.jsonl").read_text().splitlines()[-1])["by"] == "tobor"


def test_nudge_a_failed_macro_reports_not_ok(swarm):
    root, agents = swarm
    a = agents["explore-333"]
    a.macro_results["back_out"] = {"ok": False, "result": "screen_unchanged", "presses": 4}
    rc, text = run(["nudge", "explore-333"], root)
    assert rc == 1 and "screen_unchanged" in text and a.cmds[-1] == {"cmd": "hold_release"}  # released even when it failed


def test_unreachable_agent_is_listed_not_fatal(swarm):
    root, agents = swarm
    agents["explore-111"].stop()
    rc, text = run(["ls"], root)
    assert rc == 0 and text.splitlines()[-1].startswith("explore-111") and "unreachable" in text.splitlines()[-1]
    assert run(["hold", "explore-111", "5"], root)[0] == 1  # the command could not be delivered; journaled, not raised


def test_parse_kv_and_empty_registry(tmp_path):
    ctl = _agentctl()
    assert ctl.parse_kv(["move=BITE", "x=5", "y=-2"]) == {"move": "BITE", "x": 5, "y": -2}
    with pytest.raises(SystemExit):
        ctl.parse_kv(["oops"])
    assert run(["ls"], tmp_path) == (0, "no agents registered")


def test_mcp_agent_tools(swarm):
    root, agents = swarm
    tools = AgentTools(root)
    d = tools.agents_digest()
    assert d["table"].splitlines()[0].startswith("explore-20120") and len(d["agents"]) == 3
    assert "item_loop" in tools.agent_show("stuck")["text"]
    n = tools.agent_nudge("closest")
    assert n["result"]["ok"] and "wild" in n["before"] and agents["explore-20120"].held == 0
    assert tools.agent_hold("333", 10)["result"]["claude_hold_s"] == 10.0
    assert tools.agent_release("333")["action"] == "release"
    assert tools.agent_macro("333", "back_out")["result"]["result"] == "overworld"
    assert tools.agent_show("zzz")["ok"] is False
    rows = (root / "runs" / "agent_interventions.jsonl").read_text().splitlines()
    assert json.loads(rows[0])["by"] == "claude-mcp"


def test_mcp_server_registers_the_agent_tools(tmp_path):
    from mcp.server.mcpserver import MCPServer
    from pokeagent.intervene.mcp_tools import register
    server = MCPServer("t")
    register(server, tmp_path)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"agents_digest", "agent_show", "agent_hold", "agent_release", "agent_macro", "agent_nudge"}


class OldAgent(FakeAgent):
    """An agent from before the lease/macros: its snapshot has no claude_hold_s/extra and it lacks those commands."""

    def __init__(self, root, aid, done):
        super().__init__(root, aid, done)
        self.srv.stop()
        outer = self

        class Old:
            def to_dict(self):
                d = outer.snap().to_dict()
                d.pop("claude_hold_s"), d.pop("extra")
                return d
        self.srv = ControlServer(lambda: Old(), {"press": self.h_press, "hold_release": self.h_release}, token="tok-old")
        port = self.srv.start()
        agent_registry.register(root, aid, "explorer", port, "", pid=os.getpid(), token=self.srv.token)


def test_old_agent_degrades_gracefully(tmp_path):
    a = OldAgent(tmp_path, "explore-old", done=5)
    try:
        rc, text = run(["ls"], tmp_path)
        assert rc == 0 and "explore-old" in text and "no-lease" in text and "unreachable" not in text
        rc, text = run(["show", "explore-old"], tmp_path)
        assert rc == 0 and "lease unsupported (old agent code)" in text and "WARTORTLE" in text
        a.cmds.clear()
        for argv in (["hold", "explore-old", "5"], ["nudge", "explore-old"], ["macro", "explore-old", "back_out"]):
            rc, text = run(argv, tmp_path)
            assert rc == 1 and "lease unsupported (old agent code)" in text
        assert a.cmds == []  # nothing was sent to it
        rc, _ = run(["press", "explore-old", "B"], tmp_path)
        assert rc == 0 and [c["cmd"] for c in a.cmds] == ["press"]  # plain presses still work, without a lease
    finally:
        a.stop()


def test_nudge_cancels_a_pending_macro_before_it_releases(swarm):
    root, agents = swarm
    a = agents["explore-333"]
    a.macro_results["back_out"] = {"ok": False, "result": "pending", "presses": 0}  # still running on the agent
    rc, text = run(["nudge", "explore-333"], root)
    assert rc == 1
    assert [(c["cmd"], c.get("name")) for c in a.cmds] == [("claude_hold", None), ("macro", "back_out"), ("macro_cancel", None),
                                                           ("hold_release", None)]
