"""The stitched world as downscaled levels cut into chunks, so GPU textures stay small (pure numpy/Pillow).

Dear PyGui textures larger than ~8192 px per side can fail and a float RGBA texture of the whole 5632x11488 world would be
~1 GB, so the viewer never uploads the whole image: it picks the level whose scale is closest to the zoom, and uploads only
the CHUNK x CHUNK tiles that intersect the view. Level ``f`` is the world shrunk by factor ``f`` (1, 2, 4, 8).
"""
from __future__ import annotations

import numpy as np
from PIL import Image

CHUNK = 1024
LEVELS = (1, 2, 4, 8)


class Pyramid:
    def __init__(self, base: np.ndarray) -> None:
        self.base = base
        self.height, self.width = base.shape[:2]
        self._levels: dict[int, np.ndarray] = {1: base}

    def level(self, f: int) -> np.ndarray:
        if f not in self._levels:
            w, h = max(1, self.width // f), max(1, self.height // f)
            self._levels[f] = np.asarray(Image.fromarray(self.base).resize((w, h), Image.BOX))
        return self._levels[f]

    @staticmethod
    def level_for_zoom(zoom: float) -> int:
        """Largest shrink factor still at least as sharp as the screen needs (zoom = screen px per world px)."""
        best = 1
        for f in LEVELS:
            if 1.0 / f >= zoom * 0.99:
                best = f
        return best

    def chunks(self, f: int, x0: float, y0: float, x1: float, y1: float) -> list[tuple[int, int]]:
        """(cx, cy) of every chunk of level ``f`` touching the world-pixel rectangle."""
        lv = self.level(f)
        lh, lw = lv.shape[:2]
        cx0, cx1 = max(0, int(x0 / f) // CHUNK), min((lw - 1) // CHUNK, int(max(x1, 0) / f) // CHUNK)
        cy0, cy1 = max(0, int(y0 / f) // CHUNK), min((lh - 1) // CHUNK, int(max(y1, 0) / f) // CHUNK)
        return [(cx, cy) for cy in range(cy0, cy1 + 1) for cx in range(cx0, cx1 + 1)]

    def chunk_rect(self, f: int, cx: int, cy: int) -> tuple[int, int, int, int]:
        """World-pixel (x0, y0, x1, y1) a chunk covers."""
        lh, lw = self.level(f).shape[:2]
        return (cx * CHUNK * f, cy * CHUNK * f, min(lw, (cx + 1) * CHUNK) * f, min(lh, (cy + 1) * CHUNK) * f)

    def chunk(self, f: int, cx: int, cy: int) -> np.ndarray:
        """(h, w, 3) uint8 pixels of one chunk."""
        return self.level(f)[cy * CHUNK:(cy + 1) * CHUNK, cx * CHUNK:(cx + 1) * CHUNK]


def to_gpu(rgb: np.ndarray) -> list[float]:
    """Flat RGBA float list in 0..1 for ``dpg.add_static_texture`` / raw textures."""
    out = np.ones(rgb.shape[:2] + (4,), dtype=np.float32)
    out[..., :3] = rgb / np.float32(255.0)
    return out.reshape(-1)
