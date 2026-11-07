"""The World side panel's health block: a clickable badge plus an expandable detail section.

The badge counts non-ok agents and invariant errors (coloured by the worst state). Clicking it
expands the ``HEALTH_PANEL`` section: one line per non-ok agent, the invariant top-3 ERRORs, and
recent anomalies. Clicking an anomaly line (or an anomaly card's header) loads its ``.png`` once
into ``viewer_tex`` and shows it in a fixed-size slot with the ``.state`` path and cause below.
"""
from __future__ import annotations

from pathlib import Path

import dearpygui.dearpygui as dpg

from pokeagent.viewer import health as hm
from pokeagent.viewer.health import HealthStore, AnomalyRef
from pokeagent.viewer.ui import tags, theme
from pokeagent.viewer.ui_scale import px

IMG_W, IMG_H = 320, 288       # untuned first values: fixed anomaly image slot (2x a GB frame)
MAX_ANOMALY_LINES = 5         # untuned first value: recent anomalies listed in the panel


class HealthPanel:
    def __init__(self, parent=None) -> None:
        kw = {} if parent is None else {"parent": parent}
        self.badge = dpg.add_selectable(label="Health: -", callback=lambda s, a, u: self.toggle(), **kw)
        self.panel = dpg.add_group(tag=tags.HEALTH_PANEL, show=False, **kw)
        with dpg.group(parent=self.panel):
            self.lines = dpg.add_group()
            self.detail_head = dpg.add_text("")
            self._ph_tex = dpg.add_raw_texture(1, 1, [0.0] * 4, parent=tags.VIEWER_TEX)
            self.detail_img = dpg.add_image(self._ph_tex, width=px(IMG_W), height=px(IMG_H), show=False)
            self.detail_state = dpg.add_input_text(label="state", readonly=True, width=px(330))
            self.detail_cause = dpg.add_input_text(label="cause", readonly=True, width=px(330))
        self._open = False
        self._store: HealthStore | None = None
        self._entries: dict = {}
        self._sig = None
        self._tex: tuple[str, int] | None = None
        self._badge_state = hm.OK

    def bind(self, store: HealthStore, entries: dict) -> None:
        self._store, self._entries = store, entries

    def toggle(self) -> None:
        self._open = not self._open
        dpg.configure_item(self.panel, show=self._open)

    def _started(self, agent_id: str) -> float | None:
        e = self._entries.get(agent_id) or {}
        try:
            return float(e.get("started")) if e.get("started") is not None else None
        except (TypeError, ValueError):
            return None

    def update(self, agent_ids: list[str]) -> None:
        store = self._store
        if store is None:
            return
        hs = [(aid, store.health(aid, self._started(aid))) for aid in agent_ids]
        counts: dict[str, int] = {}
        for _, h in hs:
            counts[h.state] = counts.get(h.state, 0) + 1
        br = store.breaks()
        dpg.configure_item(self.badge, label=hm.badge_text(counts, br))
        worst = hm.worst_state([h.state for _, h in hs])
        if worst != self._badge_state:
            self._badge_state = worst
            dpg.bind_item_theme(self.badge, theme.health_theme(worst) or 0)
        if self._open:
            sig = (tuple((aid, h.state, h.reason) for aid, h in hs if h.state != hm.OK),
                   repr(br), tuple(a.run for a in store.anomalies(MAX_ANOMALY_LINES)))
            if sig != self._sig:
                self._sig = sig
                self._rebuild(hs, br)

    def _rebuild(self, hs, br) -> None:
        store = self._store
        dpg.delete_item(self.lines, children_only=True)
        for aid, h in hs:
            if h.state == hm.OK:
                continue
            syn = " (synthetic)" if store.provenance(h.dossier_run) == "synthetic" else ""
            dpg.add_text(f"{aid}: {h.state} - {h.reason}{syn}", parent=self.lines, wrap=px(340))
        for m in (br or {}).get("top") or []:
            dpg.add_text(f"invariant: {m}", parent=self.lines, wrap=px(340))
        for ref in store.anomalies(MAX_ANOMALY_LINES):
            syn = " (synthetic)" if ref.provenance == "synthetic" else ""
            dpg.add_selectable(label=f"{ref.run} step {ref.step} {ref.type}{syn}", parent=self.lines,
                               callback=lambda s, a, u, r=ref: self.show_anomaly(r))

    def _set_detail_image(self, path: Path) -> None:
        """Load ``path`` once into viewer_tex and point the fixed image slot at it; drops the old texture."""
        key = str(path)
        if self._tex is not None and self._tex[0] == key:
            return
        w, h, _c, data = dpg.load_image(key)
        tag = dpg.add_static_texture(w, h, data, parent=tags.VIEWER_TEX)
        if self._tex is not None and dpg.does_item_exist(self._tex[1]):
            dpg.delete_item(self._tex[1])
        self._tex = (key, tag)
        dpg.configure_item(self.detail_img, texture_tag=tag)

    def show_anomaly(self, ref: AnomalyRef) -> None:
        """Open the anomaly in the side panel: image in the slot, .state path + cause as selectable text."""
        if not self._open:
            self.toggle()
        head = f"{ref.run} step {ref.step} {ref.type}"
        ok = False
        if ref.png is not None and Path(ref.png).exists():
            try:
                self._set_detail_image(Path(ref.png))
                ok = True
            except Exception:
                ok = False
        dpg.configure_item(self.detail_img, show=ok)
        dpg.set_value(self.detail_head, head if ok else f"{head} - file missing")
        dpg.set_value(self.detail_state, str(ref.state) if ref.state else "")
        dpg.set_value(self.detail_cause, ref.cause_hint or "")
