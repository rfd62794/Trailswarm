"""vision_motion and tools/motion_train.py import in a process where torch cannot import."""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MODULES = (
    "pokeagent",
    "pokeagent.vision_motion",
    "pokeagent.vision_motion.tracks",
    "pokeagent.vision_motion.features",
    "pokeagent.vision_motion.movement",
    "pokeagent.vision_motion.nextpos",
    "pokeagent.vision_motion.nextpos_net",
    "pokeagent.vision_motion.blocked",
    "pokeagent.vision_motion.synthetic",
    "pokeagent.vision_motion.split",
    "pokeagent.vision_motion.location_data",
    "pokeagent.vision_motion.location_baseline",
    "pokeagent.vision_motion.location_net",
    "pokeagent.vision_motion.report",
)

NO_TORCH = "import sys\nsys.modules['torch'] = None\n"


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True)


def test_every_module_imports_with_torch_blocked():
    r = _run(NO_TORCH + "import " + ", ".join(MODULES))
    assert r.returncode == 0, r.stderr


def test_motion_train_tool_imports_with_torch_blocked():
    r = _run(NO_TORCH +
             "import importlib.util\n"
             "spec = importlib.util.spec_from_file_location('motion_train',"
             " 'tools/motion_train.py')\n"
             "m = importlib.util.module_from_spec(spec)\n"
             "spec.loader.exec_module(m)\n")
    assert r.returncode == 0, r.stderr


def test_torch_lives_only_in_the_vision_group():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any("torch" in d for d in data["project"]["dependencies"])
    assert any(d.startswith("torch") for d in data["dependency-groups"]["vision"])
