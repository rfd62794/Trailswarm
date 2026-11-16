"""What the watcher may ask a stalled run to do over its control API (stdlib urllib only).

The run's ``POST /command`` surface (pokeagent.control_server) answers on an ephemeral port whose
entry - port AND token - lives in ``runs/agents/explore-<pid>.json``; a run dir ``explore-<ts>-<pid>``
matches it by pid. Port resolution: ``--port`` wins, then that registry entry, then meta.json
``control_port`` (the demo's REST port - no /command route today, kept as the directive's fallback).
Every action is failure-tolerant: nothing here raises, the result rides in the JSON line.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_S = 3.0
TOKEN_HEADER = "X-PokeAgent-Token"  # pokeagent.control_server's auth header


def _registry_entry(view) -> dict:
    """The runs/agents/*.json entry matching this run's pid ({} when none is live or readable)."""
    pid = view.name.rsplit("-", 1)[-1]
    try:
        for p in (view.dir.parent / "agents").glob("*.json"):
            try:
                e = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(e, dict) and (p.stem == f"explore-{pid}" or str(e.get("pid")) == pid):
                return e
    except OSError:
        pass
    return {}


def endpoint(view, port: int | None = None) -> tuple[int, str]:
    """(port, token) for the run's control API; (0, "") when undiscoverable."""
    entry = _registry_entry(view)
    if port:
        return int(port), str(entry.get("token") or "")
    if entry.get("port"):
        return int(entry["port"]), str(entry.get("token") or "")
    meta_port = view.meta.get("control_port")
    if meta_port:
        return int(meta_port), ""
    return 0, ""


def post_command(port: int, body: dict, token: str = "", timeout: float = TIMEOUT_S) -> dict:
    """POST one /command body to 127.0.0.1:<port>; the reply dict, or {"error": ...}."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/command",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **({TOKEN_HEADER: token} if token else {})},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except (ValueError, OSError):
            return {"error": f"http {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def save_state(port: int, press: int, token: str = "") -> dict:
    """{"save": path-or-error}: ask the run to checkpoint itself for the post-mortem."""
    if not port:
        return {"save": "no port"}
    r = post_command(port, {"cmd": "save_state", "name": f"stall-{press}"}, token)
    return {"save": str(r.get("path") or r.get("error") or ("ok" if r.get("ok") else r))}


def stop(port: int, token: str = "") -> dict:
    """{"stop": "ok"-or-error}: --stop asks the run for a clean exit (the control `stop` command)."""
    if not port:
        return {"stop": "no port"}
    r = post_command(port, {"cmd": "stop"}, token)
    return {"stop": "ok" if r.get("ok") else str(r.get("error") or r)}
