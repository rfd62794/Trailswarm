"""Agent positions for the overlay: transitions files (``runs/explore-*/transitions.jsonl``) + the agents registry."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from pokeagent.atlas.overlay import Agent


def read_agent(path: Path, trail: int = 80, agent_id: str | None = None) -> Agent | None:
    """Last position and a ``trail``-long tail of distinct positions from one transitions.jsonl (None when empty)."""
    pts: deque[tuple[int, int, int]] = deque(maxlen=trail)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    to = json.loads(line).get("to")
                except ValueError:
                    continue            # a partial last line while the agent is writing
                if isinstance(to, list) and len(to) == 3 and (not pts or pts[-1] != tuple(to)):
                    pts.append((int(to[0]), int(to[1]), int(to[2])))
    except OSError:
        return None
    if not pts:
        return None
    m, x, y = pts[-1]
    return Agent(agent_id or Path(path).parent.name.rsplit("-", 1)[-1], m, x, y, list(pts))


def registry_ids(agents_dir: Path) -> dict[str, str]:
    """pid -> registered agent id from ``runs/agents/*.json`` (pids name the explore-<ts>-<pid> run directories)."""
    out: dict[str, str] = {}
    for p in sorted(Path(agents_dir).glob("*.json")):
        try:
            e = json.loads(p.read_text(encoding="utf-8"))
            out[str(e["pid"])] = str(e.get("id", p.stem))
        except (OSError, ValueError, KeyError):
            continue
    return out


def load_agents(transitions: list[Path], agents_dir: Path | None = None, trail: int = 80) -> list[Agent]:
    ids = registry_ids(agents_dir) if agents_dir else {}
    out = []
    for t in transitions:
        pid = Path(t).parent.name.rsplit("-", 1)[-1]
        a = read_agent(Path(t), trail, ids.get(pid, pid))
        if a:
            out.append(a)
    return out
