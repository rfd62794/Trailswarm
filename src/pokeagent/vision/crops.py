"""Cut labelled boxes out of a rendered frame, content-hash them, and halve frames to thumbs."""
from __future__ import annotations

import hashlib

import numpy as np

FRAME_W, FRAME_H = 160, 144


def crop(frame: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray | None:
    """An (h, w, 3) uint8 copy of the box, or None when it is not fully on screen."""
    if x < 0 or y < 0 or x + w > frame.shape[1] or y + h > frame.shape[0]:
        return None
    return frame[y:y + h, x:x + w].copy()


def content_id(arr: np.ndarray) -> str:
    """sha1 hex of (width, height, raw bytes); unique per distinct crop."""
    return hashlib.sha1(bytes([arr.shape[1], arr.shape[0]]) + arr.tobytes()).hexdigest()


def thumb(frame: np.ndarray) -> np.ndarray:
    """An (72, 80) uint8 greyscale of the 144x160 frame: mean of 2x2 luminance blocks, integer math."""
    lum = frame.astype(np.uint16).sum(axis=2) // 3
    return (lum.reshape(FRAME_H // 2, 2, FRAME_W // 2, 2).sum(axis=(1, 3)) // 4).astype(np.uint8)
