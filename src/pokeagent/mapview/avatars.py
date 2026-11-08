"""``frame_crop`` avatars: cut the player's picture out of the live frame, tint per agent.

Every ghost of a game shares the one crop - it is the game's player picture, not a
per-agent photo - tinted by the ghost's agent colour. Crops are memory only: nothing here
writes a file, a cache directory or a fixture. Until the first good crop exists the
overlay keeps drawing its square.
"""
from __future__ import annotations

import threading

import numpy as np

KEY_TOL = 24          # per-channel distance from the background colour that keys a pixel out
MAX_KEYED = 0.90      # a crop keyed past this fraction is a bad crop, not an avatar
RING_UNIFORM = 0.90   # a box whose 1 px ring is less uniform than this holds scenery, not a lone sprite
TYPICAL = 0.55        # a sprite fills about this fraction of its box; crops are ranked by closeness to it
MIX = 0.35            # how much agent colour blends into the opaque pixels


def _ring(box: np.ndarray) -> np.ndarray:
    return np.concatenate([box[0], box[-1], box[1:-1, 0], box[1:-1, -1]]).reshape(-1, 3)


def crop_avatar(frame: np.ndarray, sx: int, sy: int, size: int, key: tuple[int, int, int] | None = None,
                box_wh: tuple[int, int] | None = None) -> np.ndarray | None:
    """A box at (sx, sy) - ``size`` square, or the sprite's own ``box_wh`` tile box when the record
    gives one - with the background keyed to alpha 0. ``key`` overrides the background colour;
    otherwise it is the most common colour in the box's 1 px ring. None when the box is clipped by
    the screen edge, over/under-keyed, or (without ``box_wh``) its ring is not near-uniform, which
    means scenery touches it."""
    h, w = frame.shape[:2]
    bw, bh = box_wh if box_wh else (size, size)
    if sx < 0 or sy < 0 or sx + bw > w or sy + bh > h or bw < 1 or bh < 1:
        return None
    box = frame[sy:sy + bh, sx:sx + bw, :3]
    ring = _ring(box)
    if key is None:
        vals, counts = np.unique(ring, axis=0, return_counts=True)
        key = vals[counts.argmax()]
    near = np.abs(ring.astype(np.int16) - np.asarray(key, np.int16)).max(axis=1) <= KEY_TOL
    if box_wh is None and near.mean() < RING_UNIFORM:
        return None
    dist = np.abs(box.astype(np.int16) - np.asarray(key, np.int16)).max(axis=2)
    alpha = np.where(dist > KEY_TOL, 255, 0).astype(np.uint8)
    opaque = float(alpha.mean()) / 255.0
    if opaque < 1.0 - MAX_KEYED or opaque >= 1.0:
        return None
    out = np.zeros((bh, bw, 4), np.uint8)
    out[..., :3], out[..., 3] = box, alpha
    return out


def tint(rgba: np.ndarray, colour) -> np.ndarray:
    """~35% of ``colour`` mixed into the opaque pixels (alpha kept), plus a 1 px outline
    in the agent colour so tinted pictures of one game stay readable at a glance."""
    out = rgba.copy()
    c = np.asarray(colour, np.float32)
    m = out[..., 3] > 0
    out[..., :3][m] = (out[..., :3][m].astype(np.float32) * (1 - MIX) + c * MIX).astype(np.uint8)
    ring = np.zeros(m.shape, bool)
    ring[1:, :] |= m[:-1, :]
    ring[:-1, :] |= m[1:, :]
    ring[:, 1:] |= m[:, :-1]
    ring[:, :-1] |= m[:, 1:]
    ring &= ~m
    out[..., :3][ring], out[..., 3][ring] = c.astype(np.uint8), 255
    return out


class AvatarCache:
    """The best crop seen so far per (preset, facing), plus tinted variants keyed
    (preset, facing, colour). 'Better' = opaque ratio closest to a typical sprite; ``get`` is None until one."""

    def __init__(self) -> None:
        self._crops: dict[tuple, np.ndarray] = {}
        self._opaque: dict[tuple, int] = {}
        self._tinted: dict[tuple, np.ndarray] = {}
        self._lock = threading.Lock()   # offer runs on the live thread, get on the UI thread

    def offer(self, preset, facing: str, frame: np.ndarray, live) -> None:
        """Crop at the live position and keep it only when it beats the held crop."""
        if live.screen_x is None or live.screen_y is None:
            return
        size = int(getattr(preset, "avatar_size", 16))
        bw, bh = getattr(live, "screen_w", None), getattr(live, "screen_h", None)
        crop = crop_avatar(frame, int(live.screen_x), int(live.screen_y), size,
                           box_wh=(bw, bh) if bw and bh else None)
        if crop is None or max(crop.shape[:2]) > size:
            return
        key = (getattr(preset, "name", preset), facing)
        fit = -abs(float((crop[..., 3] > 0).mean()) - TYPICAL)
        with self._lock:
            if fit > self._opaque.get(key, float("-inf")):
                self._crops[key], self._opaque[key] = crop, fit
                self._tinted = {k: v for k, v in self._tinted.items() if k[:2] != key}

    def ready(self) -> bool:
        return bool(self._crops)

    def get(self, preset, facing: str, colour) -> np.ndarray | None:
        key = (getattr(preset, "name", preset), facing)
        with self._lock:
            crop = self._crops.get(key)
            if crop is None:                    # LEFT/RIGHT share one picture, mirrored
                other = {"LEFT": "RIGHT", "RIGHT": "LEFT"}.get(facing)
                crop = self._crops.get((key[0], other))
                crop = None if crop is None else crop[:, ::-1]
            if crop is None:
                return None
            tkey = (*key, tuple(int(v) for v in colour))
            if tkey not in self._tinted:
                self._tinted[tkey] = tint(crop, tkey[2])
            return self._tinted[tkey]


class AvatarSource:
    """The ``avatars`` object the overlay gets: the rom provider when the preset says
    ``rom_sprite`` and bytes were supplied, else the crop cache (None = draw the square)."""

    def __init__(self, cache: AvatarCache, preset, provider=None) -> None:
        self.cache, self.preset, self.provider = cache, preset, provider

    def ready(self) -> bool:
        return (self.provider is not None and getattr(self.preset, "avatar", "") == "rom_sprite") or self.cache.ready()

    def get(self, agent: str, facing: str, phase: int, colour):
        if getattr(self.preset, "avatar", "") == "rom_sprite" and self.provider is not None:
            return self.provider.get(agent, facing, phase, colour)
        return self.cache.get(self.preset, facing, colour)


def feed(cache: AvatarCache, preset, positions, frame_for, track) -> None:
    """Offer the host's latest frame for each live agent (``frame_for`` may give None)."""
    for agent, pos in positions.items():
        got = frame_for(agent)
        if got is not None:
            rgb, w, h = got
            facing, _ph = track.update(agent, pos.area, pos.x, pos.y)
            cache.offer(preset, facing, np.asarray(rgb, np.uint8).reshape(h, w, -1), pos)
