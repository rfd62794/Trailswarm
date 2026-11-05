"""The campaign goal order has one source: pokeagent.goals. Guard against copies."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "tools/explore_demo.py",
    "tools/overnight.py",
    "tools/swarm.py",
    "tools/review_runs.py",
    "tools/status.py",
]

EXPECTED = ["potion", "left_house", "first_pokemon", "won_battle",
            "to_route1", "to_viridian", "oaks_parcel", "deliver_parcel",
            "to_route2", "to_pewter", "to_gym", "beat_brock"]


def test_goals_literal_lives_only_in_pokeagent_goals() -> None:
    offenders = []
    for f in FILES:
        src = (ROOT / f).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "GOALS" for t in node.targets)
                    and isinstance(node.value, (ast.List, ast.Tuple))
                    and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts)):
                offenders.append(f)
    assert not offenders, f"GOALS literal duplicated in: {offenders} (use pokeagent.goals.GOALS)"


def test_tools_use_the_shared_goals_module() -> None:
    missing = [f for f in FILES if "pokeagent.goals" not in (ROOT / f).read_text(encoding="utf-8")
               and "review_runs" not in (ROOT / f).read_text(encoding="utf-8")]
    assert not missing, f"not wired to shared goals: {missing}"


def test_canonical_goal_list() -> None:
    import pokeagent.goals as g
    assert list(g.GOALS) == EXPECTED
