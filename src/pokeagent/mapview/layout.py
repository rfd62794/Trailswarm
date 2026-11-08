"""Lay every area out in one shared pixel space: index order, left to right, wrapping into rows.

Pure and deterministic: the same areas give the same offsets, and a new area appends after the
existing ones without moving them (unless a row wraps differently because an earlier area grew).
Each row reserves a ``label_h`` strip above its images for the area name.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.mapview.areas import Area

LABEL_H = 20


@dataclass(frozen=True)
class Layout:
    offsets: dict[str, tuple[int, int]]
    space_w: int
    space_h: int


def place(areas: list[Area], max_row_width: int = 4096, gap: int = 32, label_h: int = LABEL_H) -> Layout:
    """Row height is the tallest area plus ``label_h`` plus ``gap``; an area wider than
    ``max_row_width`` gets a row to itself. Image offsets sit ``label_h`` below the row top."""
    offsets: dict[str, tuple[int, int]] = {}
    y = row_h = used_w = space_w = 0
    for a in areas:
        if used_w > 0 and used_w + gap + a.width > max_row_width:
            y += label_h + row_h + gap
            row_h = used_w = 0
        x = used_w if used_w == 0 else used_w + gap
        offsets[a.name] = (x, y + label_h)
        used_w = x + a.width
        row_h = max(row_h, a.height)
        space_w = max(space_w, used_w)
    space_h = y + label_h + row_h if areas else 0
    return Layout(offsets, space_w, space_h)


def locate(layout: Layout, area: str, x: float, y: float) -> tuple[float, float] | None:
    """Space coordinates of a point inside ``area``; None for an area the layout does not know
    (a ghost may refer to an area whose image has not been captured yet)."""
    off = layout.offsets.get(area)
    if off is None:
        return None
    return off[0] + x, off[1] + y
