"""Pure helpers the window uses: compose the whole space into one image, summarise agents."""
from __future__ import annotations

import numpy as np

from pokeagent.mapview import edges, overlay, playback
from pokeagent.mapview.best import best_index


def compose_base(snap) -> np.ndarray | None:
    """The whole space as one RGB image: white background, each area's image at its offset,
    plus the preset's coloured edge lines drawn once in the gap between stacked areas."""
    w, h = snap.layout.space_w, snap.layout.space_h
    if not snap.areas or w <= 0 or h <= 0:
        return None
    img = np.full((h, w, 3), 255, np.uint8)
    for a in snap.areas:
        off, src = snap.layout.offsets.get(a.name), snap.images.get(a.name)
        if off is not None and src is not None:
            img[off[1]:off[1] + src.shape[0], off[0]:off[0] + src.shape[1]] = src[..., :3]
    preset = getattr(snap, "preset", None)
    if preset is not None and preset.area_gap_px and preset.edge_palette:
        rows = edges.rects(snap.areas, snap.layout)
        edges.draw_edges(img, rows, edges.edge_colours(rows, preset.edge_palette))
    return img


def agent_rows(tb: playback.Tables) -> list[tuple[str, int, int, str]]:
    """One summary row per distinct agent: (agent, palette slot, ghost count, furthest reached)."""
    by: dict[str, list] = {}
    for g in tb.ghosts:
        by.setdefault(g.agent, []).append(g)
    rows = []
    for agent in sorted(by):
        gs, b = by[agent], best_index(by[agent], tb.area_names)
        far = "-"
        if b is not None:
            r = int(gs[b].area_idx[-1])
            far = f"{tb.area_names[r] if 0 <= r < len(tb.area_names) else '?'} x{int(gs[b].xs[-1])}"
        rows.append((agent, overlay.color_index(agent, len(overlay.PALETTE)), len(gs), far))
    return rows
