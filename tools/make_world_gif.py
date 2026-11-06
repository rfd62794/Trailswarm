"""Build docs/media/world.gif: replay real overnight explore runs on the ROM-rendered Kanto map (headless, files only).

    uv run python tools/make_world_gif.py --rom "C:/path/Pokemon Red.gb" --base runs/atlas/world.png \
        --runs runs/explore-A runs/explore-B ... --out docs/media/world.gif --frames-dir <dir for PNG frames>

Each run's transitions.jsonl is replayed over the same normalised timeline, so every agent crosses the map in the GIF.
Positions inside buildings are drawn at the door (the interiors sit outside the crop).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

from pokeagent.world.export import export_png, load_world
from pokeagent.world.model import Track

CROP_CELLS = (48, 36, 232, 262)      # x0, y0, x1, y1 in map cells: Pallet Town up to Cerulean and Route 4
CELL = 16


def load_steps(run: Path, world) -> list[tuple[int, int, int, str]]:
    """(map, x, y, facing) per step; indoor steps repeat the last outdoor position."""
    out, last = [], None
    for line in (run / "transitions.jsonl").open(encoding="utf-8"):
        try:
            r = json.loads(line)
            m, x, y = r["to"]
        except (ValueError, KeyError):
            continue
        p = world.layout.places.get(m)
        if p is not None and not p.interior:
            last = (m, x, y, r.get("facing") or "DOWN")
        if last:
            out.append(last)
    return out


def build_tracks(runs: list[list], t: float, trail: int) -> list[Track]:
    tracks = []
    for i, steps in enumerate(runs):
        if not steps:
            continue
        k = min(len(steps) - 1, int(t * len(steps)))
        m, x, y, f = steps[k]
        tr = Track(f"agent-{i + 1}", map=m, x=x, y=y, facing=f, moved_at=-10.0, step=k)
        for s in steps[max(0, k - trail * 6):k + 1:6]:       # thin the trail so it stays a line, not a smear
            tr.path.append(s[:3])
        tracks.append(tr)
    return tracks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", default="docs/media/world.gif")
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--frames", type=int, default=75)
    ap.add_argument("--scale", type=float, default=0.3)
    ap.add_argument("--trail", type=int, default=40)
    ap.add_argument("--colors", type=int, default=64)
    ap.add_argument("--fps", type=int, default=10)
    a = ap.parse_args()
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    world = load_world(a.rom, base=a.base)
    runs = [load_steps(Path(r), world) for r in a.runs]
    crop = tuple(c * CELL for c in CROP_CELLS)
    fdir = Path(a.frames_dir)
    fdir.mkdir(parents=True, exist_ok=True)
    imgs = []
    for n in range(a.frames):
        t = n / (a.frames - 1)
        p = fdir / f"f{n:03d}.png"
        export_png(p, world, build_tracks(runs, t, a.trail), None, (), crop=crop,
                   scale=a.scale, now=0.0, interiors="inset")
        imgs.append(Image.open(p).convert("RGB"))
        print(f"frame {n + 1}/{a.frames}", file=sys.stderr)
    pal = imgs[len(imgs) // 2].quantize(colors=a.colors, method=Image.Quantize.MEDIANCUT)
    frames = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in imgs]
    frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=1000 // a.fps, loop=0, optimize=True)
    print(f"wrote {a.out} ({Path(a.out).stat().st_size / 1e6:.2f} MB, {len(frames)} frames, {imgs[0].size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
