"""Small PIL helpers shared by the vision viewer panels (no torch, no dataset knowledge)."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

GREEN, RED, GREY = (0, 200, 0), (230, 30, 30), (150, 150, 150)
BG = (24, 24, 28)
COARSE_RGB = {"enemy": (255, 120, 0), "npc": (255, 0, 220), "item": (255, 230, 0),
              "player": (0, 220, 255), "terrain": (40, 90, 255), "other": (255, 255, 255)}


def up(arr: np.ndarray, k: int) -> Image.Image:
    """``arr`` (h,w[,3] uint8) as an RGB image scaled k times, nearest neighbour."""
    im = Image.fromarray(np.ascontiguousarray(arr)).convert("RGB")
    return im.resize((im.width * k, im.height * k), Image.NEAREST)


def banner(width: int, text: str, h: int = 16) -> Image.Image:
    """A dark strip with one line of text."""
    im = Image.new("RGB", (width, h), BG)
    ImageDraw.Draw(im).text((3, 2), text, fill=(235, 235, 235))
    return im


def cell(img: Image.Image, size: int, border=None) -> Image.Image:
    """``img`` centred on a size x size dark square, with an optional 2px border."""
    c = Image.new("RGB", (size, size), BG)
    c.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    if border:
        ImageDraw.Draw(c).rectangle([0, 0, size - 1, size - 1], outline=border, width=2)
    return c


def hstrip(imgs, pad: int = 4) -> Image.Image:
    """Images side by side, top-aligned, on the dark background."""
    imgs = list(imgs)
    if not imgs:
        return Image.new("RGB", (1, 1), BG)
    out = Image.new("RGB", (sum(i.width for i in imgs) + pad * (len(imgs) - 1),
                            max(i.height for i in imgs)), BG)
    x = 0
    for i in imgs:
        out.paste(i, (x, 0))
        x += i.width + pad
    return out


def vstack(imgs, pad: int = 4) -> Image.Image:
    """Images top to bottom, left-aligned, on the dark background."""
    imgs = list(imgs)
    if not imgs:
        return Image.new("RGB", (1, 1), BG)
    out = Image.new("RGB", (max(i.width for i in imgs),
                            sum(i.height for i in imgs) + pad * (len(imgs) - 1)), BG)
    y = 0
    for i in imgs:
        out.paste(i, (0, y))
        y += i.height + pad
    return out


def to_rgba_floats(img: Image.Image) -> tuple[int, int, np.ndarray]:
    """(width, height, flat float32 RGBA in 0..1): the data a Dear PyGui static texture takes."""
    a = np.asarray(img.convert("RGBA"), dtype=np.float32) / 255.0
    return img.width, img.height, a.ravel()
