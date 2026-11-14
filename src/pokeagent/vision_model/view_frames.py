"""Panel 1: lay recorded crops back onto a frame thumbnail and outline them.

Thumbnails are 80x72 greyscale halves of the 160x144 frame; a crop is found on one by
matching its own halved luminance (the same integer maths as ``crops.thumb``).
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image, ImageDraw

from pokeagent.vision_model.view_draw import COARSE_RGB, GREEN, GREY, RED, banner, hstrip, up, vstack

STATUS_RGB = {"ok": GREEN, "wrong": RED, "unseen": GREY}


def lum_half(crop: np.ndarray) -> np.ndarray:
    """Greyscale half-size of an (h,w,3) crop, as ``crops.thumb`` computes it."""
    h, w = crop.shape[0] // 2, crop.shape[1] // 2
    lum = crop[:h * 2, :w * 2].astype(np.uint16).sum(axis=2) // 3
    return (lum.reshape(h, 2, w, 2).sum(axis=(1, 3)) // 4).astype(np.uint8)


def find_boxes(thumb: np.ndarray, crops: dict) -> list:
    """[(x, y, w, h, row)] in frame pixels. ``crops`` maps row -> (kind, crop). Tiles are
    matched exactly on the 8px grid, sprites by best sliding window under a small error."""
    tiles, boxes = {}, []
    for r, (kind, c) in crops.items():
        if kind == "tile":
            tiles.setdefault(lum_half(c).tobytes(), r)
    for gy in range(thumb.shape[0] // 4):
        for gx in range(thumb.shape[1] // 4):
            r = tiles.get(thumb[gy * 4:gy * 4 + 4, gx * 4:gx * 4 + 4].tobytes())
            if r is not None:
                boxes.append((gx * 8, gy * 8, 8, 8, r))
    for r, (kind, c) in crops.items():
        small = lum_half(c)
        if kind != "sprite" or small.size == 0 or small.std() < 5:
            continue
        if small.shape[0] > thumb.shape[0] or small.shape[1] > thumb.shape[1]:
            continue
        win = sliding_window_view(thumb, small.shape).astype(np.int16)
        err = np.abs(win - small).mean(axis=(2, 3))
        y, x = np.unravel_index(int(err.argmin()), err.shape)
        if err[y, x] <= 2.0:
            boxes.append((int(x) * 2, int(y) * 2, c.shape[1], c.shape[0], r))
    return boxes


def overlay(thumb: np.ndarray, boxes, colour_of, fill: bool, k: int = 4) -> Image.Image:
    """The thumbnail upscaled k times with each box outlined (or filled, 45% blend)."""
    base = up(thumb, k)
    layer = base.copy()
    d = ImageDraw.Draw(layer)
    for x, y, w, h, r in boxes:
        box = [x // 2 * k, y // 2 * k, (x + w) // 2 * k - 1, (y + h) // 2 * k - 1]
        d.rectangle(box, fill=colour_of(r) if fill else None,
                    outline=None if fill else colour_of(r), width=2 if w > 8 else 1)
    return Image.blend(base, layer, 0.45) if fill else layer


def pick_frame(thumbs: list, crops: dict, load):
    """(thumb array, boxes) of the thumbnail in ``thumbs`` covering the most crops, or None."""
    best = None
    for t in thumbs:
        arr = load(t["id"])
        boxes = find_boxes(arr, crops)
        if best is None or len(boxes) > len(best[1]):
            best = (arr, boxes)
    return best


def frame_images(thumb, boxes, status, coarse_name) -> tuple[Image.Image, Image.Image]:
    """(outlines by right/wrong/unseen, fill by coarse prediction) for one frame."""
    return (overlay(thumb, boxes, lambda r: STATUS_RGB[status(r)], False),
            overlay(thumb, boxes, lambda r: COARSE_RGB[coarse_name(r)], True))


def mosaic(title: str, crops: list, colours: list, k: int = 3, cols: int = 24) -> Image.Image:
    """Fallback when no frame can be rebuilt: a grid of crops, each with its status border."""
    cells = []
    for c, col in zip(crops, colours):
        im = up(c, k)
        ImageDraw.Draw(im).rectangle([0, 0, im.width - 1, im.height - 1], outline=col)
        cells.append(im)
    rows = [hstrip(cells[i:i + cols], 2) for i in range(0, len(cells), cols)]
    return vstack([banner(300, title)] + rows, 2)
