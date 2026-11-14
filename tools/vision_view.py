"""Show what the cheap vision model "sees" in a native Dear PyGui window.

    uv run python tools/vision_view.py --game pokemon-red [--root runs/vision/pokemon-red] \
        [--model runs/vision_models/pokemon-red] [--frames 6] [--png-only --out runs/vision_models/pokemon-red/view]

Local data only: the pictures are ROM-derived, so PNGs go under a runs/ directory
(gitignored) and nothing is ever uploaded. Needs `uv sync --group vision` (torch).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.vision_model import view


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Native viewer for the cheap vision model.")
    ap.add_argument("--game", required=True)
    ap.add_argument("--root")
    ap.add_argument("--model")
    ap.add_argument("--out")
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--png-only", action="store_true", help="write PNGs under runs/, open no window")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    root = Path(a.root) if a.root else Path("runs") / "vision" / a.game
    model = Path(a.model) if a.model else Path("runs") / "vision_models" / a.game
    out = Path(a.out) if a.out else model / "view"
    if a.png_only and not view.out_allowed(out):
        print(f"error: --out {out} is not inside a runs directory", file=sys.stderr)
        return 2
    if not root.is_dir() or not (model / "report.json").is_file():
        print(f"error: need dataset {root} and trained model {model} (vision_record, vision_train)",
              file=sys.stderr)
        return 2
    try:
        import torch  # noqa: F401
    except ImportError:
        print("torch is not installed; `uv sync --group vision` is needed", file=sys.stderr)
        return 2
    panels = view.build(root, model, a.frames)
    if a.png_only:
        for p in view.save_pngs(panels, out):
            print(p)
        return 0
    from pokeagent.vision_model import view_window
    return view_window.run(panels, f"Vision viewer - {a.game}")


if __name__ == "__main__":
    sys.exit(main())
