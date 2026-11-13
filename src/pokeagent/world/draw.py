"""Compose a world frame as an image (pure numpy/Pillow): learning layers, trails, ROM objects and every agent as the game's
own player sprite. Used by the PNG export and the headless checks; the viewer draws the same things through Dear PyGui.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from pokeagent.atlas import inplace, inplace_render, sprites
from pokeagent.atlas.overlay import LAYERS, overlay
from pokeagent.atlas.rom_maps import MapHeader
from pokeagent.atlas.world import CELL, WorldLayout
from pokeagent.world import anim, layers as layerdata, pill
from pokeagent.world.palette import agent_colour  # noqa: F401  (re-exported: one palette for every surface)
from pokeagent.world.model import Track

LEARN_LAYERS = tuple(l for l in LAYERS if l not in ("trails", "agents"))


class SpriteBook:
    """Decoded sprite sheets + tinted RGBA frames, cached (sheet decode is the only ROM access)."""

    def __init__(self, rom: bytes) -> None:
        self.rom = rom
        self._sheets: dict[int, np.ndarray] = {}
        self._rgba: dict[tuple, Image.Image] = {}

    def frames(self, sprite_id: int) -> np.ndarray:
        if sprite_id not in self._sheets:
            self._sheets[sprite_id] = sprites.sheet(self.rom, sprite_id)
        return self._sheets[sprite_id]

    def image(self, sprite_id: int, facing: str, phase: int = 0, colour: tuple[int, int, int] | None = None) -> Image.Image:
        key = (sprite_id, facing, phase, colour)
        if key not in self._rgba:
            self._rgba[key] = Image.fromarray(sprites.sprite_rgba(sprites.pick_frame(self.frames(sprite_id), facing, phase), colour))
        return self._rgba[key]


def draw_trails(dr: ImageDraw.ImageDraw, layout: WorldLayout, tracks: list[Track], ids: list[str], n: int = 120) -> None:
    for t in tracks:
        r, g, b = agent_colour(t.id, ids)
        pts = anim.trail_points(t, layout, n)
        for j, (cx, cy) in enumerate(pts):
            age = (j + 1) / len(pts)
            rad = 3 + int(3 * age)
            dr.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(r, g, b, int(20 + 220 * age * age)))


def draw_objects(im: Image.Image, layout: WorldLayout, headers: dict[int, MapHeader], book: SpriteBook, maps: set[int]) -> None:
    """Static NPCs, trainers and item balls of ``maps`` from the ROM's object data, standing facing down."""
    for m in sorted(maps):
        hd = headers.get(m)
        if hd is None or m not in layout.places or m in layout.pins:
            continue
        for o in hd.objects:
            try:
                spr = book.image(o["sprite"], "DOWN")
            except (ValueError, IndexError):
                continue
            px, py = layout.to_world(m, o["x"], o["y"])
            im.alpha_composite(spr, (px - 1, py - 1))


def draw_agent(im: Image.Image, dr: ImageDraw.ImageDraw, layout: WorldLayout, t: Track, ids: list[str], book: SpriteBook,
               now: float) -> tuple[float, float] | None:
    pos = anim.place(t, layout, now)
    if pos is None:
        return None
    x, y, phase = pos
    col = agent_colour(t.id, ids)
    im.alpha_composite(book.image(sprites.PLAYER, t.facing, phase, col), (int(x) - 1, int(y) - 1))
    cx, cy = int(x) + CELL // 2, int(y)
    dr.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], outline=(*col, 255), width=2)         # ring in the agent's colour
    label = t.id[-8:]
    pl = pill.pill(cx, cy - 11, dr.textlength(label), 11)
    dr.rounded_rectangle([pl.x0, pl.y0, pl.x1, pl.y1], radius=pl.radius, fill=pill.PILL_FILL)
    dr.text((pl.text_x, pl.text_y - 1), label, fill=pill.PILL_TEXT)
    tag = inplace.badge(layout, t.map)
    if tag:
        dr.text((cx - 4, cy + 18), tag, fill=(255, 235, 150, 255), stroke_width=1, stroke_fill=(0, 0, 0, 255))
    if t.battle and t.battle.ended_at is None:                       # battle badge: crossed swords + enemy species
        for a, b in (((cx - 7, cy - 22), (cx + 7, cy - 8)), ((cx + 7, cy - 22), (cx - 7, cy - 8))):
            dr.line([a, b], fill=(255, 255, 255, 255), width=4)
            dr.line([a, b], fill=(220, 30, 30, 255), width=2)
        dr.text((cx - 18, cy - 36), t.battle.species or "?", fill=(255, 220, 80, 255), stroke_width=1, stroke_fill=(0, 0, 0, 255))
    return x + CELL / 2, y + CELL / 2


def render_state(base: np.ndarray, layout: WorldLayout, tracks: list[Track], book: SpriteBook, now: float,
                 model: dict | None = None, headers: dict[int, MapHeader] | None = None,
                 layers: tuple[str, ...] = (), objects: bool = True, trails: bool = True,
                 crop: tuple[int, int, int, int] | None = None, scale: float = 1.0, interiors: str = "inset",
                 plan: inplace.Plan | None = None) -> np.ndarray:
    """The world with the chosen learning ``layers`` (default none), trails, ROM objects of the agents' maps and every agent.

    ``crop`` (x0, y0, x1, y1 in world px) and ``scale`` keep exports of a region small; drawing happens at full size first."""
    ids = [t.id for t in tracks]
    img = overlay(base, layout, model or {}, headers or {}, [], tuple(layers)) if layers else base
    vl, shown, imgs = None, set(), inplace_render.InteriorImages(book.rom, headers or {})
    if plan is not None and interiors != "inset":
        shown = inplace.shown_set(interiors, plan.anchors, scale, inside=tuple(t.map for t in tracks if t.placed),
                                  hidden=plan.hidden)
        vl = inplace.view_layout(layout, plan.anchors, plan.xf(interiors), shown)
    if crop:
        x0, y0, x1, y1 = (v // CELL * CELL for v in crop)
        shift = (-x0, -y0)
        img = inplace_render.compose(img, vl, plan.anchors, shown, imgs, None, (x0, y0, x1, y1)) if vl else img[y0:y1, x0:x1]
    else:
        shift = (0, 0)
        img = inplace_render.compose(img, vl, plan.anchors, shown, imgs) if vl else img
    layout = vl or layout
    im = Image.fromarray(np.ascontiguousarray(img)).convert("RGBA")
    if shift != (0, 0):                                      # draw in world coordinates on a translated canvas
        layout = _shifted(layout, *shift)
    dr = ImageDraw.Draw(im, "RGBA")
    if trails:
        draw_trails(dr, layout, tracks, ids)
    if objects and headers:
        draw_objects(im, layout, headers, book, {t.map for t in tracks if t.placed})
    for t in tracks:
        draw_agent(im, dr, layout, t, ids, book, now)
    if layers:                                                 # an empty model draws nothing: say so instead of a silent no-op
        layerdata.draw_legend(dr, layerdata.legend_lines(tuple(layers), model))
    out = im.convert("RGB")
    if scale != 1.0:
        out = out.resize((max(1, int(out.width * scale)), max(1, int(out.height * scale))), Image.LANCZOS)
    return np.asarray(out)


def _shifted(layout: WorldLayout, dx: int, dy: int) -> WorldLayout:
    """A layout whose to_world is translated by (dx, dy) px (for crops); cells stay whole when dx, dy are multiples of CELL."""
    from dataclasses import replace
    cx, cy = dx // CELL, dy // CELL
    places = {m: replace(p, x=p.x + cx, y=p.y + cy) for m, p in layout.places.items()}
    warp = replace(layout.warp, dx=layout.warp.dx + cx, dy=layout.warp.dy + cy) if layout.warp else None
    return replace(layout, places=places, warp=warp, pins={m: (x + cx, y + cy) for m, (x, y) in layout.pins.items()},
                   xf={m: t._replace(ox=t.ox + cx, oy=t.oy + cy) for m, t in layout.xf.items()})


def blend(img: np.ndarray, rgba: np.ndarray, x: int, y: int) -> None:
    """Alpha-composite an (h, w, 4) uint8 sprite onto an RGB array in place (clipped at the edges)."""
    h, w = rgba.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(img.shape[1], x + w), min(img.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    s = rgba[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.uint16)
    dst = img[y0:y1, x0:x1]
    dst[:] = ((s[..., :3] * a + dst * (255 - a)) // 255).astype(np.uint8)


def compose_layers(base: np.ndarray, layout: WorldLayout, model: dict, headers: dict[int, MapHeader], layers: tuple[str, ...],
                   book: SpriteBook | None = None, object_maps: set[int] | None = None) -> np.ndarray:
    """``base`` + learning layers (+ ROM objects of ``object_maps`` when ``book`` is given); trails and agents are drawn live."""
    img = overlay(base, layout, model, headers, [], tuple(layers)) if layers else base.copy()
    if book is not None:
        for m in sorted(object_maps or ()):
            hd = headers.get(m)
            for o in (hd.objects if hd else []):
                try:
                    px, py = layout.to_world(m, o["x"], o["y"])
                    blend(img, np.asarray(book.image(o["sprite"], "DOWN")), px - 1, py - 1)
                except (ValueError, IndexError, KeyError):
                    continue
    return img
