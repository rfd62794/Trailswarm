"""Brain tools CLI - the same commands as ``pokeagent brain`` (JSON output by default).

    uv run python tools/brain.py maps
    uv run python tools/brain.py map 12 --overlay visits
    uv run python tools/brain.py tile 12 3 4
    uv run python tools/brain.py find --kind trainer --text "FIGHT"
    uv run python tools/brain.py edit wall_add 12 "3,4,UP" --note "sign is not a wall"
    uv run python tools/brain.py apply --backup
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.cli_brain import main

if __name__ == "__main__":
    raise SystemExit(main())
