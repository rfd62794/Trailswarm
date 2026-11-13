"""World loading (ROM -> layout + stitched image, cached on disk) and PNG export. Headless: writes files only."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from pokeagent.atlas.compact import compact_image, compact_layout
from pokeagent.atlas.fit import walk_cells
from pokeagent.atlas.inplace import plan_interiors, usable_anchors
from pokeagent.atlas.overrides import Overrides
from pokeagent.atlas.stretch import stretch_image, stretch_layout, stretch_warp
from pokeagent.atlas.rom_maps import MapHeader, all_headers, load
from pokeagent.atlas.world import WorldLayout, build_layout
from pokeagent.atlas.world_render import render_world
from pokeagent.game.pokemon_red import RED
from pokeagent.world.draw import SpriteBook, render_state
from pokeagent.world.palette import gb_tint
from pokeagent.world.model import Track

Image.MAX_IMAGE_PIXELS = None
CACHE = Path("runs") / "atlas" / "world_v2.png"   # v2: tidy interior labels (the cache holds the untinted render)

# str signature default, forward slashes on every OS; RED-pinned: fixed at def time, POKEAGENT_GAME must not change it
_DEFAULT_ROM = str(RED.default_rom).replace("\\", "/")


@dataclass
class World:
    rom: bytes
    headers: dict[int, MapHeader]
    layout: WorldLayout
    base: np.ndarray
    book: SpriteBook
    compact: bool = False                  # inset grid holds only the interiors that could not be anchored
    source: "World | None" = None          # the full-grid world this one was derived from (to go back to inset mode)


def load_world(rom_path: str | Path = _DEFAULT_ROM, cache: Path | None = CACHE, base: str | Path | None = None,
               tint: bool = True) -> World:
    """Decode the ROM and stitch Kanto. ``base`` / ``cache`` name a previously rendered world.png (skips the slow render);
    a fresh render is written to ``cache`` (runs/ is git-ignored: never commit it, it is ROM-derived).
    ``tint`` (default on) maps the map onto the four Game Boy greens; the cache always holds the untinted render."""
    rom = load(rom_path)
    headers = all_headers(rom)
    layout = build_layout(headers)
    src = Path(base) if base else cache
    if src is not None and src.exists():
        img = np.asarray(Image.open(src).convert("RGB"))
        if (img.shape[1], img.shape[0]) == layout.size_px:
            return World(rom, headers, layout, gb_tint(img) if tint else img, SpriteBook(rom))
    img = render_world(rom, headers, layout, False)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(img).save(cache)
    return World(rom, headers, layout, gb_tint(img) if tint else img, SpriteBook(rom))


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


def load_for_view(rom_path: str | Path = _DEFAULT_ROM, cache: Path | None = CACHE, base: str | Path | None = None,
                  tint: bool = True) -> World:
    """What the viewer opens with: the full inset world, unless the saved Interiors choice is an in-place mode (then compact)."""
    from pokeagent.atlas.inplace import DEFAULT_MODE
    w, ov = load_world(rom_path, cache, base, tint), Overrides.load()
    return w if (ov.mode or DEFAULT_MODE) == "inset" else compact_world(w, None, ov)


def full_world(world: World) -> World:
    """The world with the complete inset grid (what inset mode shows)."""
    return world.source or world


def compact_world(world: World, model: dict | None = None, overrides: Overrides | None = None) -> World:
    """The world for the in-place modes: the grid below Kanto holds only the interiors that could not be anchored (the
    anchored ones are drawn in place from the ROM) and the canvas shrinks to fit. Already-compact worlds come back as is."""
    if world.compact:
        return world
    lay = world.layout
    anchors = usable_anchors(world.headers, lay, model, overrides)
    keep = {m for m, p in lay.places.items() if p.interior} - set(anchors)
    lay2 = compact_layout(lay, keep)
    return World(world.rom, world.headers, lay2, compact_image(world.base, lay, lay2, keep), world.book, True, world.source or world)


def stretch_world(world: World, model: dict | None = None, overrides: Overrides | None = None,
                  walk_cache: dict | None = None) -> World:
    """The compact world with the outdoor map locally stretched so every in-place interior fits its building at full size."""
    ov = overrides or Overrides()
    world = compact_world(world, model, ov)
    cache = walk_cache if walk_cache is not None else {}
    lay, hd = world.layout, world.headers

    def walk(m: int):
        if m not in cache:
            cache[m] = walk_cells(world.rom, hd[m]) if m in hd else None
        return cache[m]

    anchors = usable_anchors(hd, lay, model, ov)
    warp = stretch_warp(anchors, lay, walk, ov.bands)
    return World(world.rom, hd, stretch_layout(lay, warp), stretch_image(world.base, lay, warp), world.book, True, world.source)


def export_png(path: str | Path, world: World, tracks: list[Track], model: dict | None = None, layers: tuple[str, ...] = (),
               crop: tuple[int, int, int, int] | None = None, scale: float = 1.0, now: float | None = None,
               interiors: str = "inset", overrides: Overrides | None = None) -> tuple[int, int]:
    """Render the world state to a PNG. ``interiors``: inset | inplace (fit) | inplace_full | auto | stretch (stretched world,
    full-size in place). With ``stretch`` the ``crop`` is in the stretched world's pixels (see ``stretch_world``)."""
    ov = overrides if overrides is not None else Overrides.load()
    if interiors != "inset":
        world = compact_world(world, model, ov)               # the grid keeps only what could not be placed
    if interiors == "stretch":
        world, interiors = stretch_world(world, model, ov), "inplace"
    plan = plan_interiors(world.rom, world.headers, world.layout, model, overrides=ov) if interiors != "inset" else None
    img = render_state(world.base, world.layout, tracks, world.book, time.monotonic() if now is None else now, model,
                       world.headers, layers, crop=crop, scale=scale, interiors=interiors, plan=plan)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(path)
    return img.shape[1], img.shape[0]
