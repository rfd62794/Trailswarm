"""World view, stretch world: build the stretched world once on a worker thread and swap it in (and back) on the UI thread.

The stretched pair is cached and rebuilt only when what it depends on changes (anchors or band overrides). A failed build
records the error, drops back to 'auto', says so on screen and is not retried until that dependency changes. A swap keeps the
pan/zoom: the view centre is mapped through the warp instead of re-fitting.
"""
from __future__ import annotations

import copy
import logging
import threading
import time

import dearpygui.dearpygui as dpg

from pokeagent.atlas.inplace import LABELS
from pokeagent.atlas.stretch import remap_view
from pokeagent.world.export import stretch_world
from pokeagent.world.pyramid import Pyramid

log = logging.getLogger(__name__)
COMBO = "world_mode_combo"


def _levels(w) -> Pyramid:
    pyr = Pyramid(w.base)
    for f in (2, 4, 8):
        pyr.level(f)
    return pyr


class StretchSwap:
    def __init__(self, layer) -> None:
        self.layer = layer
        self.plain = None                     # the un-stretched World (and its pyramid when it is the clean base one)
        self.plain_pyr = None
        self.built_sig = None
        self.failed_sig = None
        self.building = False
        self.swapping = False
        self.message = ("", 0.0)
        self._done: tuple | None = None       # (kind, world, pyramid, signature) handed from the worker to the UI thread

    def signature(self):
        plan = self.layer.plan
        if plan is None:
            return None
        b = self.layer.ov.bands
        return (tuple(sorted((m, a.parent, a.via, a.entry) for m, a in plan.anchors.items())),
                tuple(sorted(b["x"].items())), tuple(sorted(b["y"].items())))

    def tick(self) -> None:
        L, v = self.layer, self.layer.view
        if v.world is None:
            return
        if v.world.layout.warp is None:
            self.plain = v.world
            if v.pyr is not None and v.pyr.base is v.world.base:
                self.plain_pyr = v.pyr
        if self._done is not None:
            kind, w, pyr, sig = self._done
            self._done = None
            if w is None:                       # the build failed: back to auto, tell the user, don't retry this input
                self.failed_sig = sig
                L.mode = "auto"
                self.message = (f"stretch failed ({pyr}); back to auto", time.monotonic() + 8)
                if dpg.does_item_exist(COMBO):
                    dpg.set_value(COMBO, LABELS["auto"])
            else:
                self.swapping, self.built_sig = True, sig if kind == "stretch" else self.built_sig
                v._loaded = (w, pyr)
            return
        if self.building or self.plain is None:
            return
        have = "stretch" if v.world.layout.warp is not None else "plain"
        want = "stretch" if L.mode == "stretch" else "plain"
        sig = self.signature()
        if want == "stretch" and (sig is None or sig == self.failed_sig or (have == "stretch" and sig == self.built_sig)):
            return
        if want == have and want == "plain":
            return
        self._spawn(want, sig)

    def _spawn(self, kind: str, sig) -> None:
        L, v = self.layer, self.layer.view
        self.building = True
        ov, model, plain, plain_pyr = copy.deepcopy(L.ov), v.wm.union_model(), self.plain, self.plain_pyr

        def work() -> None:
            try:
                if kind == "stretch":
                    w = stretch_world(plain, model, ov)
                    self._done = ("stretch", w, _levels(w), sig)
                else:
                    self._done = ("plain", plain, plain_pyr or _levels(plain), sig)
            except Exception as exc:
                log.exception("stretch world build failed")
                self._done = (kind, None, str(exc)[:80], sig)
            finally:
                self.building = False
        threading.Thread(target=work, daemon=True, name="world-stretch").start()

    def restore(self, prev_world, prev_vp, vp) -> bool:
        """After a swap: keep zoom and put the view centre on the same place (mapped through the warp)."""
        if not self.swapping:
            return False
        self.swapping = False
        cx, cy = remap_view(prev_world.layout, self.layer.view.world.layout, prev_vp.cx, prev_vp.cy)
        vp.zoom, vp.auto_fit = prev_vp.zoom, False
        vp.center_on(cx, cy)
        return True
