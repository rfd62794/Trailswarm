"""Backtracking report for one explorer run: immediate reversals and back-in-2 over agent moves.

    uv run python tools/backtrack_report.py RUN_DIR

Reads RUN_DIR/transitions.jsonl (or a .jsonl path directly). An "agent move" is a press with
source "agent" that changed position (moved=true). Prints how often a move undid the previous
one, and how often it landed on the tile stood on two moves earlier - the two numbers the
exploration-momentum work is measured against.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def agent_moves(path: Path) -> list[tuple]:
    """(from, to) of each agent press that moved the player, in order."""
    moves = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("source", "agent") == "agent" and r.get("moved"):
            moves.append((tuple(r["from"]), tuple(r["to"])))
    return moves


def backtrack_stats(path: Path) -> dict:
    """Counts and percentages for the two backtracking metrics over agent moves."""
    moves = agent_moves(path)
    rev = sum(1 for i in range(1, len(moves)) if moves[i][1] == moves[i - 1][0])
    back2 = sum(1 for i in range(2, len(moves)) if moves[i][1] == moves[i - 2][1])
    n = len(moves)
    return {"moves": n, "reversals": rev, "back_in_2": back2,
            "reversal_pct": 100.0 * rev / n if n else 0.0,
            "back2_pct": 100.0 * back2 / n if n else 0.0}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: uv run python tools/backtrack_report.py RUN_DIR")
        return 2
    path = Path(args[0])
    if path.is_dir():
        path = path / "transitions.jsonl"
    if not path.exists():
        print(f"no transitions.jsonl at {path}")
        return 1
    s = backtrack_stats(path)
    print(f"{path}: {s['moves']} agent moves; immediate reversals {s['reversals']} ({s['reversal_pct']:.1f}%); "
          f"back-in-2 {s['back_in_2']} ({s['back2_pct']:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
