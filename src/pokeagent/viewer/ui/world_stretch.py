"""World view, world variants: build the world the chosen Interiors mode needs on a worker thread and swap it in on the UI thread.

Three variants: ``full`` (inset mode: the whole interior grid), ``compact`` (every in-place mode: the grid holds only the
interiors that could not be placed) and ``stretch`` (compact + the outdoor map locally stretched). Built pairs are cached; the
stretched one is rebuilt only when its inputs (anchors, band overrides) change. A failed build records the error, drops back
to 'auto', says so on screen and is not retried until the inputs change. A swap keeps pan/zoom: the view centre is mapped
through the layout change instead of re-fitting.
"""
from __future__ import annotations

import copy
import logging
import threading
import time

import dearpygui.dearpygui as dpg

from pokeagent.atlas.inplace import LABELS
from pokeagent.atlas.stretch import remap_view
from pokeagent.world.export import compact_world, full_world, stretch_world
from pokeagent.world.pyramid import Pyramid

log = logging.getLogger(__name__)
COMBO = "world_mode_combo"


def _levels(w) -> Pyramid:
    pyr = Pyramid(w.base)
    for f in (2, 4, 8):
        pyr.level(f)
    return pyr


def kind_of(w) -> str:
    return "stretch" if w.layout.warp is not None else ("compact" if w.compact else "full")


def kind_for(mode: str) -> str:
    return {"inset": "full", "stretch": "stretch"}.get(mode, "compact")


class StretchSwap:
    def __init__(self, layer) -> None:
        self.layer = layer
        self.pairs: dict[str, tuple] = {}      # kind -> (World, Pyramid | None)
        self.sigs: dict[str, object] = {}      # kind -> what the cached stretched world was built from
        self.failed_sig = None
        self.building = False
        self.force_full = False                # set when the in-place layout failed: stay on the full world
        self.swapping = False
        self.message = ("", 0.0)
        self._done: tuple | None = None        # (kind, world, pyramid | error text, signature) from the worker

    def signature(self):
        plan = self.layer.plan
        if plan is None:
            return None
        b = self.layer.ov.bands
        return (tuple(sorted((m, a.parent, a.via, a.entry) for m, a in plan.anchors.items())),
                tuple(sorted(b["x"].items())), tuple(sorted(b["y"].items())))

    def _remember(self, have: str) -> None:
        v = self.layer.view
        clean = v.pyr if v.pyr is not None and v.pyr.base is v.world.base else None
        if have not in self.pairs or (self.pairs[have][1] is None and clean is not None and self.pairs[have][0] is v.world):
            self.pairs[have] = (v.world, clean)

    def tick(self) -> None:
        L, v = self.layer, self.layer.view
        if v.world is None:
            return
        have = kind_of(v.world)
        self._remember(have)
        if self._done is not None:
            self._adopt()
            return
        if self.building:
            return
        want, sig = ("full" if self.force_full else kind_for(L.mode)), self.signature()
        if want == "stretch" and (sig is None or sig == self.failed_sig):
            return
        fresh = want != "stretch" or self.sigs.get("stretch") == sig
        if want == have and fresh:
            return
        if want in self.pairs and fresh and self.pairs[want][1] is not None:
            self.swapping, v._loaded = True, self.pairs[want]
            return
        self._spawn(want, sig)

    def _adopt(self) -> None:
        L, v = self.layer, self.layer.view
        kind, w, pyr, sig = self._done
        self._done = None
        if w is None:                       # the build failed: back to auto, tell the user, don't retry these inputs
            self.failed_sig = sig
            L.mode = "auto"                     # this session only: a transient failure must not overwrite the saved choice
            self.message = (f"{kind} world failed ({pyr}); back to auto", time.monotonic() + 8)
            if dpg.does_item_exist(COMBO):
                dpg.set_value(COMBO, LABELS["auto"])
            return
        self.pairs[kind] = (w, pyr)
        self.sigs[kind] = sig
        self.swapping, v._loaded = True, (w, pyr)

    def _spawn(self, kind: str, sig) -> None:
        L, v = self.layer, self.layer.view
        self.building = True
        ov, model = copy.deepcopy(L.ov), v.wm.union_model()
        cached = self.pairs.get(kind)
        full = full_world(v.world)

        def work() -> None:
            try:
                if kind == "stretch":
                    w, pyr = stretch_world(full, model, ov), None
                elif kind == "compact":
                    w, pyr = compact_world(full, model, ov), None
                else:
                    w, pyr = full, None
                if cached is not None and cached[0] is w:
                    pyr = cached[1]
                self._done = (kind, w, pyr or _levels(w), sig)
            except Exception as exc:
                log.exception("%s world build failed", kind)
                self._done = (kind, None, str(exc)[:80], sig)
            finally:
                self.building = False
        threading.Thread(target=work, daemon=True, name="world-variant").start()

    def restore(self, prev_world, prev_vp, vp) -> bool:
        """After a swap: keep zoom and put the view centre on the same place (mapped through the layout change)."""
        if not self.swapping:
            return False
        self.swapping = False
        cx, cy = remap_view(prev_world.layout, self.layer.view.world.layout, prev_vp.cx, prev_vp.cy)
        vp.zoom, vp.auto_fit = prev_vp.zoom, False
        vp.center_on(cx, cy)
        return True
