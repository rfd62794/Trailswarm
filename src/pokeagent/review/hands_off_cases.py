"""Hands-off regression case table: load and validate cases, decide skips, build the demo argv.

Pure: nothing here starts a process or touches ``runs/``. The ROM, baseline state and kb are
gitignored, so a missing input is a stated skip, never a failure.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path

GAME_ROMS = {"red": "roms/Pokemon Red.gb"}
MEMORY_MODES = ("none", "live")


@dataclass(frozen=True)
class Case:
    name: str
    game: str
    state: str
    memory: str
    goal: str
    budget: int
    seed: int


def _case(raw: dict) -> Case:
    name = raw.get("name", "<unnamed>") if isinstance(raw, dict) else "<unnamed>"
    if not isinstance(raw, dict):
        raise ValueError(f"case {name}: not an object")
    missing = [f.name for f in fields(Case) if f.name not in raw]
    if missing:
        raise ValueError(f"case {name}: missing field {', '.join(missing)}")
    budget = raw["budget"]
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        raise ValueError(f"case {name}: budget must be a positive integer, got {budget!r}")
    if raw["memory"] not in MEMORY_MODES:
        raise ValueError(f"case {name}: unknown memory {raw['memory']!r}")
    if str(raw["goal"]).startswith("map:"):
        try:
            int(raw["goal"][4:], 0)
        except ValueError:
            raise ValueError(f"case {name}: bad stop map {raw['goal']!r}") from None
    if raw["game"] not in GAME_ROMS:
        raise ValueError(f"case {name}: unknown game {raw['game']!r}")
    return Case(**{f.name: raw[f.name] for f in fields(Case)})


def load_cases(path: Path) -> list[Case]:
    """Every case in the table; ``ValueError`` naming the case on the first invalid one."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_case(raw) for raw in data.get("cases", [])]


def state_path(case: Case) -> str:
    """A bare name means ``baselines/<name>.state``; a ``*.state`` path (a saved leg state) is used as given."""
    if case.state.endswith(".state"):
        return case.state
    return f"baselines/{case.state}.state"


def stop_args(goal: str) -> list[str]:
    """``map:0x25`` is a segment stop map (``--stop-at-map``); anything else is a goal name."""
    if goal.startswith("map:"):
        return ["--stop-at-map", goal[4:]]
    return ["--stop-at-goal", goal]


def inputs(case: Case) -> list[str]:
    """Required local inputs, relative to the repo root, in skip-check order."""
    needed = [GAME_ROMS[case.game], state_path(case), "kb/rom_tables.json"]
    if case.memory == "live":
        needed.append("runs/maps.json")
    return needed


def skip_reason(case: Case, root: Path) -> str | None:
    """None when runnable, else ``"missing <first absent input>"``."""
    for rel in inputs(case):
        if not (Path(root) / rel).exists():
            return f"missing {rel}"
    return None


def build_argv(case: Case, index: int) -> list[str]:
    """Demo arguments after the interpreter; the run happens in a scratch copy of the repo."""
    return [
        "tools/explore_demo.py",
        "--headless",
        "--state", state_path(case),
        *stop_args(case.goal),
        "--steps", str(case.budget),
        "--seed", str(case.seed),
        "--maps", "runs/maps.json",
        "--control-port", str(9100 + index),
    ]
