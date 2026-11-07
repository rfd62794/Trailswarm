"""Draw the agents' beliefs (a ``maps.json`` model) and live positions over the world image. Pure numpy/Pillow.

Layers (all optional): heat (visit counts), encounters, walls (learned blocked edges), ledges (learned jumps), items (ball
sprites the agent saw; hollow = ROM item object never seen), warps (learned warps that match the ROM), disagree (RED
square = learned warp whose target cell is not a ROM warp; HOLLOW square = ROM warp never learned), trails, agents.
Learned warp keys are ``"x,y,DIR": [dest_map, dx, dy]`` where (x, y) is the cell stood on and DIR the press, so the warp
tile is the neighbouring cell; a target outside the map is a connection (map edge), not a warp.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from pokeagent.atlas.rom_maps import MapHeader
from pokeagent.atlas.world import CELL, WorldLayout

LAYERS = ("heat", "encounters", "walls", "ledges", "items", "warps", "disagree", "trails", "agents")
PALETTE = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180), (70, 240, 240),
           (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128)]
_VEC = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
BALL_PIC = 61


@dataclass
class Agent:
    id: str
    map: int
    x: int
    y: int
    trail: list[tuple[int, int, int]] = field(default_factory=list)     # oldest first: (map, x, y)


def _xy(key: str) -> tuple[int, int]:
    a = key.split(",")
    return int(a[0]), int(a[1])


def _key3(key: str) -> tuple[int, int, str]:
    a = key.split(",")
    return int(a[0]), int(a[1]), a[2]


def _cell(layout: WorldLayout, m: int, x: int, y: int) -> tuple[int, int] | None:
    p = layout.places.get(m)
    if p is None or not (0 <= x < p.w and 0 <= y < p.h):
        return None
    return layout.to_world(m, x, y)


def _heat(dr: ImageDraw.ImageDraw, layout: WorldLayout, m: int, md: dict) -> None:
    visited = md.get("visited") or {}
    top = math.log1p(max(visited.values(), default=1))
    for k, n in visited.items():
        x, y = _xy(k)
        c = _cell(layout, m, x, y)
        if c:
            t = math.log1p(n) / top if top else 0.0
            dr.rectangle([c[0], c[1], c[0] + CELL - 1, c[1] + CELL - 1],
                         fill=(255, int(220 * (1 - t)), 0, int(70 + 110 * t)))


def _encounters(dr: ImageDraw.ImageDraw, layout: WorldLayout, m: int, md: dict) -> None:
    enc = md.get("encounters") or {}
    top = max(enc.values(), default=1)
    for k, n in enc.items():
        x, y = _xy(k)
        c = _cell(layout, m, x, y)
        if c:
            r = 2 + int(4 * math.sqrt(n / top))
            cx, cy = c[0] + CELL // 2, c[1] + CELL // 2
            dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(40, 200, 60, 190))


def _walls(dr: ImageDraw.ImageDraw, layout: WorldLayout, m: int, md: dict) -> None:
    for k in md.get("blocked") or []:
        x, y, d = _key3(k)
        c = _cell(layout, m, x, y)
        if not c or d not in _VEC:
            continue
        x0, y0, x1, y1 = c[0], c[1], c[0] + CELL, c[1] + CELL
        edge = {"UP": (x0, y0, x1, y0), "DOWN": (x0, y1, x1, y1), "LEFT": (x0, y0, x0, y1), "RIGHT": (x1, y0, x1, y1)}[d]
        dr.line(edge, fill=(200, 0, 200, 255), width=2)


def _ledges(dr: ImageDraw.ImageDraw, layout: WorldLayout, m: int, md: dict) -> None:
    for k, land in (md.get("jumps") or {}).items():
        x, y, _ = _key3(k)
        a, b = _cell(layout, m, x, y), _cell(layout, m, land[0], land[1])
        if a and b:
            h = CELL // 2
            dr.line([a[0] + h, a[1] + h, b[0] + h, b[1] + h], fill=(0, 220, 255, 255), width=2)
            dr.ellipse([b[0] + h - 3, b[1] + h - 3, b[0] + h + 3, b[1] + h + 3], fill=(0, 220, 255, 255))


def _diamond(dr: ImageDraw.ImageDraw, c: tuple[int, int], fill=None, outline=None) -> None:
    h = CELL // 2
    cx, cy = c[0] + h, c[1] + h
    dr.polygon([(cx, cy - 6), (cx + 6, cy), (cx, cy + 6), (cx - 6, cy)], fill=fill, outline=outline)


def _items(dr: ImageDraw.ImageDraw, layout: WorldLayout, m: int, md: dict, hd: MapHeader | None) -> None:
    seen: set[tuple[int, int]] = set()
    for npc in (md.get("npcs") or {}).values():
        if npc.get("pic") == BALL_PIC:
            seen.update(_xy(k) for k in (npc.get("positions") or {}))
    for x, y in seen:
        c = _cell(layout, m, x, y)
        if c:
            _diamond(dr, c, fill=(255, 215, 0, 255), outline=(0, 0, 0, 255))
    for o in (hd.objects if hd else []):
        if o["kind"] == "item" and (o["x"], o["y"]) not in seen:
            c = _cell(layout, m, o["x"], o["y"])
            if c:
                _diamond(dr, c, outline=(255, 215, 0, 255))


def _square(dr: ImageDraw.ImageDraw, c: tuple[int, int], fill=None, outline=None) -> None:
    dr.rectangle([c[0] + 2, c[1] + 2, c[0] + CELL - 3, c[1] + CELL - 3], fill=fill, outline=outline, width=2)


def warp_report(md: dict, hd: MapHeader | None, w: int, h: int) -> dict[str, list[tuple[int, int]]]:
    """Classify one map's warps: ``agree`` (learned and in ROM), ``false`` (learned, not in ROM), ``unlearned`` (ROM only)."""
    rom = {(x, y) for x, y, _dw, _dm in (hd.warps if hd else [])}
    agree, false, hit = [], [], set()
    for k in md.get("warps") or {}:
        x, y, d = _key3(k)
        dx, dy = _VEC.get(d, (0, 0))
        tx, ty = x + dx, y + dy
        if not (0 <= tx < w and 0 <= ty < h):
            continue                                    # walked off the map edge: a connection, not a warp
        (agree if (tx, ty) in rom else false).append((tx, ty))
        hit.add((tx, ty))
    return {"agree": agree, "false": false, "unlearned": sorted(rom - hit) if hd else []}


def _warps(dr: ImageDraw.ImageDraw, layout: WorldLayout, m: int, md: dict, hd: MapHeader | None, kinds: set[str]) -> None:
    p = layout.places[m]
    rep = warp_report(md, hd, p.w, p.h)
    if "warps" in kinds:
        for x, y in rep["agree"]:
            _square(dr, layout.to_world(m, x, y), fill=(30, 90, 255, 200))
    if "disagree" in kinds:
        for x, y in rep["false"]:
            _square(dr, layout.to_world(m, x, y), fill=(255, 0, 0, 230))
        for x, y in rep["unlearned"]:
            _square(dr, layout.to_world(m, x, y), outline=(255, 255, 255, 255))


def _trails(dr: ImageDraw.ImageDraw, layout: WorldLayout, agents: list[Agent]) -> None:
    for i, a in enumerate(agents):
        r, g, b = PALETTE[i % len(PALETTE)]
        n = len(a.trail)
        for j, (m, x, y) in enumerate(a.trail):
            c = _cell(layout, m, x, y)
            if c:
                age = (j + 1) / max(n, 1)
                cx, cy, rad = c[0] + CELL // 2, c[1] + CELL // 2, 2 + int(2 * age)
                dr.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(r, g, b, int(40 + 190 * age)))


def _agents(dr: ImageDraw.ImageDraw, layout: WorldLayout, agents: list[Agent]) -> None:
    for i, a in enumerate(agents):
        c = _cell(layout, a.map, a.x, a.y)
        if not c:
            continue
        col = PALETTE[i % len(PALETTE)]
        cx, cy = c[0] + CELL // 2, c[1] + CELL // 2
        dr.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=col + (255,), outline=(255, 255, 255, 255), width=2)
        dr.text((cx + 9, cy - 6), a.id[-5:], fill=(255, 255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0, 255))


def overlay(base: np.ndarray, layout: WorldLayout, model: dict, headers: dict[int, MapHeader] | None = None,
            agents: list[Agent] | None = None, layers: tuple[str, ...] = LAYERS) -> np.ndarray:
    """A copy of ``base`` with the chosen layers drawn on it. ``model`` is a maps.json (``{"maps": {...}}``)."""
    headers, agents, want = headers or {}, agents or [], set(layers)
    im = Image.fromarray(base).convert("RGB")
    dr = ImageDraw.Draw(im, "RGBA")
    maps = {int(k): v for k, v in (model.get("maps") or {}).items() if int(k) in layout.places}
    for m, md in sorted(maps.items()):
        if "heat" in want:
            _heat(dr, layout, m, md)
        if "encounters" in want:
            _encounters(dr, layout, m, md)
    for m, md in sorted(maps.items()):
        if "walls" in want:
            _walls(dr, layout, m, md)
        if "ledges" in want:
            _ledges(dr, layout, m, md)
        if "items" in want:
            _items(dr, layout, m, md, headers.get(m))
        if want & {"warps", "disagree"}:
            _warps(dr, layout, m, md, headers.get(m), want)
    if "trails" in want:
        _trails(dr, layout, agents)
    if "agents" in want:
        _agents(dr, layout, agents)
    return np.asarray(im)
