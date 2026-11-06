"""Launcher: ``uv run python tools/view.py [--fake N] [--web]`` -> pokeagent.viewer.app."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.viewer.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
