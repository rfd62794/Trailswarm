"""The Dear PyGui viewer window: grid/focus areas over a control bar, driven by ViewerModel.

The render loop only reads the model (never blocks on the network); commands go out through
``sources`` on user actions. All dearpygui imports in the viewer live under viewer/ui/.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import dearpygui.dearpygui as dpg

from pokeagent.viewer import commands
from pokeagent.viewer.layout import FocusState
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.panels import BG
from pokeagent.viewer.ui import keys, theme
from pokeagent.viewer.ui.card import CardView
from pokeagent.viewer.ui.control_bar import BAR_TAG, ControlBar
from pokeagent.viewer.ui.focus_view import FocusView
from pokeagent.viewer.ui.grid_view import GridView

_BAR_H = 120  # reserved height for the three control-bar rows


class ViewerWindow:
    """Builds and runs the DPG context. ``hold_s_for(agent_id)`` may return the human-hold
    countdown when the agent exposes one (HTTP agents do not -> bare "YOU HAVE IT")."""

    def __init__(self, model: ViewerModel, sources: dict, fps: int = 30,
                 supervisor=None, hold_s_for: Callable[[str], float | None] | None = None,
                 root: Path | None = None) -> None:
        self.model, self.sources, self.fps = model, sources, fps
        self.supervisor, self.root = supervisor, root
        self._hold_s_for = hold_s_for or (lambda _aid: None)
        self.focus = FocusState()
        self.selected: str | None = None
        self.scope = "all"
        self._speed = 1
        self._paused = False
        self._steer = False
        self._grid: GridView | None = None
        self._focus_view: FocusView | None = None
        self._bar: ControlBar | None = None
        self._win = "viewer_main"
        self._last_size: tuple[int, int] = (0, 0)

    # -- host API for control_bar / keys ----------------------------------------
    def set_scope(self, scope: str) -> None:
        self.scope = scope

    def selected_id(self) -> str | None:
        return self.selected

    def speed(self) -> int:
        return self._speed

    def paused(self) -> bool:
        return self._paused

    def cycle_speed(self) -> None:
        self._speed = commands.next_speed(self._speed)
        self.send_to_targets("speed", n=self._speed)

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.send_to_targets("resume" if self._paused else "pause")

    def set_steer(self, on: bool) -> None:
        self._steer = on
        self.send_to_targets("steer", on=on)

    def target_snaps(self):
        return [s for aid in self._target_ids() if (s := self.model.snapshot(aid)) is not None]

    def hand_to(self, driver: str) -> None:
        self.send_to_targets("hand_to", driver=driver)

    def save_state(self, name: str) -> None:
        self.send_to_targets("save_state", name=name or "slot")

    def load_state(self, name: str) -> None:
        self.send_to_targets("load_state", name=name or "slot")

    def spawn_agent(self, kind: str, args: str) -> None:
        if self.supervisor is not None:
            argv = [kind] + (args.split() if args else [])
            self.supervisor.spawn(*argv)

    def stop_targets(self) -> None:
        if self.supervisor is not None:
            for aid in self._target_ids():
                pid = self._pid_for(aid)
                if pid is not None:
                    self.supervisor.stop(pid)

    def send_to_targets(self, cmd: str, **args) -> None:
        for aid in self._target_ids():
            src = self.sources.get(aid)
            if src is not None:
                src.send(cmd, **args)

    def key_button(self, key_name: str) -> None:
        """Steer-gated game key: reaches only the selected agent, only while Steer is on."""
        button = commands.press_for_key(key_name, self._steer)
        if button is None or self.selected is None:
            return
        src = self.sources.get(self.selected)
        if src is not None:
            src.send("press", button=button, source="human")

    def escape(self) -> None:
        self.focus.back()

    # -- focus / selection --------------------------------------------------------
    def _on_focus(self, agent_id: str) -> None:
        self.focus.toggle(agent_id)

    def _on_select(self, agent_id: str) -> None:
        self.selected = agent_id

    def _target_ids(self) -> list[str]:
        return commands.targets(self.selected, self.model.ids(), self.scope)

    def _pid_for(self, agent_id: str) -> int | None:
        entry = getattr(self, "entries", {}).get(agent_id)
        pid = entry.get("pid") if isinstance(entry, dict) else None
        return int(pid) if pid else None

    # -- build --------------------------------------------------------------------
    def _card_factory(self, parent, agent_id, w, h, on_focus, on_select, big=False):
        return CardView(parent, agent_id, w, h, on_focus, on_select, big=big)

    def _build(self) -> None:
        """Context + viewport only - safe without a display (the smoke test stops here)."""
        dpg.create_context()
        dpg.create_viewport(title="PokeAgent viewer", width=1500, height=950,
                            clear_color=self._bg())

    def _populate(self) -> None:
        """All widgets. Needs setup_dearpygui first: groups/fonts resolve at setup time."""
        dpg.add_window(tag=self._win, no_collapse=True, no_move=True, no_resize=True,
                       no_title_bar=True, no_scrollbar=True, width=10, height=10)
        dpg.add_texture_registry(tag="viewer_tex", show=False)
        self._grid = GridView(self._win, self.model, self._card_factory,
                              self._on_focus, self._on_select)
        self._focus_view = FocusView(self._win, self.model, self._card_factory,
                                     self.focus.back, self._on_focus, self._on_select)
        self._bar = ControlBar(self._win, self)
        keys.install(self)
        self._fit()

    def _bg(self) -> list[int]:
        c = BG.lstrip("#")
        return [int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255]

    def _fit(self) -> None:
        """Size the window to the viewport and rebuild the card areas (resize only)."""
        vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        if (vw, vh) == self._last_size or vw < 50 or vh < 50:
            return
        self._last_size = (vw, vh)
        dpg.configure_item(self._win, pos=[0, 0], width=vw, height=vh)
        avail = max(80, vh - _BAR_H)
        for view in (self._grid, self._focus_view):
            if view is not None and dpg.does_item_exist(view.area):
                dpg.delete_item(view.area)
                view.area = dpg.add_child_window(parent=self._win, before=BAR_TAG, width=vw - 8,
                                                 height=avail, border=False, no_scrollbar=True,
                                                 tag="grid_area" if view is self._grid else "focus_area")
                view.cards = {}
                view.card = None
                view._sig = None

    # -- frame loop ----------------------------------------------------------------
    def tick(self) -> None:
        focused = self.focus.focused
        if self._grid is not None:
            dpg.configure_item(self._grid.area, show=focused is None)
        if self._focus_view is not None and dpg.does_item_exist(self._focus_view.area):
            dpg.configure_item(self._focus_view.area, show=focused is not None)
            self._focus_view.sync(focused)
        if self._grid is not None:
            self._grid.sync()
        hold = self._hold_s_for
        if self._grid is not None and focused is None:
            self._grid.update(hold)
        if self._focus_view is not None:
            self._focus_view.update(hold)
        if self._bar is not None:
            self._bar.refresh()
        self._fit()

    def run(self) -> None:
        self._build()
        dpg.set_viewport_resize_callback(lambda *_: setattr(self, "_last_size", (0, 0)))
        dpg.setup_dearpygui()
        self._populate()
        theme.apply()  # theme colours need the initialized context; binds before first frame
        while dpg.is_dearpygui_running():
            t0 = time.monotonic()
            self.tick()
            dpg.render_dearpygui_frame()
            time.sleep(max(0.0, 1.0 / self.fps - (time.monotonic() - t0)))
        dpg.destroy_context()
