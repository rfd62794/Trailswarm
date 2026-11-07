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
            "to_route2", "to_pewter", "to_gym", "beat_brock",
            "to_route3", "to_route4", "buy_magikarp", "to_mt_moon", "mt_moon_b1f", "mt_moon_b2f", "through_mt_moon", "to_cerulean",
            "heal_cerulean", "beat_misty", "nugget_bridge", "team_ready", "to_bill", "ss_ticket"]


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
    assert list(g.GOALS[:len(EXPECTED)]) == EXPECTED  # the ladder grew (data/campaign.json); the first 26 stay frozen


def test_side_goals_stay_empty_and_team_ready_sits_in_the_ladder() -> None:
    import pokeagent.goals as g
    assert g.SIDE_GOALS == []                                   # kept exported for its consumers; empty today
    assert not set(g.SIDE_GOALS) & set(g.GOALS)
    assert g.GOALS.index("team_ready") == g.GOALS.index("nugget_bridge") + 1  # a ladder goal now, never a blocker
    assert "gyarados" not in g.GOALS
    from pokeagent.emulator import FakeEmulator
    checked = g.check_goals(FakeEmulator({}), {"team_ready_nodata": True})
    assert checked["team_ready"]                                # settled: no boss data to judge by
    from pokeagent.explorer.decisions import goal_stage
    assert goal_stage({k: True for k in g.GOALS}) == "done"  # a missing side goal does not hold the ladder open
