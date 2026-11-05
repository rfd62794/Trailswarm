"""The campaign goal order is duplicated across tools/; keep the copies identical."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "tools/explore_demo.py",
    "tools/overnight.py",
    "tools/swarm.py",
    "tools/review_runs.py",
]


def goals_literals(path: Path) -> list[list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "GOALS" for t in node.targets)):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)) and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts
        ):
            found.append([e.value for e in node.value.elts])
    return found


def test_goal_order_matches_across_tools() -> None:
    per_file = {f: goals_literals(ROOT / f) for f in FILES}
    missing = [f for f, vals in per_file.items() if not vals]
    assert not missing, f"no GOALS literal found in: {missing}"
    unique = {tuple(vals[0]) for vals in per_file.values()}
    assert len(unique) == 1, f"GOALS literals differ across tools/: {per_file}"
