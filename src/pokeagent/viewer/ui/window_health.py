"""ViewerWindow glue for health lookups, the Stadium/Swarm pane preferences and the layout file.

A mixin (one job: the health/panes/layout host API) so ``window.py`` stays under the size cap.
Expects the host to provide ``health``, ``focus``, ``world``, ``model``, ``root``, ``_layout_path``,
``_stadium``, ``_swarm``, ``_swarm_store``, ``_grid``, ``_stadium_pref``, ``_swarm_pref`` and
``_swarm_default``.
"""
from __future__ import annotations

import logging
from pathlib import Path

import dearpygui.dearpygui as dpg

from pokeagent.viewer import layout_file
from pokeagent.viewer.model import CARD_FRAME_HZ, FOCUS_FRAME_HZ
from pokeagent.viewer.ui import menu
from pokeagent.viewer.ui.stadium_pane import FRAME_S

log = logging.getLogger(__name__)


class HealthLayoutMixin:
    def _health_for(self, agent_id: str):
        """HealthStore lookup (a dict get; the store classified once per refresh)."""
        return self.health.health(agent_id)

    def open_anomaly(self, ref) -> None:
        side = getattr(getattr(self.world, "view", None), "side", None)
        if side is not None:
            side.show_anomaly(ref)

    # -- Stadium pane ---------------------------------------------------------------
    def stadium_visible(self) -> bool:
        """Default follows the mode (shown in World, hidden in Tiles); the menu choice wins for the run."""
        return self._stadium_pref if self._stadium_pref is not None else self.focus.view == "world"

    def set_stadium_pref(self, on) -> None:
        self._stadium_pref = bool(on)

    def on_stadium_close(self, *_args) -> None:
        """The pane's title-bar X: record the choice so the next tick does not re-show it."""
        self.set_stadium_pref(False)

    # -- Swarm page -----------------------------------------------------------------
    def swarm_visible(self) -> bool:
        """Default: shown when this root looks like a swarm run (runs/swarm exists); the menu
        choice wins for the run, the title-bar X hides it."""
        if self._swarm_pref is not None:
            return self._swarm_pref
        if self._swarm_default is None:
            self._swarm_default = self.root is not None and (Path(self.root) / "runs" / "swarm").is_dir()
        return self._swarm_default

    def set_swarm_pref(self, on) -> None:
        self._swarm_pref = bool(on)

    def on_swarm_close(self, *_args) -> None:
        self.set_swarm_pref(False)

    def _panes_tick(self) -> None:
        """Per-UI-frame visibility + content for both top-level panes (Stadium, Swarm)."""
        if self._stadium is not None:
            vis = self.stadium_visible()
            self._stadium.set_visible(vis)
            if dpg.does_item_exist(menu.MENU_STADIUM):
                dpg.set_value(menu.MENU_STADIUM, vis)
            if vis:
                self._stadium.update(self.world.model, self.model)
        if self._swarm is not None:
            vis = self.swarm_visible()
            self._swarm.set_visible(vis)
            if dpg.does_item_exist(menu.MENU_SWARM):
                dpg.set_value(menu.MENU_SWARM, vis)
            if vis:
                self._swarm.update(self._swarm_store.rows())

    # -- pull-model frame demand ------------------------------------------------------
    def visible_frame_set(self) -> dict[str, float]:
        """agent_id -> frame Hz for every card on screen right now: the grid's cards (Tiles view
        only), the focus view's agent, and the Stadium pane's live slots. Max rate wins when an
        agent shows in two places; an empty dict means the poller reads no frames at all."""
        out: dict[str, float] = {}
        if self._grid is not None and self.focus.view == "grid":
            for aid in self._grid.cards:
                out[aid] = CARD_FRAME_HZ
        if self.focus.focused is not None:
            out[self.focus.focused] = FOCUS_FRAME_HZ
        if self._stadium is not None and self.stadium_visible():
            for slot in self._stadium.slots:
                if slot.aid is not None:
                    out[slot.aid] = max(out.get(slot.aid, 0.0), 1.0 / FRAME_S)
        return out

    # -- layout file ------------------------------------------------------------------
    def save_layout(self) -> None:
        if self._layout_path is not None:
            dpg.save_init_file(str(self._layout_path))
            log.info("layout saved to %s", self._layout_path)

    def reset_layout(self) -> None:
        if self._layout_path is not None:
            layout_file.reset_layout(layout_file.DEFAULT, self._layout_path)
            log.info("layout reset to the committed default; applies on next start")
