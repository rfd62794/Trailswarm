"""Inspect savestate metadata sidecars.

    uv run python tools/state_info.py runs/checkpoints/*.state
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

from pokeagent.statemeta import describe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=["runs/checkpoints/*.state"],
                        help="savestate paths/globs to inspect")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    paths = []
    for pattern in args.paths:
        matches = sorted(glob.glob(pattern))
        paths.extend(matches or [pattern])
    rows = []
    for path in paths:
        try:
            meta = describe(Path(path))
        except FileNotFoundError:
            meta = {"path": path, "error": "missing"}
        rows.append(meta)
    if args.compact:
        for row in rows:
            game = row.get("game") or {}
            print(f"{row['path']} map={game.get('map_id')} pos=({game.get('x')},{game.get('y')}) "
                  f"segment={row.get('segment')} verified={row.get('verified')} digest={str(row.get('digest'))[:12]}")
    else:
        print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
