"""The Dear PyGui viewer window: grid/focus areas over a control bar, driven by ViewerModel.

The render loop only reads the model (never blocks on the network); commands go out through
``sources`` on user actions. All dearpygui imports in the viewer live under viewer/ui/.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import dearpygui.dearpygui as dpg

from pokeagent.viewer import commands, steering
from pokeagent.viewer.layout import FocusState
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.panels import BG
from pokeagent.viewer.ui import keys, theme
from pokeagent.viewer.ui.card import CardView
from pokeagent.viewer.ui.control_bar import BAR_TAG, ControlBar
from pokeagent.viewer.ui.focus_view import FocusView
from pokeagent.viewer.ui.grid_view import GridView
from pokeagent.viewer import ui_scale
from pokeagent.viewer.screen_fit import viewport_size, work_area
from pokeagent.viewer.spawn_control import SpawnControl
from pokeagent.viewer.ui.world_host import WorldHost
from pokeagent.world.model import WorldModel

log = logging.getLogger(__name__)
_BAR_H = 120  # reserved height for the three control-bar rows


class ViewerWindow:
    """Builds and runs the DPG context. ``hold_s_for(agent_id)`` may return the human-hold
    countdown when the agent exposes one (HTTP agents do not -> bare "YOU HAVE IT")."""

    def __init__(self, model: ViewerModel, sources: dict, fps: int = 30,
                 supervisor=None, hold_s_for: Callable[[str], float | None] | None = None,
                 root: Path | None = None, world: WorldModel | None = None) -> None:
        self.model, self.sources, self.fps = model, sources, fps
        self.supervisor, self.root = supervisor, root
        self._spawn = SpawnControl(supervisor, root)
        self._hold_s_for = hold_s_for or (lambda _aid: None)
        self.focus = FocusState()
        self.world = WorldHost(self, world)
        self.selected: str | None = None
        self.scope = "all"
        self._speed = 1
        self._paused = False
        self._throttle = steering.KeyThrottle()
        self._gate = steering.PressGate()
        self._shown_focus: str | None = None
        self._grid: GridView | None = None
        self._focus_view: FocusView | None = None
        self._bar: ControlBar | None = None
        self._win = "viewer_main"
        self._last_size: tuple[int, int] = (0, 0)
        self._outbox: queue.Queue = queue.Queue()  # sends run on a worker so the UI never waits on HTTP
        threading.Thread(target=self._send_loop, daemon=True, name="viewer-send").start()

    def _send_loop(self) -> None:
        while True:
            src, cmd, args = self._outbox.get()
            try:
                src.send(cmd, **args)
            except Exception:
                pass  # sources never raise by contract; a bad one must not kill the sender
            finally:
                self._outbox.task_done()

    def flush_sends(self) -> None:
        """Block until queued commands were sent (tests; never call from the render loop)."""
        self._outbox.join()

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
        self.send_to_targets("pause" if self._paused else "resume")

    def steering(self) -> bool:
        """Read-only: keyboard steering is on exactly while an agent is focused."""
        return self.focus.focused is not None

    def target_snaps(self):
        return [s for aid in self._target_ids() if (s := self.model.snapshot(aid)) is not None]

    def hand_to(self, driver: str) -> None:
        self.send_to_targets("hand_to", driver=driver)

    def save_state(self, name: str) -> None:
        self.send_to_targets("save_state", name=name or "slot")

    def load_state(self, name: str) -> None:
        self.send_to_targets("load_state", name=name or "slot")

    def at_agent_cap(self) -> bool:
        """Cached (refreshed off the UI thread every 2 s): True when spawning is disabled."""
        self._spawn.refresh()
        return self._spawn.capped

    @property
    def spawn_msg(self) -> str:
        return self._spawn.message

    def spawn_agent(self, kind: str, args: str) -> None:
        self._spawn.spawn(kind, args)

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
                self._outbox.put((src, cmd, args))

    def key_button(self, key_name: str) -> None:
        """Game key: reaches only the focused agent (never in grid view), <=1 press / 120 ms / key."""
        hit = steering.press_target(key_name, self.focus.focused, self._throttle)
        if hit is not None:
            self._send_one(hit[0], "press", button=hit[1], source="human")

    def hotkey(self, name: str) -> None:
        """P / T: transport hotkeys, focus view only, one toggle per physical press."""
        if self.focus.focused is not None and self._gate.allow(name):
            self.toggle_pause() if name == "pause" else self.cycle_speed()

    def escape(self) -> None:
        self.leave_focus()

    # -- focus / selection --------------------------------------------------------
    def _send_one(self, aid: str, cmd: str, **args) -> None:
        src = self.sources.get(aid)
        if src is not None:
            self._outbox.put((src, cmd, args))

    def toggle_focus(self, agent_id: str) -> None:
        """Double-click: enter focus (steer on) or, on the focused card, leave it."""
        if self.focus.focused == agent_id:
            self.leave_focus()
        elif self.focus.focused is None:
            self.focus.focus(agent_id)
            self.selected = agent_id
            self._send_one(agent_id, "steer", on=True)

    def leave_focus(self) -> None:
        """Back to grid: hand the agent back (hold_release) and turn steering off."""
        aid = self.focus.focused
        self.focus.back()
        if aid is not None:
            self._send_one(aid, "hold_release")
            self._send_one(aid, "steer", on=False)

    def _on_select(self, agent_id: str) -> None:
        self.selected = agent_id

    def _target_ids(self) -> list[str]:
        if self.focus.focused is not None:  # control bar acts on the focused agent only
            return [self.focus.focused]
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
        scale = ui_scale.init()  # DPI awareness first; sizes below are physical px
        dpg.create_context()
        vw, vh = viewport_size(work_area(), scale)  # never taller than the screen: the control bar stays visible
        dpg.create_viewport(title="PokeAgent viewer", width=vw, height=vh, x_pos=0, y_pos=0,
                            clear_color=self._bg())

    def _populate(self) -> None:
        """All widgets. Needs setup_dearpygui first: groups/fonts resolve at setup time."""
        dpg.add_window(tag=self._win, no_collapse=True, no_move=True, no_resize=True,
                       no_title_bar=True, no_scrollbar=True, width=10, height=10)
        dpg.add_texture_registry(tag="viewer_tex", show=False)
        self._grid = GridView(self._win, self.model, self._card_factory,
                              self.toggle_focus, self._on_select)
        self._focus_view = FocusView(self._win, self.model, self._card_factory,
                                     self.leave_focus, self.toggle_focus, self._on_select)
        self.world.build()
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
        avail = max(80, vh - ui_scale.px(_BAR_H))
        self.world.fit(vw, avail)
        for view in (self._grid, self._focus_view):
            if view is not None and dpg.does_item_exist(view.area):
                dpg.delete_item(view.area)
                is_grid = view is self._grid
                view.area = dpg.add_child_window(parent=self._win, before=BAR_TAG, width=vw - 8,
                                                 height=avail, border=False, no_scrollbar=True,
                                                 show=self.area_visible(is_grid),
                                                 tag="grid_area" if is_grid else "focus_area")
                view.cards = {}
                view.card = None
                view._sig = None

    # -- frame loop ----------------------------------------------------------------
    def area_visible(self, is_grid: bool) -> bool:
        """Which card area shows in the current mode (also used when areas are recreated on resize)."""
        return self.focus.view == ("grid" if is_grid else "focus")

    def drop_lost_focus(self) -> None:
        if self.focus.focused is not None and self.focus.focused not in self.model.ids():
            self.leave_focus()  # the focused agent was lost/pruned: back to the grid

    def _title(self, fps: float | None = None) -> str:
        mode = f"focus {self.focus.focused}" if self.focus.focused else self.focus.mode
        return f"PokeAgent viewer [{mode}]" + (f" - {fps:.0f} fps" if fps is not None else "")

    def tick(self) -> None:
        self.drop_lost_focus()
        focused = self.focus.focused
        if focused != self._shown_focus:  # the title always names the view (and what steers)
            self._shown_focus = focused
            dpg.set_viewport_title(self._title(getattr(self, "ui_fps", None)))
        self.world.tick()
        if self._grid is not None:
            dpg.configure_item(self._grid.area, show=self.focus.view == "grid")
        if self._focus_view is not None and dpg.does_item_exist(self._focus_view.area):
            dpg.configure_item(self._focus_view.area, show=focused is not None)
            self._focus_view.sync(focused)
        if self._grid is not None:
            self._grid.pin = focused or self.selected  # the agent being watched/steered never pages out
            self._grid.sync()
        hold = self._hold_s_for
        if self._grid is not None and self.focus.view == "grid":
            self._grid.update(hold)
            for aid, card in self._grid.cards.items():
                card.set_selected(aid == self.selected)
        if self._focus_view is not None:
            self._focus_view.update(hold)
        if self._bar is not None:
            self._bar.refresh()
        self._fit()

    def run(self) -> None:
        self._build()
        dpg.set_viewport_resize_callback(lambda *_: setattr(self, "_last_size", (0, 0)))
        dpg.setup_dearpygui(); ui_scale.install_font(dpg); self._populate()
        theme.apply()  # theme colours need the initialized context; binds before first frame
        dpg.show_viewport()
        dpg.set_primary_window(self._win, True)
        frames, t_mark = 0, time.monotonic()
        while dpg.is_dearpygui_running():
            t0 = time.monotonic()
            self.tick()
            dpg.render_dearpygui_frame()
            frames += 1
            if t0 - t_mark >= 5.0:  # fps counter: title + one log line per 5 s
                self.ui_fps = frames / (t0 - t_mark)
                dpg.set_viewport_title(self._title(self.ui_fps))
                log.info("ui fps %.1f", self.ui_fps)
                frames, t_mark = 0, t0
            time.sleep(max(0.0, 1.0 / self.fps - (time.monotonic() - t0)))
        dpg.destroy_context()
