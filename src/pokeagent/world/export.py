"""World loading (ROM -> layout + stitched image, cached on disk) and PNG export. Headless: writes files only."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from pokeagent.atlas.anchor import anchor_interiors
from pokeagent.atlas.fit import walk_cells
from pokeagent.atlas.inplace import plan_interiors
from pokeagent.atlas.overrides import Overrides
from pokeagent.atlas.stretch import stretch_image, stretch_layout, stretch_warp
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


def stretch_world(world: World, model: dict | None = None, overrides: Overrides | None = None,
                  walk_cache: dict | None = None) -> World:
    """The same Kanto with the outdoor world locally stretched so every in-place interior fits its building at full size."""
    cache = walk_cache if walk_cache is not None else {}
    lay, hd = world.layout, world.headers

    def walk(m: int):
        if m not in cache:
            cache[m] = walk_cells(world.rom, hd[m]) if m in hd else None
        return cache[m]

    ov = overrides or Overrides()
    anchors = anchor_interiors(hd, lay, model)
    warp = stretch_warp(anchors, lay, walk, ov.bands)
    return World(world.rom, hd, stretch_layout(lay, warp), stretch_image(world.base, lay, warp), world.book)


def export_png(path: str | Path, world: World, tracks: list[Track], model: dict | None = None, layers: tuple[str, ...] = (),
               crop: tuple[int, int, int, int] | None = None, scale: float = 1.0, now: float | None = None,
               interiors: str = "inset", overrides: Overrides | None = None) -> tuple[int, int]:
    """Render the world state to a PNG. ``interiors``: inset | inplace (fit) | inplace_full | auto | stretch (stretched world,
    full-size in place). With ``stretch`` the ``crop`` is in the stretched world's pixels (see ``stretch_world``)."""
    ov = overrides if overrides is not None else Overrides.load()
    if interiors == "stretch":
        world, interiors = stretch_world(world, model, ov), "inplace"
    plan = plan_interiors(world.rom, world.headers, world.layout, model, overrides=ov) if interiors != "inset" else None
    img = render_state(world.base, world.layout, tracks, world.book, time.monotonic() if now is None else now, model,
                       world.headers, layers, crop=crop, scale=scale, interiors=interiors, plan=plan)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(path)
    return img.shape[1], img.shape[0]
