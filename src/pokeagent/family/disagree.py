"""Find the facts in an agent's map record that contradict the shared doc (rules: Family_Shared_Memory_Directive)."""
from __future__ import annotations

from pokeagent.compat.ledges import classify_wall, parse_edge

_D = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def _wall_findings(mid: str, shared_map: dict, agent_map: dict) -> list[dict]:
    out = []
    have = set(agent_map.get("blocked") or [])
    paths, seen = agent_map.get("paths") or {}, agent_map.get("visited") or {}
    for edge in shared_map.get("blocked") or []:
        if edge in have:
            continue
        try:
            x, y, b = parse_edge(edge)
        except ValueError:
            continue
        if classify_wall(shared_map, edge) != "plain":
            continue  # one-way terrain is never evidence against a wall
        dx, dy = _D[b]
        to = (paths.get(edge) or {}).get("to") if isinstance(paths.get(edge), dict) else None
        if to is not None and list(to)[:2] == [x + dx, y + dy]:
            out.append({"section": "blocked_not", "key": edge, "value": edge, "kind": "wall_open"})
        elif f"{x},{y}" in seen and f"{x + dx},{y + dy}" in seen:
            out.append({"section": "blocked", "key": edge, "value": None, "kind": "wall_suspect"})
    return out


def find_disagreements(shared_map: dict, agent_map: dict, game, mid: str) -> list[dict]:
    """Rows ``{section, key, value, kind}``; ``value`` is what goes to the overlay (None = report only)."""
    out = []
    for sec, kind in (("warps", "warp_diff"), ("jumps", "jump_diff")):
        sv = shared_map.get(sec) or {}
        for k, v in (agent_map.get(sec) or {}).items():
            if k in sv and sv[k] != v:
                out.append({"section": sec, "key": k, "value": v, "kind": kind})
    sn = shared_map.get("npcs") or {}
    for k, n in (agent_map.get("npcs") or {}).items():
        s = sn.get(k)
        if isinstance(s, dict) and isinstance(n, dict) and not s.get("moves") and not n.get("moves") \
                and n.get("last") is not None and s.get("last") != n.get("last"):
            out.append({"section": "npcs", "key": k, "value": n, "kind": "npc_diff"})
    return out + _wall_findings(mid, shared_map, agent_map)
