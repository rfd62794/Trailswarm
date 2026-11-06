"""agentctl: read any live agent's situation and nudge it safely (the directive's CLI).

    uv run python tools/agentctl.py ls                       # ranked digest table, furthest agent first
    uv run python tools/agentctl.py show closest|stuck|<id>  # detailed block for one agent
    uv run python tools/agentctl.py hold <agent> [seconds]   # lease: the agent makes no own decisions (default 120 s)
    uv run python tools/agentctl.py release <agent>
    uv run python tools/agentctl.py press <agent> A B UP ...
    uv run python tools/agentctl.py macro <agent> back_out|battle_run|battle_fight|use_item|switch|goto|wait [k=v ...]
    uv run python tools/agentctl.py nudge <agent|closest>    # hold 120 s, back_out, battle_run if a wild battle is open, release

``<agent>`` is an id, a unique fragment of one, ``closest`` (furthest goal stage) or ``stuck``. ``--root`` (or POKEAGENT_ROOT)
is the checkout whose ``runs/agents`` registry to read; every intervention is journaled to ``<root>/runs/agent_interventions.jsonl``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.intervene import client, ops  # noqa: E402
from pokeagent.intervene.client import AgentError  # noqa: E402
from pokeagent.intervene.digest import format_block, format_table  # noqa: E402
from pokeagent.intervene.macros import macro_names  # noqa: E402


def parse_kv(pairs: list[str]) -> dict:
    """['move=BITE', 'x=5'] -> {'move': 'BITE', 'x': 5}  (digits become ints)."""
    out: dict = {}
    for p in pairs:
        key, sep, val = p.partition("=")
        if not sep or not key:
            raise SystemExit(f"bad argument {p!r}: use key=value")
        out[key] = int(val) if val.lstrip("-").isdigit() else val
    return out


def show_row(row: dict) -> str:
    """The before / result / after text an intervention prints."""
    parts = [f"== {row['action']} on {row['agent']}: {json.dumps(row['result'], default=str)}"]
    for label in ("before", "after"):
        d = row[f"digest_{label}"]
        parts.append(f"-- {label}\n" + (format_block(d) if "error" not in d else f"unreachable: {d['error']}"))
    return "\n".join(parts)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="agentctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help="checkout whose runs/agents to read (default $POKEAGENT_ROOT or .)")
    ap.add_argument("--by", default="claude", help="who is intervening (journal field)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ls")
    for name in ("show", "release", "nudge"):
        sub.add_parser(name).add_argument("agent")
    h = sub.add_parser("hold"); h.add_argument("agent"); h.add_argument("seconds", nargs="?", type=int, default=ops.NUDGE_HOLD_S)
    p = sub.add_parser("press"); p.add_argument("agent"); p.add_argument("buttons", nargs="+")
    m = sub.add_parser("macro", help="macros: " + ", ".join(macro_names()))
    m.add_argument("agent"); m.add_argument("name"); m.add_argument("kv", nargs="*")
    return ap


def main(argv=None, out=print) -> int:
    a = build_parser().parse_args(argv)
    root = client.root_dir(a.root)
    try:
        if a.cmd == "ls":
            out(format_table(client.digests(root)))
            return 0
        entry = client.resolve(root, a.agent)
        if a.cmd == "show":
            out(format_block(client.digest_of(entry)))
            return 0
        if a.cmd == "hold":
            row = ops.hold(root, entry, a.seconds, a.by)
        elif a.cmd == "release":
            row = ops.release(root, entry, a.by)
        elif a.cmd == "press":
            row = ops.press(root, entry, a.buttons, a.by)
        elif a.cmd == "macro":
            row = ops.macro(root, entry, a.name, parse_kv(a.kv), a.by)
        else:
            row = ops.nudge(root, entry, a.by)
    except AgentError as exc:
        print(f"agentctl: {exc}", file=sys.stderr)
        return 2
    out(show_row(row))
    return 0 if row["result"].get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
