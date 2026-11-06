"""World loading (ROM -> layout + stitched image, cached on disk) and PNG export. Headless: writes files only."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from pokeagent.atlas.rom_maps import MapHeader, all_headers, load
from pokeagent.atlas.world import WorldLayout, build_layout
from pokeagent.atlas.world_render import render_world
from pokeagent.world.draw import SpriteBook, render_state
from pokeagent.world.model import Track

Image.MAX_IMAGE_PIXELS = None
CACHE = Path("runs") / "atlas" / "world.png"


@dataclass
class World:
    rom: bytes
    headers: dict[int, MapHeader]
    layout: WorldLayout
    base: np.ndarray
    book: SpriteBook


def load_world(rom_path: str | Path = "roms/Pokemon Red.gb", cache: Path | None = CACHE, base: str | Path | None = None) -> World:
    """Decode the ROM and stitch Kanto. ``base`` / ``cache`` name a previously rendered world.png (skips the slow render);
    a fresh render is written to ``cache`` (runs/ is git-ignored: never commit it, it is ROM-derived)."""
    rom = load(rom_path)
    headers = all_headers(rom)
    layout = build_layout(headers)
    src = Path(base) if base else cache
    if src is not None and src.exists():
        img = np.asarray(Image.open(src).convert("RGB"))
        if (img.shape[1], img.shape[0]) == layout.size_px:
            return World(rom, headers, layout, img, SpriteBook(rom))
    img = render_world(rom, headers, layout, False)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(img).save(cache)
    return World(rom, headers, layout, img, SpriteBook(rom))


def fake_tracks(layout: WorldLayout, n: int = 4, now: float = 0.0) -> list[Track]:
    """``n`` fake agents at known spots: Pallet Town (0), Viridian (1), Pewter (2), Cerulean (3), Vermilion (5), Lavender (4)."""
    spots = [(0, 5, 6, "DOWN"), (1, 12, 10, "UP"), (2, 10, 9, "LEFT"), (3, 14, 10, "RIGHT"), (5, 14, 12, "DOWN"), (4, 6, 8, "UP")]
    out = []
    for i, (m, x, y, f) in enumerate(spots[:n]):
        t = Track(f"agent-{i + 1}", map=m, x=x, y=y, facing=f, moved_at=now - 10, step=100 * i)
        for k in range(12):
            t.path.append((m, x - k if f in ("RIGHT", "DOWN") else x + k, y))
        out.append(t)
    return out


def export_png(path: str | Path, world: World, tracks: list[Track], model: dict | None = None, layers: tuple[str, ...] = (),
               crop: tuple[int, int, int, int] | None = None, scale: float = 1.0, now: float | None = None) -> tuple[int, int]:
    img = render_state(world.base, world.layout, tracks, world.book, time.monotonic() if now is None else now, model,
                       world.headers, layers, crop=crop, scale=scale)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(path)
    return img.shape[1], img.shape[0]
