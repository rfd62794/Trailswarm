"""World palette (pure): the four Game Boy greens, the fixed per-agent colours and the map tint."""
from __future__ import annotations

import re
import zlib

import numpy as np

GB_GREENS = ((0x0F, 0x38, 0x0F), (0x30, 0x62, 0x30), (0x8B, 0xAC, 0x0F), (0x9B, 0xBC, 0x0F))
VOID = GB_GREENS[0]
# one palette for every agent surface (ring, trail, roster swatch, card header); distinct on all four greens
AGENT_COLOURS = ((230, 25, 75), (255, 255, 255), (0, 130, 200), (245, 130, 48), (145, 30, 180),
                 (70, 240, 240), (240, 50, 230), (250, 230, 60), (250, 190, 212), (200, 160, 255))


def agent_colour(agent_id: str, ids=None) -> tuple[int, int, int]:
    """A fixed colour per agent, whoever else is running: the trailing number picks the slot (agent-3 -> slot 3),
    any other id hashes to one. ``ids`` is accepted for the old call sites and ignored."""
    m = re.search(r"(\d+)\D*$", agent_id)
    n = int(m.group(1)) - 1 if m else zlib.crc32(agent_id.encode())
    return AGENT_COLOURS[n % len(AGENT_COLOURS)]


def hex_colour(c: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % tuple(c)


def gb_tint(img: np.ndarray) -> np.ndarray:
    """Map an RGB image onto the four Game Boy greens by luminance (darkest -> #0f380f, lightest -> #9bbc0f)."""
    lum = img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114
    idx = np.clip((lum / 64.0).astype(np.int32), 0, 3)
    return np.asarray(GB_GREENS, dtype=np.uint8)[idx]
