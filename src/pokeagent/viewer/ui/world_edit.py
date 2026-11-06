"""World view, 'edit layout': drag an interior = move, Ctrl+wheel = scale, reset. Changes apply live and are saved to the user
overrides file after a short quiet period (debounced, atomic) and at exit - never once per wheel notch."""
from __future__ import annotations

import atexit
import logging
import time

import dearpygui.dearpygui as dpg

from pokeagent.atlas.world import CELL

log = logging.getLogger(__name__)
SAVE_AFTER_S = 0.5


class EditLayout:
    def __init__(self, layer) -> None:
        self.layer = layer
        self.on = False
        self.drag_map: int | None = None
        self.rev = 0                              # bumps on edits that need a replan (scale, reset); a drag shifts the plan live
        self._dirty_at: float | None = None
        atexit.register(self.flush)

    def touch(self, replan: bool = False) -> None:
        self._dirty_at = time.monotonic()
        self.rev += replan

    def tick(self, now: float) -> None:
        if self._dirty_at is not None and now - self._dirty_at >= SAVE_AFTER_S:
            self.flush()

    def flush(self) -> None:
        if self._dirty_at is None:
            return
        try:
            self.layer.ov.save()
        except OSError as exc:                 # stay dirty: the next tick retries
            log.warning("layout overrides not saved (will retry): %s", exc)
            self._dirty_at = time.monotonic()
            return
        self._dirty_at = None

    def press(self) -> None:
        L = self.layer
        self.drag_map = L.hover if self.on and L.hover in L.shown else None

    def drag(self, dsx: float, dsy: float) -> bool:
        """Move the pressed interior by a screen delta; False when nothing is being dragged (the view pans instead)."""
        L = self.layer
        if self.drag_map is None or L.plan is None:
            return False
        z = L.view.vp.zoom * CELL
        L.ov.move(self.drag_map, dsx / z, dsy / z)
        L.plan.shift(self.drag_map, dsx / z, dsy / z)
        self.touch()
        return True

    def release(self) -> None:
        self.drag_map = None

    def wheel(self, delta: float) -> bool:
        L = self.layer
        m = L.hover if L.hover in L.shown else L.selected
        ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
        if not (self.on and ctrl and m is not None and L.plan and m in L.plan.xf(L.eff_mode)):
            return False
        L.ov.rescale(m, L.plan.xf(L.eff_mode)[m].s, 1.1 if float(delta) > 0 else 1 / 1.1)
        self.touch(True)
        return True

    def reset(self, everything: bool = False) -> None:
        L = self.layer
        m = L.selected if L.selected is not None else L.hover
        if everything or m is not None:
            L.ov.reset(None if everything else m)
            self.touch(True)
