"""Learning-layer data checks and the 'no learning data' legend (pure numpy/Pillow, no ROM)."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import ImageDraw

# the model key(s) each layer reads (atlas.overlay)
LAYER_KEYS = {"heat": ("visited",), "encounters": ("encounters",), "walls": ("blocked",), "ledges": ("jumps",),
              "items": ("npcs",), "warps": ("warps",), "disagree": ("warps",)}


def has_data(model: dict | None, layers: tuple[str, ...]) -> bool:
    """True when the model holds something for at least one of the requested layers."""
    keys = {k for l in layers for k in LAYER_KEYS.get(l, ())}
    return any(md.get(k) for md in ((model or {}).get("maps") or {}).values() if isinstance(md, dict) for k in keys)


def load_model(path: str | Path) -> dict:
    """A saved maps.json (``{"maps": {...}}``); {} when missing or unreadable."""
    try:
        out = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def legend_lines(layers: tuple[str, ...], model: dict | None) -> list[str]:
    """Empty when the layers have data; otherwise the banner explaining why the image shows no overlay."""
    if not layers or has_data(model, layers):
        return []
    return ["no learning data", f"layers: {', '.join(layers)}", "no agent has reported it and no maps.json was loaded (--model)"]


def draw_legend(dr: ImageDraw.ImageDraw, lines: list[str], xy: tuple[int, int] = (12, 12)) -> None:
    if not lines:
        return
    w, h = max(len(s) for s in lines) * 6 + 12, len(lines) * 13 + 8
    dr.rounded_rectangle([xy[0], xy[1], xy[0] + w, xy[1] + h], radius=6, fill=(14, 24, 14, 225))
    for i, s in enumerate(lines):
        dr.text((xy[0] + 6, xy[1] + 4 + 13 * i), s, fill=(255, 220, 120, 255) if i == 0 else (225, 235, 200, 255))
