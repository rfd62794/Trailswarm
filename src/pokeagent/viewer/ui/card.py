"""One agent card: header + Render | Sees textures over Thinking/Progress text textures.

Every pixel the card shows comes from viewer.panels (pure functions); this module only owns
Dear PyGui items and texture bookkeeping. ``big=True`` lays the same card out for focus view.
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable

import dearpygui.dearpygui as dpg

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.panels import BG, DIM, PANE, TEXT, driver_color, plain, span
from pokeagent.viewer.panels import render as pres
from pokeagent.viewer.panels import registry
from pokeagent.viewer.panels.textimg import lines_texture

_PAD = 5
_HEADER_H = 15


class _Tex:
    """A named raw texture: created lazily, updated only when its pixels change."""

    def __init__(self, width: int, height: int) -> None:
        self.w, self.h = width, height
        self.tag: str | int | None = None
        self._key: tuple | None = None

    def _ensure(self, data: list[float], w: int, h: int) -> str | int:
        if self.tag is None or self.w != w or self.h != h:
            if self.tag is not None:
                dpg.delete_item(self.tag)
            self.tag = dpg.add_raw_texture(w, h, data, parent="viewer_tex")
            self.w, self.h, self._key = w, h, None
        return self.tag

    def set(self, data: list[float], w: int, h: int, key: tuple) -> str | int:
        """Upload ``data`` when ``key`` (content+size signature) differs from the last upload."""
        tag = self._ensure(data, w, h)
        if self._key != key:
            dpg.set_value(tag, data)
            self._key = key
        return tag

    def delete(self) -> None:
        if self.tag is not None:
            dpg.delete_item(self.tag)
            self.tag = None


def _frame_tex(rgb: bytes, w: int, h: int, pw: int, ph: int, dim: bool) -> tuple[list[float], int, int, tuple]:
    px = pres.frame_rgba(rgb, w, h, pw, ph)
    if dim:  # lost/stopped: darken the last frame instead of dropping it
        px = [v * 0.4 for v in px]
    key = (w, h, dim, hashlib.blake2b(rgb, digest_size=8).digest())
    return px, pw, ph, key


def _text_tex(lines, pw: int, ph: int) -> tuple[list[float], int, int, tuple]:
    data, tw, th = lines_texture(lines, pw, ph)
    key = (tw, th, hashlib.md5(repr(lines).encode()).digest()[:8])
    return data, tw, th, key


def _hex_rgba(color: str) -> list[float]:
    c = color.lstrip("#")
    return [int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)] + [1.0]


def _hstack(left: list[float] | None, lw: int, lh: int,
            right: list[float], rw: int, rh: int, gap: int,
            fill: list[float]) -> tuple[list[float], int, int]:
    """Render | Sees side by side in one texture (DPG groups cannot nest in cells)."""
    w, h = lw + gap + rw, lh
    out = [c for _ in range(w * h) for c in fill]
    for y in range(h):
        base = y * w * 4
        if left is not None:
            out[base:base + lw * 4] = left[y * lw * 4:(y + 1) * lw * 4]
        ro = base + (lw + gap) * 4
        out[ro:ro + rw * 4] = right[y * rw * 4:(y + 1) * rw * 4]
    return out, w, h


class CardView:
    """Textures + item tags for one card. ``update`` is called every UI frame; it only
    re-uploads pixels when the snapshot/frame content actually changed."""

    def __init__(self, parent, agent_id: str, card_w: int, card_h: int, on_focus: Callable[[str], None],
                 on_select: Callable[[str], None], big: bool = False) -> None:
        self.agent_id = agent_id
        self.big = big
        self._on_focus, self._on_select = on_focus, on_select
        self.card_w, self.card_h = card_w, card_h
        self._sizes: dict[str, tuple[int, int]] = {}
        self._tex: dict[str, _Tex] = {}
        self._img: dict[str, str | int] = {}
        self._parent = parent  # items are leaves: no container can nest inside cells/child_windows
        self._last_click = 0.0
        self._build()

    def _clicked(self) -> None:
        """Click = select; two clicks <0.4 s apart = focus (DPG item double-click handlers are flaky)."""
        now = time.monotonic()
        if now - self._last_click < 0.4:
            self._last_click = 0.0
            self._on_focus(self.agent_id)
        else:
            self._last_click = now
            self._on_select(self.agent_id)

    # -- layout -----------------------------------------------------------------
    def _geom(self) -> dict[str, tuple[int, int]]:
        "-> panel name -> (w, h) in display px."""
        w, h = self.card_w, self.card_h
        iw = w - 2 * _PAD
        pw = (iw - _PAD) // 2 if not self.big else iw * 2 // 5
        # two 10:9 frames wide -> frame height follows panel width
        fh = int(pw * 9 / 10)
        avail = h - 2 * _PAD - _HEADER_H
        top = min(fh, max(24, int(avail * 0.62)))
        text = max(16, avail - top - _PAD)
        g = {
            "header": (iw, _HEADER_H),
            "top": (iw, top),  # render | sees composited into one texture
            "thinking": (iw, int(text * 0.55)),
            "progress": (iw, text - int(text * 0.55) - 2),
        }
        self._split = (pw, iw - pw - _PAD)  # (render_w, sees_w) inside "top"
        if self.big:
            g["focus"] = (iw, max(30, h - _HEADER_H - top - int(text * 0.55) - text - 6 * _PAD))
        return g

    def _panel_lines(self, name: str, snap: AgentSnapshot | None, hold_s: float | None) -> list:
        if snap is None:
            return [plain("(waiting for snapshot)", DIM)]
        if name == "header":
            return self._header(snap)
        if name == "thinking":
            return registry.lines_for(name, snap, hold_s=hold_s)
        return registry.lines_for(name, snap)

    def _header(self, snap: AgentSnapshot) -> list:
        head = f"{snap.agent_id} · {snap.kind or '?'}"
        seg = f" · {snap.segment.id} {snap.segment.name}".rstrip() if snap.segment.id else ""
        st = f" · step {snap.step}"
        line = [span(head, driver_color(snap.thinking.driver or snap.kind)), span(seg + st, DIM)]
        if snap.state != "running":
            line.append(span(f"  [{snap.state}{': ' + snap.stop_reason if snap.stop_reason else ''}]", DIM))
        return [line]

    # -- build ------------------------------------------------------------------
    def _build(self) -> None:
        g = self._geom()
        self._sizes = dict(g)
        p = self._parent
        self._img["header"] = self._place("header", g["header"])
        self._img["top"] = self._place("top", g["top"])
        self._img["thinking"] = self._place("thinking", g["thinking"])
        self._img["progress"] = self._place("progress", g["progress"])
        if self.big:
            self._img["focus"] = self._place("focus", g["focus"])

    def _place(self, name: str, size: tuple[int, int]):
        tex = self._tex.setdefault(name, _Tex(*size))
        if tex.tag is None:  # 1x1 placeholder until the first update uploads real pixels
            tex.tag = dpg.add_raw_texture(1, 1, [0.0] * 4, parent="viewer_tex")
        img = dpg.add_image_button(tex.tag, parent=self._parent, width=size[0], height=size[1],
                                   background_color=(0, 0, 0, 0),
                                   callback=lambda s, a, u: self._clicked())
        return img

    # -- update -----------------------------------------------------------------
    def update(self, snap: AgentSnapshot | None, frame, staleness: str, hold_s: float | None = None) -> None:
        g = self._sizes
        dim = staleness != "live" or (snap is not None and snap.state in ("stopped", "done"))
        # top strip: render frame (left) | sees text (right) in one texture, at 2x
        rw_, sw_ = self._split
        _, th_ = g["top"]
        ss = 2  # textimg supersample; frame is rasterized to match
        left = lkey = None
        if frame is not None:
            rgb, w, h = frame
            px, pw_, ph_, lkey = _frame_tex(rgb, w, h, rw_ * ss, th_ * ss, dim)
            if (pw_, ph_) == (rw_ * ss, th_ * ss):
                left = px
            else:  # unexpected raster size: skip rather than misalign
                lkey = None
        sees_lines = registry.lines_for("sees", snap) if snap is not None else [plain("(waiting for snapshot)", DIM)]
        rpx, rtw, rth, rkey = _text_tex(sees_lines, sw_, th_)
        data, tw2, th2 = _hstack(left, rw_ * ss, rth, rpx, rtw, rth, _PAD * ss, _hex_rgba(PANE))
        tag = self._tex["top"].set(data, tw2, th2, ("top", lkey, rkey))
        dpg.configure_item(self._img["top"], texture_tag=tag)
        # text panels
        for name in ("header", "thinking", "progress", "focus"):
            if name not in self._img:
                continue
            lines = self._panel_lines(name, snap, hold_s)
            pw, ph = g[name]
            data, tw, th, key = _text_tex(lines, pw, ph)
            tag = self._tex[name].set(data, tw, th, key)
            dpg.configure_item(self._img[name], texture_tag=tag)

    def delete(self) -> None:
        for tag in self._img.values():
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        self._img.clear()
        for tex in self._tex.values():
            tex.delete()
        self._tex.clear()

    def resize(self, card_w: int, card_h: int) -> None:
        if (card_w, card_h) != (self.card_w, self.card_h):
            self.card_w, self.card_h = card_w, card_h
            self.delete()
            self._build()
