"""World mode side panel: layer toggles, the stadium strip (one panel per agent in battle, max 8), tile info, event feed."""
from __future__ import annotations

import time

import dearpygui.dearpygui as dpg

from pokeagent.atlas import inplace
from pokeagent.atlas.overlay import LAYERS
from pokeagent.viewer.panels.render import frame_rgba
from pokeagent.viewer.ui_scale import get_scale, px
from pokeagent.world import stadium
from pokeagent.world.tileinfo import describe

SIDE_W = 380                   # 1x fallback; the live width is proportional (ui_scale.side_panel_width)
FW, FH = 120, 108              # live frame in a stadium panel
FEED_KINDS = {"all": None, "battles": {"battle_start", "battle_turn", "battle_end"}, "items": {"item"},
              "goals": {"goal"}, "stalls": {"stall", "human_hold"}, "learned": {"learn"}}
LEARN = tuple(l for l in LAYERS if l not in ("trails", "agents"))
FRAME_S = 0.1


class Slot:
    """One stadium panel: live frame (click = focus view) next to the battle card."""

    def __init__(self, parent, idx: int, on_focus) -> None:
        self.aid: str | None = None
        self._last = 0.0
        self.tex = dpg.add_raw_texture(FW, FH, [0.0] * (FW * FH * 4), parent="viewer_tex")  # texture stays 1x; the button scales it
        self.group = dpg.add_group(horizontal=True, parent=parent, show=False)
        self.btn = dpg.add_image_button(self.tex, width=px(FW), height=px(FH), parent=self.group,
                                        callback=lambda s, a, u: self.aid and on_focus(self.aid))
        with dpg.group(parent=self.group):
            self.title = dpg.add_text("")
            self.text = dpg.add_text("")
            self.you = dpg.add_progress_bar(width=px(200), overlay="you")
            self.foe = dpg.add_progress_bar(width=px(200), overlay="enemy")

    def show(self, aid: str, card, frame, now: float) -> None:
        self.aid = aid
        dpg.show_item(self.group)
        rows = stadium.lines(card)
        dpg.set_value(self.title, f"{aid}")
        dpg.set_value(self.text, "\n".join(rows[0:1] + rows[2:]))
        dpg.set_value(self.you, stadium.hp_frac(card.hp, card.max_hp))
        dpg.set_value(self.foe, stadium.hp_frac(card.enemy_hp, card.enemy_max_hp))
        if frame is not None and now - self._last > FRAME_S:
            self._last = now
            dpg.set_value(self.tex, frame_rgba(frame[0], frame[1], frame[2], FW, FH))

    def hide(self) -> None:
        self.aid = None
        dpg.hide_item(self.group)


class WorldSide:
    def __init__(self, view) -> None:
        self.view = view
        self.width = px(SIDE_W)
        self.host = None                       # set by the window: model (frames) + on_focus
        self._feed_sig: tuple = ()
        self._tile: list[str] = []
        self.kind = "all"
        self.panel = dpg.add_child_window(width=self.width, height=10, border=False, tag="world_side")
        with dpg.group(parent=self.panel):
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
                dpg.add_combo(list(names), default_value=inplace.LABELS["auto"], width=px(200), tag="world_mode_combo",
                              callback=lambda s, a, u: setattr(view.interiors, "mode", names[a]))
            with dpg.group(horizontal=True):
                dpg.add_checkbox(label="edit layout", callback=lambda s, a, u: setattr(view.interiors.edit, "on", a))
                dpg.add_button(label="Reset interior", callback=lambda s, a, u: view.interiors.reset())
                dpg.add_button(label="Reset all", callback=lambda s, a, u: view.interiors.reset(True))
            dpg.add_text("edit: drag an interior = move, Ctrl+wheel = scale (saved to runs/atlas/layout_overrides.json)", wrap=px(340))
            dpg.add_separator()
            self.strip_title = dpg.add_text("Stadium")
            self.slots_parent = dpg.add_group()
            self.slots: list[Slot] = []
            self.more = dpg.add_text("", color=(255, 200, 80, 255))
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
        self.slots = [Slot(self.slots_parent, i, on_focus) for i in range(stadium.MAX_CARDS)]

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
        now = time.monotonic()
        shown, overflow = stadium.strip(self.view.wm.stadium(now))
        dpg.set_value(self.strip_title, f"Stadium - {len(shown) + overflow} in battle" if shown else "Stadium - no battles")
        for i, slot in enumerate(self.slots):
            if i < len(shown):
                aid, card = shown[i]
                slot.show(aid, card, model.frame(aid), now)
            else:
                slot.hide()
        dpg.set_value(self.more, f"+{overflow} more battles not shown" if overflow else "")
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
