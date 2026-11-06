"""In-place interiors: which are shown, in what z-order, and the layout that maps agent coords to them (pure).

Modes: ``inset`` (the grid below the world), ``inplace`` (every interior painted at its building, scaled to fit),
``inplace_full`` (same at full size), ``auto`` (fit, but only the interior hovered / selected / holding an agent, or all of them
once zoomed in past AUTO_ZOOM). An interior that is not shown pins its agents and trails to its door tile with a badge.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from pokeagent.atlas.anchor import Anchor, anchor_interiors
from pokeagent.atlas.fit import build_xforms, walk_cells
from pokeagent.atlas.overrides import Overrides
from pokeagent.atlas.rom_maps import MapHeader, map_name
from pokeagent.atlas.world import WorldLayout, Xform

MODES = ("auto", "inplace", "inplace_full", "stretch", "inset")
LABELS = {"auto": "auto", "inplace": "in place (fit)", "inplace_full": "in place (full size)",
          "stretch": "in place (stretch world)", "inset": "inset"}
DEFAULT_MODE = "inplace"       # rooms in place (fit) unless the user picked otherwise
AUTO_ZOOM = 0.75               # screen px per world px at which auto shows every interior


@dataclass
class Plan:
    anchors: dict[int, Anchor]
    fit: dict[int, Xform]
    full: dict[int, Xform]
    hidden: frozenset[int] = frozenset()

    def xf(self, mode: str) -> dict[int, Xform]:
        return self.full if mode == "inplace_full" else self.fit

    def shift(self, m: int, dx: float, dy: float) -> None:
        """Move interior ``m`` and the floors hanging off it by (dx, dy) cells in place (a live drag; no replanning)."""
        for k in self.anchors:
            if m in chain(self.anchors, k):
                for d in (self.fit, self.full):
                    if k in d:
                        t = d[k]
                        d[k] = Xform(t.ox + dx, t.oy + dy, t.s)


def usable_anchors(headers: dict[int, MapHeader], layout: WorldLayout, model: dict | None = None,
                   overrides: Overrides | None = None) -> dict[int, Anchor]:
    """Anchors minus the interiors (and the floors hanging off them) the user keeps in the inset grid."""
    anchors = anchor_interiors(headers, layout, model)
    if overrides is not None and overrides.inset_only:
        anchors = {m: a for m, a in anchors.items() if not set(chain(anchors, m)) & overrides.inset_only}
    return anchors


def plan_interiors(rom: bytes, headers: dict[int, MapHeader], layout: WorldLayout, model: dict | None = None,
                   walk_cache: dict | None = None, overrides: Overrides | None = None) -> Plan:
    cache = walk_cache if walk_cache is not None else {}

    def walk(m: int):
        if m not in cache:
            cache[m] = walk_cells(rom, headers[m]) if m in headers else None
        return cache[m]

    ov = overrides
    anchors = usable_anchors(headers, layout, model, ov)
    adj = (lambda m, t: ov.adjust(m, t, anchors[m].entry)) if ov is not None else None
    fit, full = build_xforms(anchors, layout, walk, True, adj), build_xforms(anchors, layout, walk, False, adj)
    for m in (ov.interiors if ov is not None else ()):          # a per-interior mode beats the global fit/full choice
        if ov.mode_of(m) == "inplace_full" and m in full:
            fit[m] = full[m]
        elif ov.mode_of(m) == "inplace" and m in fit:
            full[m] = fit[m]
    return Plan(anchors, fit, full, ov.hidden if ov is not None else frozenset())


def chain(anchors: dict[int, Anchor], m: int) -> list[int]:
    """``m`` and its anchored ancestors (a floor needs the floors it hangs off to be shown)."""
    out = []
    while m in anchors and m not in out:
        out.append(m)
        m = anchors[m].parent
    return out


def shown_set(mode: str, anchors: dict[int, Anchor], zoom: float, hover: int | None = None, selected: int | None = None,
              inside: tuple[int, ...] = (), hidden: frozenset[int] = frozenset()) -> set[int]:
    if mode == "inset":
        return set()
    if mode in ("inplace", "inplace_full", "stretch") or zoom >= AUTO_ZOOM:
        return set(anchors) - hidden
    return {c for m in (hover, selected, *inside) if m is not None for c in chain(anchors, m)} - hidden


def z_order(anchors: dict[int, Anchor], shown: set[int], top: int | None = None) -> list[int]:
    """Draw order, first = bottom: deeper floors above shallower ones, ``top`` (hovered / selected) above everything."""
    order = sorted((m for m in shown if m in anchors), key=lambda m: (anchors[m].depth, m))
    if top in order:
        order.remove(top)
        order.append(top)
    return order


def _door(layout: WorldLayout, anchors: dict[int, Anchor], xf: dict[int, Xform], shown: set[int], m: int) -> tuple[int, int]:
    a = anchors[m]
    if a.parent not in anchors:
        p = layout.places[a.parent]
        if layout.warp is not None:
            wx, wy = layout.warp.cell(p.x + a.via[0], p.y + a.via[1])
            return round(wx), round(wy)
        return p.x + a.via[0], p.y + a.via[1]
    if a.parent in shown:
        t = xf[a.parent]
        return round(t.ox + a.via[0] * t.s), round(t.oy + a.via[1] * t.s)
    return _door(layout, anchors, xf, shown, a.parent)


def view_layout(layout: WorldLayout, anchors: dict[int, Anchor], xf: dict[int, Xform], shown: set[int],
                top: int | None = None) -> WorldLayout:
    """``layout`` with shown interiors moved to their transform and the others' agents pinned to the building's door."""
    order = z_order(anchors, shown, top)
    pins = {m: _door(layout, anchors, xf, shown, m) for m in anchors if m not in shown}
    return replace(layout, pins=pins, xf={m: xf[m] for m in order}, z={m: i for i, m in enumerate(order)})


def hit(layout: WorldLayout, anchors: dict[int, Anchor], xf: dict[int, Xform], cx: float, cy: float,
        top: int | None = None) -> int | None:
    """Topmost interior (even one not shown) whose painted rectangle contains world cell (cx, cy)."""
    for m in reversed(z_order(anchors, set(xf), top)):
        t, p = xf[m], layout.places[m]
        if t.ox <= cx < t.ox + p.w * t.s and t.oy <= cy < t.oy + p.h * t.s:
            return m
    return None


def badge(layout: WorldLayout, m: int) -> str | None:
    return f"inside: {pretty(m)}" if m in layout.pins else None


def pretty(m: int) -> str:
    return map_name(m).replace("_", " ").title()


def legend(anchors: dict[int, Anchor], xf: dict[int, Xform], m: int) -> list[str]:
    """Tooltip / legend lines for an interior: name, floor depth, what it hangs off, how it was placed, scale."""
    a = anchors.get(m)
    if a is None:
        return [f"{pretty(m)} (inset)"]
    floor = "ground floor" if a.depth == 1 else f"floor level {a.depth}"
    out = [f"{pretty(m)} - {floor}", f"via {pretty(a.parent)} at ({a.via[0]}, {a.via[1]}), {a.source} warp"]
    if m in xf and xf[m].s != 1.0:
        out.append(f"scaled to {int(xf[m].s * 100)}% to fit")
    return out


def locate_in(layout: WorldLayout, cx: float, cy: float) -> tuple[int, int, int] | None:
    """(map, cell x, cell y) of an in-place interior at world cell (cx, cy), topmost first; None when no interior is there."""
    for m in sorted(layout.xf, key=lambda k: layout.z.get(k, 0), reverse=True):
        t, p = layout.xf[m], layout.places[m]
        if t.ox <= cx < t.ox + p.w * t.s and t.oy <= cy < t.oy + p.h * t.s:
            return m, int((cx - t.ox) / t.s), int((cy - t.oy) / t.s)
    return None
