"""Interventions, journaled: hold, release, press, macro, nudge. Shared by tools/agentctl.py and the MCP tools.

Every operation reads the agent's digest before and after, sends its command(s), and appends one line to
``<root>/runs/agent_interventions.jsonl`` ({ts, agent, by, action, args, result, digest_before, digest_after}).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pokeagent.intervene import client
from pokeagent.intervene.client import AgentError

JOURNAL = Path("runs") / "agent_interventions.jsonl"  # runs/interventions.jsonl is the explorer's demonstration log
NUDGE_HOLD_S = 120
UNSUPPORTED = "lease unsupported (old agent code)"


def journal(root: Path, row: dict) -> None:
    path = Path(root) / JOURNAL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")  # one write per line: concurrent writers do not interleave


def _run(root: Path, entry: dict, by: str, action: str, args: dict, body, needs_lease: bool = False) -> dict:
    """Digest before, `body(entry) -> result`, digest after, journal; returns the journaled row."""
    before = client.digest_of(entry)
    try:
        if needs_lease and "error" not in before and not before.get("lease"):
            result = {"ok": False, "error": UNSUPPORTED}  # an agent from before the lease/macro commands: send nothing
        else:
            result = body(entry)
    except AgentError as exc:
        result = {"ok": False, "error": str(exc)}
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "agent": entry["id"], "by": by, "action": action, "args": args,
           "result": result, "digest_before": before, "digest_after": client.digest_of(entry)}
    journal(root, row)
    return row


def hold(root: Path, entry: dict, seconds: int = NUDGE_HOLD_S, by: str = "claude") -> dict:
    return _run(root, entry, by, "hold", {"seconds": seconds}, lambda e: client.command(e, "claude_hold", seconds=seconds), needs_lease=True)


def release(root: Path, entry: dict, by: str = "claude") -> dict:
    return _run(root, entry, by, "release", {}, lambda e: client.command(e, "hold_release"))


def press(root: Path, entry: dict, buttons: list[str], by: str = "claude") -> dict:
    """Presses under a short lease (so the agent does not decide between them); the lease is dropped again afterwards."""
    def body(e: dict) -> dict:
        d = client.digest_of(e)
        was_held = d.get("claude_hold_s", 0) > 0 or not d.get("lease")  # old agent: plain presses, no lease to grant or drop
        if not was_held:
            client.command(e, "claude_hold", seconds=30)
        outs = [client.command(e, "press", button=b.upper(), source="claude") for b in buttons]
        if not was_held:
            client.command(e, "hold_release")
        return {"ok": all(o.get("ok") for o in outs), "presses": len(outs), "buttons": [b.upper() for b in buttons]}
    return _run(root, entry, by, "press", {"buttons": buttons}, body)


def macro(root: Path, entry: dict, name: str, args: dict | None = None, by: str = "claude") -> dict:
    return _run(root, entry, by, "macro", {"name": name, **(args or {})},
                lambda e: client.command(e, "macro", name=name, args=args or {}), needs_lease=True)


def nudge(root: Path, entry: dict, by: str = "claude") -> dict:
    """Hold 120 s, back_out, battle_run when a wild battle is open, then release (always: a nudge never leaves it frozen)."""
    def body(e: dict) -> dict:
        steps = [("hold", client.command(e, "claude_hold", seconds=NUDGE_HOLD_S))]
        steps.append(("back_out", client.command(e, "macro", name="back_out", args={})))
        d = client.digest_of(e)
        if d.get("battle") and d["battle"].get("kind") == "wild":
            steps.append(("battle_run", client.command(e, "macro", name="battle_run", args={})))
        steps.append(("release", client.command(e, "hold_release")))
        macros = [o for n, o in steps if n in ("back_out", "battle_run")]
        return {"ok": bool(macros) and bool(macros[-1].get("ok")),
                "steps": [{"step": n, "ok": o.get("ok"), "result": o.get("result"), "presses": o.get("presses")}
                          for n, o in steps]}
    return _run(root, entry, by, "nudge", {}, body, needs_lease=True)
