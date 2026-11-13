"""A counting stand-in for ``dearpygui.dearpygui`` (no context, no display) for headless tests: every call is accepted, textures are tracked."""
from __future__ import annotations

import itertools


class _Ctx(int):
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class StubDpg:
    mvMouseButton_Left = 0

    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.live: dict[int, int] = {}      # texture tag -> pixel-float count
        self.created = 0
        self.deleted = 0
        self.items: set[int] = set()

    def _new(self) -> _Ctx:
        i = _Ctx(next(self._ids))
        self.items.add(int(i))
        return i

    def _texture(self, w, h, data, **_kw):
        i = self._new()
        self.live[int(i)] = w * h * 4
        self.created += 1
        return i

    add_static_texture = add_raw_texture = _texture

    def delete_item(self, item, children_only=False, **_kw):
        if children_only:
            return
        if item in self.live:
            del self.live[item]
            self.deleted += 1
        self.items.discard(item)

    def does_item_exist(self, item):
        return item in self.items

    def __getattr__(self, name):
        if name.startswith("add_") or name in ("group", "handler_registry", "child_window", "window", "drawlist", "table"):
            return lambda *a, **k: self._new()
        if name.startswith(("draw_", "configure_", "set_", "show_", "hide_")):
            return lambda *a, **k: None
        raise AttributeError(name)

    def is_item_hovered(self, *_a):
        return False
