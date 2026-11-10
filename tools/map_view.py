"""Launcher: ``uv run python tools/map_view.py runs/mario-land [--game super-mario-land] [--fps 60] [--refresh 2.0]`` —
the stitched map inside the unified viewer's World mode (one window, one agent list, one selection)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.viewer import app as viewer_app  # noqa: E402


def args_for(source, game=None, preset=None, genre=None, fps=None, refresh=None) -> list[str]:
    """The ``pokeagent view`` argv for a stitched source (pure; tested)."""
    argv = ["--mode", "world", "--source", Path(source).as_posix()]
    if game:
        argv += ["--game", game]
    if preset:
        argv += ["--preset", preset]
    if genre:
        argv += ["--genre", genre]
    if fps is not None:
        argv += ["--fps", str(fps)]
    if refresh is not None:
        argv += ["--refresh", str(refresh)]
    return argv


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="map_view",
                                description="Every captured area in one space, every ghost replayed together.")
    p.add_argument("source", type=Path, help="run dir holding maps/index.json + images and ghosts/*.json")
    p.add_argument("--game", help="named game row of the preset table")
    p.add_argument("--preset", help="named view preset (wins over --game)")
    p.add_argument("--genre", help="named genre fallback when --game/--preset are absent")
    p.add_argument("--fps", type=int, help="poll/UI rate (viewer default 30)")
    p.add_argument("--refresh", type=float, help="re-read cadence in seconds (default 2)")
    a = p.parse_args(argv)
    return viewer_app.main(args_for(a.source, a.game, a.preset, a.genre, a.fps, a.refresh))


if __name__ == "__main__":
    raise SystemExit(main())
