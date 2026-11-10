"""Launcher: ``uv run python tools/map_view.py runs/mario-land [--game super-mario-land]`` —
the stitched map inside the unified viewer's World mode (one window, one agent list, one selection)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.viewer import app as viewer_app  # noqa: E402


def args_for(source, game=None, preset=None, genre=None) -> list[str]:
    """The ``pokeagent view`` argv for a stitched source (pure; tested)."""
    argv = ["--mode", "world", "--source", Path(source).as_posix()]
    if game:
        argv += ["--game", game]
    if preset:
        argv += ["--preset", preset]
    if genre:
        argv += ["--genre", genre]
    return argv


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="map_view",
                                description="Every captured area in one space, every ghost replayed together.")
    p.add_argument("source", type=Path, help="run dir holding maps/index.json + images and ghosts/*.json")
    p.add_argument("--game", help="named game row of the preset table")
    p.add_argument("--preset", help="named view preset (wins over --game)")
    p.add_argument("--genre", help="named genre fallback when --game/--preset are absent")
    a = p.parse_args(argv)
    return viewer_app.main(args_for(a.source, a.game, a.preset, a.genre))


if __name__ == "__main__":
    raise SystemExit(main())
