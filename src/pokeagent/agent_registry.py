"""Agent discovery files: ``<root>/runs/agents/<id>.json`` written by agents, read by viewers."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pokeagent.registry import process_alive


def _dir(root: Path) -> Path:
    return Path(root) / "runs" / "agents"


def register(root: Path, agent_id: str, kind: str, port: int, frame_slot: str, pid: int | None = None,
             token: str = "") -> Path:
    d = _dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{agent_id}.json"
    for other in d.glob("*.json"):  # a dead agent's file on the same control port is stale: drop it
        e = _entry(other)
        if other != path and e.get("port") == port and not process_alive(e.get("pid")):
            other.unlink(missing_ok=True)
    entry = {"id": agent_id, "kind": kind, "pid": os.getpid() if pid is None else pid, "port": port,
             "frame_slot": frame_slot, "token": token, "started": time.time()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry), encoding="utf-8")
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def _entry(p: Path) -> dict:
    try:
        e = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return e if isinstance(e, dict) else {}


def unregister(root: Path, agent_id: str) -> None:
    try:
        (_dir(root) / f"{agent_id}.json").unlink()
    except FileNotFoundError:
        pass


def list_agents(root: Path) -> list[dict]:
    out: list[dict] = []
    for p in _dir(root).glob("*.json"):
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        if process_alive(entry.get("pid")):
            out.append(entry)
        else:  # prune: a dead agent's file would otherwise accumulate forever
            p.unlink(missing_ok=True)
    return sorted(out, key=lambda e: str(e.get("id", "")))
