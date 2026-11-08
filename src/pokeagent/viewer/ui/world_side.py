"""World mode side panel: the health badge/panel, layer toggles, tile info, event feed.

The old Stadium strip moved out to ``stadium_pane`` (a real top-level window)."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.atlas import inplace
from pokeagent.atlas.overlay import LAYERS
from pokeagent.viewer.ui import tags
from pokeagent.viewer.ui.health_panel import HealthPanel
from pokeagent.viewer.ui_scale import get_scale, px
from pokeagent.world.tileinfo import describe

SIDE_W = 380                   # 1x fallback; the live width is proportional (ui_scale.side_panel_width)
FEED_KINDS = {"all": None, "battles": {"battle_start", "battle_turn", "battle_end"}, "items": {"item"},
              "goals": {"goal"}, "stalls": {"stall", "human_hold"}, "learned": {"learn"}}
LEARN = tuple(l for l in LAYERS if l not in ("trails", "agents"))


class WorldSide:
    def __init__(self, view) -> None:
        self.view = view
        self.width = px(SIDE_W)
        self.host = None                       # set by the window: model (frames) + on_focus
        self._feed_sig: tuple = ()
        self._tile: list[str] = []
        self.kind = "all"
        self.panel = dpg.add_child_window(width=self.width, height=10, border=False, tag=tags.WORLD_SIDE)
        with dpg.group(parent=self.panel):
            self.health = HealthPanel()        # badge + expandable HEALTH_PANEL section
            dpg.add_separator()
            dpg.add_text("Layers (learned by all agents)")
            with dpg.group(horizontal=True):
                for name in LEARN:
                    dpg.add_checkbox(label=name, callback=self._cb(name))
            with dpg.group(horizontal=True):
                dpg.add_checkbox(label="trails", default_value=True, callback=lambda s, a, u: setattr(view, "trails", a))
                dpg.add_checkbox(label="NPCs", callback=lambda s, a, u: setattr(view, "npcs", a))
                dpg.add_button(label="Fit", callback=lambda s, a, u: view.vp.fit())
                dpg.add_button(label="1:1", callback=lambda s, a, u: view.vp.one_to_one(get_scale()))
            with dpg.group(horizontal=True):
                dpg.add_text("Interiors")
                names = {v: k for k, v in inplace.LABELS.items()}
                dpg.add_combo(list(names), default_value=inplace.LABELS[view.interiors.mode], width=px(200), tag="world_mode_combo",
                              callback=lambda s, a, u: view.interiors.set_mode(names[a]))
            with dpg.group(horizontal=True):
                dpg.add_checkbox(label="edit layout", callback=lambda s, a, u: setattr(view.interiors.edit, "on", a))
                dpg.add_button(label="Reset interior", callback=lambda s, a, u: view.interiors.reset())
                dpg.add_button(label="Reset all", callback=lambda s, a, u: view.interiors.reset(True))
            dpg.add_text("edit: drag an interior = move, Ctrl+wheel = scale (saved to runs/atlas/layout_overrides.json)", wrap=px(340))
            dpg.add_separator()
            dpg.add_text("Tile (click the map)")
            self.tile = dpg.add_text("", wrap=self.width - px(20))
            dpg.add_separator()
            dpg.add_combo(list(FEED_KINDS), default_value="all", width=px(120), callback=lambda s, a, u: setattr(self, "kind", a))
            self.feed = dpg.add_child_window(height=-1, border=False)

    def _cb(self, name: str):
        def cb(sender, app_data, user_data=None):
            (self.view.layers.add if app_data else self.view.layers.discard)(name)
        return cb

    def bind(self, model, on_focus) -> None:
        self.host = (model, on_focus)

    def bind_health(self, store, entries) -> None:
        """``store`` is the HealthStore fed by the poll thread; ``entries`` the agent registry dict."""
        self.health.bind(store, entries)

    def show_anomaly(self, ref) -> None:
        self.health.show_anomaly(ref)

    def fit(self, w: int, h: int) -> None:
        """Proportional width; the tile/feed text wraps to it."""
        self.width = w
        dpg.configure_item(self.panel, width=w, height=max(100, h - 8))
        dpg.configure_item(self.tile, wrap=w - px(20))

    def show_tile(self, map_id: int, x: int, y: int) -> None:
        w = self.view.world
        self._tile = describe(map_id, x, y, w.headers, self.view.wm) if w else []
        dpg.set_value(self.tile, "\n".join(self._tile))

    def update(self) -> None:
        if self.host is None:
            return
        model, _ = self.host
        self.health.update(model.ids())
        rows = self.view.wm.feed(FEED_KINDS[self.kind], 40)
        sig = (self.kind, len(rows), rows[-1][1].get("seq") if rows else 0, rows[-1][0] if rows else "")
        if sig != self._feed_sig:
            self._feed_sig = sig
            dpg.delete_item(self.feed, children_only=True)
            for aid, d in reversed(rows):
                dpg.add_text(f"{aid[-6:]} {_line(d)}", parent=self.feed, wrap=self.width - px(30))


def _line(d: dict) -> str:
    t = d.get("type", "")
    if t == "battle_start":
        return f"battle vs {d.get('species')} L{d.get('enemy_level')}"
    if t == "battle_end":
        return f"battle {d.get('result')}"
    if t == "battle_turn":
        return f"turn {d.get('turn')} {d.get('move', '')}"
    if t in ("goal", "item"):
        return f"{t} {d.get('name')} {d.get('status', d.get('action', ''))}"
    if t == "learn":
        return f"learned {d.get('kind')} @ {d.get('map')}:{d.get('x')},{d.get('y')}"
    if t == "map_change":
        return f"entered map 0x{d.get('map', 0):02X}"
    if t == "stall":
        return f"STALL {d.get('reason')}"
    return t
