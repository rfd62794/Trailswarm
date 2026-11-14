"""The record loop: drive an Emulator through presses, label each sampled frame, write the dataset."""
from __future__ import annotations

import time

import numpy as np

from pokeagent.vision.crops import FRAME_H, FRAME_W, crop, thumb

FLUSH_S = 60.0              # the indexes hit disk atomically at least this often and at the end
THUMB_EVERY = 30


def _region(x: int, y: int, w: int, h: int) -> str:
    """The 3x3 screen cell "r<0-2>c<0-2>" holding the box centre."""
    col = min(2, max(0, (x + w // 2) * 3 // FRAME_W))
    row = min(2, max(0, (y + h // 2) * 3 // FRAME_H))
    return f"r{row}c{col}"


def record(emu, source, store, positions, presses, *, sample_every: int = 8,
           thumb_every: int = THUMB_EVERY, run: str = "run") -> dict:
    """For each (button, hold, settle): press(hold, settle 0), then run hold+settle frames in
    rendered chunks of ``sample_every``, reading labels after each chunk. Returns counters; the
    loop stops when the store is full AND the positions log is capped."""
    counters = {"presses": 0, "frames": 0, "samples": 0, "skipped": 0, "stopped": False}
    last_flush = time.monotonic()
    for button, hold, settle in presses:
        counters["presses"] += 1
        emu.press(button, hold, 0)              # registers the hold; a zero settle ticks nothing
        left = settle + hold
        while left > 0:
            chunk = min(sample_every, left)
            emu.tick_rendered(chunk)
            left -= chunk
            counters["frames"] += chunk
            labels = source.read(emu)
            if labels.skip:
                counters["skipped"] += 1
            else:
                counters["samples"] += 1
                frame = np.frombuffer(emu.frame_rgb(), np.uint8).reshape(FRAME_H, FRAME_W, 3)
                for s in labels.sprites:
                    arr = crop(frame, s.x, s.y, s.w, s.h)
                    if arr is not None:
                        store.add_crop("sprite", s.label, s.coarse, labels.area,
                                       _region(s.x, s.y, s.w, s.h), s.x, s.y, s.w, s.h, None, arr)
                for t in labels.tiles:
                    arr = crop(frame, t.x, t.y, 8, 8)
                    if arr is not None:
                        store.add_crop("tile", t.label, "terrain", labels.area,
                                       _region(t.x, t.y, 8, 8), t.x, t.y, 8, 8, labels.bank, arr)
                positions.append(emu.frames, run, labels.area, labels.player,
                                 [[s.ident, s.label, *(s.pos if s.pos is not None else (s.x, s.y)),
                                   s.move] for s in labels.sprites])
                if counters["samples"] % thumb_every == 0:
                    store.add_thumb(labels.area, labels.cell, labels.player, thumb(frame))
            if store.full and positions.capped:
                counters["stopped"] = True
                store.meta.update(frames_seen=counters["frames"], positions_capped=True)
                return counters
            if time.monotonic() - last_flush > FLUSH_S:
                store.meta.update(frames_seen=counters["frames"], positions_capped=positions.capped)
                store.flush()
                last_flush = time.monotonic()
    store.meta.update(frames_seen=counters["frames"], positions_capped=positions.capped)
    return counters
