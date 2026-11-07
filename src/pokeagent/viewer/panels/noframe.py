"""The hint a tile shows when an agent has a snapshot but no frame (pure; no UI toolkit)."""
from __future__ import annotations

import textwrap

import numpy as np

from pokeagent.viewer.panels import DIM, Line, plain
from pokeagent.viewer.panels.textimg import lines_texture

NO_FRAME_HINT = "no frame - swarm started with --no-share-frames"


def hint_lines(cols: int = 18) -> list[Line]:
    return [plain(t, DIM) for t in textwrap.wrap(NO_FRAME_HINT, max(8, cols), break_on_hyphens=False)]


def hint_texture(width: int, height: int) -> tuple[np.ndarray, int, int]:
    """RGBA floats + (tex_w, tex_h) for the render slot of ``width`` x ``height`` px."""
    return lines_texture(hint_lines(max(8, width // 8)), width, height)
