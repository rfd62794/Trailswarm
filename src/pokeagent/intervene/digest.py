"""Situation digest: one line per agent and a detailed block for one, pure functions of a snapshot dict.

The snapshot is ``AgentSnapshot.to_dict()``; the extras the snapshot itself lacks (map id, x/y, mode, battle, bag, recent
decisions) come in ``snap["extra"]`` (built agent-side by ``intervene.extra``). Agents rank by progress: furthest goal
stage first, so the closest agent is row 1.
"""
from __future__ import annotations

import re

from pokeagent.goals import GOALS, SIDE_GOALS
from pokeagent.intervene.names import map_name
from pokeagent.intervene.stuck import stuck_signals

KEY_ITEM = re.compile(r"POTION|BALL|ROPE|REVIVE|ANTIDOTE|HEAL|ETHER|ELIXER|ESCAPE|REPEL|AWAKENING|BURN|ICE|PARLYZ", re.I)
LADDER = [g for g in GOALS if g not in SIDE_GOALS]


def _mon(m: dict) -> str:
    return f"{m.get('species', '?')} L{m.get('level', 0)} {m.get('hp', 0)}/{m.get('max_hp', m.get('max', 0))}"


def _battle_text(b: dict | None) -> str:
    if not b:
        return ""
    you, foe = b.get("you", {}), b.get("enemy", {})
    return (f"{b.get('kind', '?')}: {you.get('species', '?')} L{you.get('level', 0)} {you.get('hp', 0)}/{you.get('max', 0)}"
            f" vs {foe.get('species', '?')} L{foe.get('level', 0)} {foe.get('hp', 0)}/{foe.get('max', 0)}")


def stage_of(goals: list[dict]) -> tuple[str, int]:
    """(current goal id or 'done', ladder goals already reached)."""
    done = sum(1 for g in goals if g.get("status") == "done" and g.get("id") in LADDER)
    cur = next((g["id"] for g in goals if g.get("status") == "current"), "done" if done else "?")
    return cur, done


def digest_agent(snap: dict) -> dict:
    """The structured digest of one snapshot dict."""
    extra = snap.get("extra") or {}
    scr = snap.get("screen", {})
    stage, done = stage_of(snap.get("goals", []))
    bag = {n: q for n, q in (extra.get("bag") or {}).items() if KEY_ITEM.search(n)}
    decs = extra.get("decisions", [])[-8:]
    return {
        "id": snap.get("agent_id", "?"), "state": snap.get("state", "?"), "step": snap.get("step", 0),
        "map": extra.get("map"), "map_name": map_name(extra["map"]) if extra.get("map") is not None else "?",
        "x": extra.get("x"), "y": extra.get("y"),
        "stage": stage, "done": done, "total": len(LADDER),
        "mode": extra.get("mode") or ("battle" if scr.get("in_battle") else "overworld"),
        "battle": extra.get("battle"), "battle_text": _battle_text(extra.get("battle")),
        "party": [_mon(m) for m in scr.get("party", [])], "money": scr.get("money"),
        "bag": bag, "potions": any("POTION" in n.upper() and q > 0 for n, q in bag.items()),
        "decisions": [f"{d.get('r', '?')}:{d.get('b', '')}" + ("*claude" if d.get("d") == "claude" else "") for d in decs],
        "stuck": stuck_signals(snap), "box_text": scr.get("box_text", ""),
        "lease": "claude_hold_s" in snap, "macro": extra.get("macro_status"), "claude_hold_s": round(float(snap.get("claude_hold_s", 0) or 0), 1), "human_hold": bool(snap.get("human_hold")),
    }


def rank(digests: list[dict]) -> list[dict]:
    """Furthest goal stage first; ties by step count (more steps = further along)."""
    return sorted(digests, key=lambda d: (-d.get("done", 0), -d.get("step", 0), d.get("id", "")))


def where(d: dict) -> str:
    return f"{d['map_name']} ({d['x']},{d['y']})" if d.get("x") is not None else d.get("map_name", "?")


def hold_text(d: dict) -> str:
    return " ".join(t for t in (f"claude {d['claude_hold_s']:g}s" if d.get("claude_hold_s") else "",
                                "human" if d.get("human_hold") else "") if t)


def line(d: dict) -> str:
    """One compact line: the table row `ls` prints (columns aligned by format_table)."""
    return "  ".join(row_cells(d))


def row_cells(d: dict) -> list[str]:
    lead = d["party"][0] if d.get("party") else "-"
    stuck = ",".join(s["kind"] for s in d.get("stuck", [])) or "-"
    mode = d["mode"] + (f"/{d['battle']['kind']}" if d.get("battle") else "")
    hold = hold_text(d)
    return [d["id"], where(d), f"{d['stage']} {d['done']}/{d['total']}", mode, lead,
            f"${d['money']}" if d.get("money") is not None else "$?", f"STUCK:{stuck}" if stuck != "-" else "ok",
            f"HELD:{hold}" if hold else ("" if d.get("lease", True) else "no-lease")]


def format_table(digests: list[dict]) -> str:
    """Ranked table, columns padded; unreachable agents (a digest with only id/error) listed last."""
    rows = [row_cells(d) for d in rank([d for d in digests if "error" not in d])]
    rows += [[d["id"], f"unreachable: {d['error']}"] for d in digests if "error" in d]
    if not rows:
        return "no agents registered"
    widths = [max(len(r[i]) for r in rows if len(r) > i) for i in range(max(len(r) for r in rows))]
    return "\n".join("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows)


def format_block(d: dict) -> str:
    """The detailed block `show` prints for one agent."""
    out = [f"{d['id']}  [{d['state']}]  step {d['step']}" + (f"  HELD: {hold_text(d)}" if hold_text(d) else ""),
           f"where : {where(d)}", f"goal  : {d['stage']}  ({d['done']}/{d['total']} stages done)", f"mode  : {d['mode']}"]
    if d.get("battle_text"):
        out.append(f"battle: {d['battle_text']}")
    out.append("party : " + (" | ".join(d["party"]) or "-"))
    bag = ", ".join(f"{n} x{q}" for n, q in d["bag"].items()) or "none"
    out.append(f"money : {d['money'] if d.get('money') is not None else '?'}   bag: {bag}" + ("" if d["potions"] else "   (NO POTION)"))
    if d.get("box_text"):
        out.append(f"box   : {d['box_text'][:120]}")
    if d.get("macro"):
        m = d["macro"]
        out.append(f"macro : {m.get('name')} {m.get('state')} {m.get('result') or ''} ({m.get('presses')} presses, {m.get('age_s')}s)".rstrip())
    if not d.get("lease", True):
        out.append("lease : lease unsupported (old agent code)")
    out.append("last 8: " + (", ".join(d["decisions"]) or "-"))
    out.append("stuck : " + ("; ".join(f"{s['kind']} - {s['reason']}" for s in d["stuck"]) or "no signals"))
    return "\n".join(out)
