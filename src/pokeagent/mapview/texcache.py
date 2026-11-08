"""Chunk-texture cache that never leaks and never blanks the map on a rebuild.

``retire`` moves the live textures to a stale set instead of dropping them: they keep being drawn
(``fallback``) until the replacements upload. ``sweep`` deletes the stale tags, and the caller
runs it only after a frame that drew nothing from the stale set, so no draw list references a
texture that is deleted in the same frame. ``delete`` is injected (dpg.delete_item in the window).
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Callable, Hashable


class TexCache:
    def __init__(self, delete: Callable[[object], None], limit: int) -> None:
        self._delete, self.limit = delete, limit
        self.live: OrderedDict[Hashable, object] = OrderedDict()   # (generation, f, cx, cy) -> tag
        self.stale: dict[tuple, object] = {}                       # (f, cx, cy) -> tag
        self.generation = 0

    def key(self, f: int, cx: int, cy: int) -> tuple:
        return (self.generation, f, cx, cy)

    def get(self, f: int, cx: int, cy: int):
        k = self.key(f, cx, cy)
        if k in self.live:
            self.live.move_to_end(k)
            return self.live[k]
        return None

    def fallback(self, f: int, cx: int, cy: int):
        """The previous generation's texture for this chunk, if it is still around."""
        return self.stale.get((f, cx, cy))

    def put(self, f: int, cx: int, cy: int, tag) -> None:
        self.live[self.key(f, cx, cy)] = tag
        while len(self.live) > self.limit:
            self._delete(self.live.popitem(last=False)[1])

    def retire(self) -> None:
        """Rebuild happened: live textures become the stale fallback set. Textures already stale
        from an earlier rebuild are superseded here and deleted."""
        self.sweep()
        self.stale = {k[1:]: tag for k, tag in self.live.items()}
        self.live = OrderedDict()
        self.generation += 1

    def sweep(self) -> None:
        for tag in self.stale.values():
            self._delete(tag)
        self.stale = {}
