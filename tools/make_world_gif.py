"""Build docs/media/world.gif: replay real overnight explore runs on the ROM-rendered Kanto map (headless, files only).

    uv run python tools/make_world_gif.py --rom "C:/path/Pokemon Red.gb" --base runs/atlas/world.png \
        --runs runs/explore-A runs/explore-B ... --out docs/media/world.gif

The base map is rendered once, cropped to the agents' bounding box; agents and trails are then drawn with PIL.
Every run is replayed over the same normalised timeline. Indoors an agent is a hollow circle at the door.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from pokeagent.world.export import export_png, load_world

CELL = 16
MARGIN = 8                                   # cells around the agents' bounding box
COLORS = [(230, 25, 75), (0, 130, 200), (245, 130, 48), (60, 180, 75), (145, 30, 180), (240, 50, 230), (0, 190, 190), (200, 170, 0)]


def load_steps(run: Path, world) -> list[tuple[int, int, int, bool]]:
    """(map, x, y, indoors) per step; indoor steps keep the last outdoor position (the door)."""
    out, last = [], None
    for line in (run / "transitions.jsonl").open(encoding="utf-8"):
        try:
            m, x, y = json.loads(line)["to"]
        except (ValueError, KeyError):
            continue
        p = world.layout.places.get(m)
        if p is None:
            continue
        if not p.interior:
            last = (m, x, y)
        if last:
            out.append((*last, p.interior))
    return out


def world_px(world, m: int, x: int, y: int) -> tuple[int, int]:
    px, py = world.layout.to_world(m, x, y)
    return px + CELL // 2, py + CELL // 2


def draw_frame(base: Image.Image, runs, t, world, origin, scale, trail, label) -> Image.Image:
    im = base.copy()
    d = ImageDraw.Draw(im)
    r = max(4, round(4.5 * scale / 0.5))
    pos = []
    for steps in runs:
        k = min(len(steps) - 1, int(t * len(steps)))
        pts = []
        for s in steps[max(0, k - trail * 8):k + 1:8][-trail:] + [steps[k]]:
            wx, wy = world_px(world, *s[:3])
            pts.append(((wx - origin[0]) * scale, (wy - origin[1]) * scale))
        pos.append((pts, steps[k][3]))
    for i, (pts, indoors) in enumerate(pos):
        c = COLORS[i % len(COLORS)]
        for j in range(1, len(pts)):
            f = j / len(pts)                                      # older segments fade towards the map grey
            col = tuple(int(g + (v - g) * f) for v, g in zip(c, (170, 170, 170)))
            d.line([pts[j - 1], pts[j]], fill=col, width=2 + (f > 0.6))
    for i, (pts, indoors) in enumerate(pos):
        c, (x, y) = COLORS[i % len(COLORS)], pos[i][0][-1]
        box = [x - r, y - r, x + r, y + r]
        d.ellipse(box, fill=None if indoors else c, outline=(0, 0, 0) if not indoors else c, width=2 if indoors else 1)
    d.rectangle([0, 0, 8 + 7 * len(label), 20], fill=(0, 0, 0))
    d.text((5, 5), label, fill=(255, 255, 255))
    return im


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", default="docs/media/world.gif")
    ap.add_argument("--frames", type=int, default=75)
    ap.add_argument("--size", type=int, default=850, help="longest side in px after the crop")
    ap.add_argument("--trail", type=int, default=15)
    ap.add_argument("--colors", type=int, default=64)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--keep-frames", help="also save each frame as PNG into this directory")
    a = ap.parse_args()
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    world = load_world(a.rom, base=a.base)
    runs = [r for r in (load_steps(Path(p), world) for p in a.runs) if r]
    pts = [world_px(world, *s[:3]) for r in runs for s in r]
    maps = {s[0] for r in runs for s in r}                     # the outdoor maps the agents actually walked
    pad = MARGIN * CELL
    x0, y0 = max(0, min(p[0] for p in pts) - pad) // CELL * CELL, max(0, min(p[1] for p in pts) - pad) // CELL * CELL
    x1, y1 = max(p[0] for p in pts) + pad, max(p[1] for p in pts) + pad
    scale = a.size / max(x1 - x0, y1 - y0)
    with tempfile.TemporaryDirectory() as tmp:
        bp = Path(tmp) / "base.png"
        export_png(bp, world, [], None, (), crop=(x0, y0, x1, y1), scale=scale, now=0.0)
        base = Image.open(bp).convert("RGB")
    keep = Image.new("L", base.size, 0)                        # grey out stitched maps nobody visited
    kd = ImageDraw.Draw(keep)
    for m in maps:
        pl = world.layout.places[m]
        kd.rectangle([(pl.x * CELL - x0) * scale, (pl.y * CELL - y0) * scale, (pl.x + pl.w) * CELL * scale - x0 * scale,
                      (pl.y + pl.h) * CELL * scale - y0 * scale], fill=255)
    base = Image.composite(base, Image.new("RGB", base.size, (205, 205, 205)), keep)
    print(f"crop cells x{x0 // CELL}-{x1 // CELL} y{y0 // CELL}-{y1 // CELL}, base {base.size}", file=sys.stderr)
    label = f"overnight swarm, {len(runs)} agents"
    imgs = [draw_frame(base, runs, n / (a.frames - 1), world, (x0, y0), scale, a.trail, label) for n in range(a.frames)]
    if a.keep_frames:
        Path(a.keep_frames).mkdir(parents=True, exist_ok=True)
        for n, im in enumerate(imgs):
            im.save(Path(a.keep_frames) / f"f{n:03d}.png")
    pal = imgs[len(imgs) // 2].quantize(colors=a.colors, method=Image.Quantize.MEDIANCUT)
    frames = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in imgs]
    frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=1000 // a.fps, loop=0, optimize=True)
    print(f"wrote {a.out} ({Path(a.out).stat().st_size / 1e6:.2f} MB, {len(frames)} frames, {imgs[0].size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
