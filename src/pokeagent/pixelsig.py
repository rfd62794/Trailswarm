"""Pixel-level signature matching as a redundant check under tile decode.

Captures compact ink signatures (thresholded text ink, downsampled) of fixed
screen regions and matches live frames against stored references. Used for
SAVING/YES-NO dialogs where tile-decode gaps let actions slip through.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.game.pokemon_red import RED

REFS = Path(__file__).with_name('pixelrefs.json')
SCREEN_W, SCREEN_H = RED.screen
# region: (x0, y0, x1, y1) in the game's frame
REGIONS = {'dialog_box': (8, 96, 152, 140), 'yesno_box': (96, 32, 156, 84)}


def _ink(rgb: bytes, box, width: int = SCREEN_W, stride: int = 4):
    """Binary ink mask of a region at 2x2 downsample -> hex signature (flat RGBA bytes)."""
    x0, y0, x1, y1 = box
    if len(rgb) == width * SCREEN_H * 3:
        stride = 3
    bits = []
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            i = (y * width + x) * stride
            bits.append(1 if rgb[i] + rgb[i + 1] + rgb[i + 2] < 150 else 0)  # darkest DMG shade only
    h = 0
    for bit in bits:
        h = h << 1 | bit
    return hex(h)


def sign(rgb) -> dict:
    return {name: _ink(rgb, box) for name, box in REGIONS.items()}


def _dist(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count('1')


def match(rgb, name: str, max_dist: int = 40) -> bool:
    try:
        refs = json.loads(REFS.read_text())
        return _dist(_ink(rgb, REGIONS[name]), refs[name]) <= max_dist
    except Exception:
        return False
