"""World view layer composition: which layer images are wanted, and the worker thread that recomposes the pyramid."""
from __future__ import annotations

import threading

from pokeagent.world import draw
from pokeagent.world.pyramid import Pyramid

REBUILD_S = 3.0         # layer images are recomposed at most this often


def want(v) -> tuple:
    maps = frozenset(t.map for t in v.wm.tracks() if t.placed) if v.npcs else frozenset()
    return (frozenset(v.layers), maps, v.wm.rev if v.layers else 0)


def maybe_rebuild(v, now: float) -> None:
    w_ = want(v)
    if v.world is None or v._building or w_ == v._built_for or now - v._built_at < REBUILD_S:
        return
    v._building, v._built_at = True, now

    def work() -> None:
        try:
            w = v.world
            if not w_[0] and not w_[1]:
                img = w.base
            else:
                img = draw.compose_layers(w.base, w.layout, v.wm.union_model(), w.headers, tuple(sorted(w_[0])),
                                          w.book if w_[1] else None, set(w_[1]))
            p = Pyramid(img)
            for f in (2, 4, 8):
                p.level(f)
            v._pending, v._built_for = p, w_
        finally:
            v._building = False
    threading.Thread(target=work, daemon=True, name="world-layers").start()
