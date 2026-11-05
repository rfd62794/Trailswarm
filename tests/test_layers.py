"""Layer-direction guard: src/pokeagent must not import up into tools/."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "pokeagent"


def test_package_never_imports_tools() -> None:
    bad = []
    for f in SRC.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mod = getattr(node, "module", "") or ""
            names = [a.name for a in getattr(node, "names", [])]
            if (isinstance(node, (ast.Import, ast.ImportFrom))
                    and (mod == "tools" or mod.startswith("tools.") or any(n in ("explore_demo", "explore_plan") for n in names))):
                bad.append((f.name, getattr(node, "lineno", 0), mod or ",".join(names)))
    assert not bad, f"src/pokeagent imports tools code (upward dependency): {bad}"
