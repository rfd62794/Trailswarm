"""Talk to live agents: discover them in ``<root>/runs/agents``, read snapshots, send commands, resolve selectors.

Transport only (stdlib urllib, the agent's token header); the operations that journal (ops.py) sit on top. An agent
that does not answer is reported as unreachable, never retried in a loop and never killed.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pokeagent.agent_registry import list_agents
from pokeagent.control_server import TOKEN_HEADER
from pokeagent.intervene.digest import digest_agent, rank

SNAPSHOT_TIMEOUT_S = 4.0
COMMAND_TIMEOUT_S = 150.0   # a macro walks the game on the agent's own thread


class AgentError(RuntimeError):
    """The agent is unreachable or refused the request."""


def root_dir(arg: str | os.PathLike | None = None) -> Path:
    return Path(arg or os.environ.get("POKEAGENT_ROOT") or ".")


def _request(entry: dict, method: str, path: str, body: dict | None, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {TOKEN_HEADER: entry.get("token", ""), **({"Content-Type": "application/json"} if data else {})}
    req = urllib.request.Request(f"http://127.0.0.1:{entry['port']}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read())
        except ValueError:
            raise AgentError(f"{entry.get('id')}: HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AgentError(f"{entry.get('id')}: {getattr(exc, 'reason', exc)}") from None


def snapshot(entry: dict, timeout: float = SNAPSHOT_TIMEOUT_S) -> dict:
    return _request(entry, "GET", "/snapshot", None, timeout)


def command(entry: dict, cmd: str, timeout: float = COMMAND_TIMEOUT_S, **args) -> dict:
    return _request(entry, "POST", "/command", {"cmd": cmd, **args}, timeout)


def digest_of(entry: dict) -> dict:
    """The digest of one agent, or ``{"id", "error"}`` when it does not answer."""
    try:
        return digest_agent(snapshot(entry))
    except AgentError as exc:
        return {"id": entry.get("id", "?"), "error": str(exc)}


def digests(root: Path) -> list[dict]:
    """Every registered agent's digest, ranked (unreachable ones last)."""
    entries = list_agents(root)
    if not entries:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(entries))) as pool:
        ds = list(pool.map(digest_of, entries))
    return rank([d for d in ds if "error" not in d]) + [d for d in ds if "error" in d]


def resolve(root: Path, selector: str, known: list[dict] | None = None) -> dict:
    """Registry entry for an agent id, a unique id fragment ('20120'), 'closest' (furthest stage) or 'stuck'."""
    entries = {e["id"]: e for e in list_agents(root)}
    if selector in ("closest", "stuck"):
        ds = [d for d in (known if known is not None else digests(root)) if "error" not in d]
        pick = next((d for d in ds if selector == "closest" or d["stuck"]), None)
        if pick is None:
            raise AgentError(f"no {'reachable' if selector == 'closest' else 'stuck'} agent")
        return entries[pick["id"]]
    if selector in entries:
        return entries[selector]
    hits = [e for i, e in entries.items() if selector in i]
    if len(hits) != 1:
        raise AgentError(f"agent {selector!r}: {'no match' if not hits else 'ambiguous: ' + ', '.join(e['id'] for e in hits)}"
                         f" (registered: {', '.join(entries) or 'none'})")
    return hits[0]
