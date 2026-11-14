"""The package imports with torch absent; torch stays an optional group only."""
from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MODULES = ("import pokeagent\n"
           "import pokeagent.vision_model\n"
           "import pokeagent.vision_model.data\n"
           "import pokeagent.vision_model.split\n"
           "import pokeagent.vision_model.template\n"
           "import pokeagent.vision_model.metrics\n"
           "import pokeagent.vision_model.net\n"
           "import pokeagent.vision_model.bench\n"
           "import pokeagent.vision_model.export\n")


def test_imports_with_torch_blocked():
    """sys.modules['torch'] = None makes any `import torch` raise ImportError."""
    code = "import sys\nsys.modules['torch'] = None\n" + MODULES + "print('ok')\n"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr


def test_torch_only_in_vision_group():
    doc = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any("torch" in d for d in doc["project"]["dependencies"])
    assert any(d.startswith("torch") for d in doc["dependency-groups"]["vision"])
