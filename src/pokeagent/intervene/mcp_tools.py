"""MCP tools for the intervention layer: agents_digest, agent_show, agent_hold, agent_release, agent_macro, agent_nudge.

Registered by ``mcp_server.build_server`` next to the emulator tools. They talk to the LIVE agents registered under
``$POKEAGENT_ROOT`` (default: the server's working directory); the emulator tools of the same server are a separate game.
Selectors: an agent id, a unique fragment of one, ``closest`` (furthest goal stage) or ``stuck``. Every intervention is
journaled to runs/interventions.jsonl with the digest before and after.
"""
from __future__ import annotations

from typing import Any

from pokeagent.intervene import client, ops
from pokeagent.intervene.client import AgentError
from pokeagent.intervene.digest import format_block, format_table

BY = "claude-mcp"


class AgentTools:
    def __init__(self, root=None) -> None:
        self.root = client.root_dir(root)

    def _entry(self, agent: str) -> dict:
        return client.resolve(self.root, agent)

    def _do(self, fn, agent: str, *a, **kw) -> dict[str, Any]:
        try:
            row = fn(self.root, self._entry(agent), *a, by=BY, **kw)
        except AgentError as exc:
            return {"ok": False, "error": str(exc)}
        return {"agent": row["agent"], "action": row["action"], "result": row["result"],
                "before": format_block(row["digest_before"]) if "error" not in row["digest_before"] else row["digest_before"],
                "after": format_block(row["digest_after"]) if "error" not in row["digest_after"] else row["digest_after"]}

    def agents_digest(self) -> dict[str, Any]:
        """All live agents, ranked by progress (furthest goal stage first), one row each, with stuck reasons."""
        ds = client.digests(self.root)
        return {"table": format_table(ds), "agents": ds}

    def agent_show(self, agent: str = "closest") -> dict[str, Any]:
        """Detailed situation of one agent (id, fragment, 'closest' or 'stuck'): where, goal, battle, party, bag, last 8 decisions, stuck signals."""
        try:
            d = client.digest_of(self._entry(agent))
        except AgentError as exc:
            return {"ok": False, "error": str(exc)}
        return {"text": format_block(d) if "error" not in d else d["error"], "digest": d}

    def agent_hold(self, agent: str, seconds: int = ops.NUDGE_HOLD_S) -> dict[str, Any]:
        """Lease an agent (1..600 s): it makes no own decisions and the stall watchdog will not kill it."""
        return self._do(ops.hold, agent, seconds)

    def agent_release(self, agent: str) -> dict[str, Any]:
        """End the lease (and any human hold): the agent decides for itself again."""
        return self._do(ops.release, agent)

    def agent_macro(self, agent: str, name: str, args: dict | None = None) -> dict[str, Any]:
        """Run a screen-verified macro on an agent: back_out, battle_run, battle_fight{move}, use_item{item,on}, switch{slot}, goto{map,x,y}, wait{frames}."""
        return self._do(ops.macro, agent, name, args or {})

    def agent_nudge(self, agent: str = "closest") -> dict[str, Any]:
        """Hold 120 s, back out of menus, run from a wild battle if one is open, release. Prints the digest before and after."""
        return self._do(ops.nudge, agent)


def register(server, root=None) -> AgentTools:
    tools = AgentTools(root)
    for fn in (tools.agents_digest, tools.agent_show, tools.agent_hold, tools.agent_release, tools.agent_macro,
               tools.agent_nudge):
        server.tool()(fn)
    return tools
