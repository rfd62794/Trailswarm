"""ViewerWindow glue for health lookups, the Stadium pane preference and the layout file.

A mixin (one job: the health/stadium/layout host API) so ``window.py`` stays under the size cap.
Expects the host to provide ``health``, ``focus``, ``world``, ``_layout_path`` and ``_stadium_pref``.
"""
from __future__ import annotations

import logging

import dearpygui.dearpygui as dpg

from pokeagent.viewer import layout_file

log = logging.getLogger(__name__)


class HealthLayoutMixin:
    def _health_for(self, agent_id: str):
        """HealthStore lookup (a dict get; the store classified once per refresh)."""
        return self.health.health(agent_id)

    def open_anomaly(self, ref) -> None:
        side = getattr(getattr(self.world, "view", None), "side", None)
        if side is not None:
            side.show_anomaly(ref)

    def stadium_visible(self) -> bool:
        """Default follows the mode (shown in World, hidden in Tiles); the menu choice wins for the run."""
        return self._stadium_pref if self._stadium_pref is not None else self.focus.view == "world"

    def set_stadium_pref(self, on) -> None:
        self._stadium_pref = bool(on)

    def on_stadium_close(self, *_args) -> None:
        """The pane's title-bar X: record the choice so the next tick does not re-show it."""
        self.set_stadium_pref(False)

    def save_layout(self) -> None:
        if self._layout_path is not None:
            dpg.save_init_file(str(self._layout_path))
            log.info("layout saved to %s", self._layout_path)

    def reset_layout(self) -> None:
        if self._layout_path is not None:
            layout_file.reset_layout(layout_file.DEFAULT, self._layout_path)
            log.info("layout reset to the committed default; applies on next start")
