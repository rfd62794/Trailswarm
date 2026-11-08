"""Launcher: ``uv run python tools/map_view.py runs/mario-land [--fps 60] [--refresh 2.0]``."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.mapview.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
