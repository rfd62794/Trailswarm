"""Editable layout overrides: source-controlled defaults + a user file. Never touches ROM data (pure JSON in/out).

{"interiors": {"<map id>": {"dx": cells, "dy": cells, "scale": float, "hidden": bool, "mode": "inplace"|"inplace_full"|"inset"}},
 "bands": {"x": {"<logical column>": extra cells}, "y": {"<logical row>": extra cells}}}
Two layers: ``defaults`` (atlas/layout_defaults.json) and ``user`` (runs/atlas/layout_overrides.json). The user layer wins per
interior key; bands add up. Edits and ``save`` touch the user layer only. Bad entries are dropped on load with a log line.
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from pokeagent.atlas.world import Xform

log = logging.getLogger(__name__)
DEFAULTS = Path(__file__).with_name("layout_defaults.json")
USER = Path("runs") / "atlas" / "layout_overrides.json"
MIN_SCALE, MAX_SCALE = 0.25, 2.0
MAX_BAND, MAX_SHIFT = 16, 500.0
MODES = ("inplace", "inplace_full", "inset")


def _num(v, lo: float, hi: float) -> float:
    f = float(v)
    if isinstance(v, bool) or not math.isfinite(f):
        raise ValueError(v)
    return min(hi, max(lo, f))


def _clean_interior(o: dict) -> dict:
    """The valid keys of one interior's override; raises ValueError when nothing usable is in it."""
    out: dict = {}
    for k, v in o.items():
        try:
            if k in ("dx", "dy"):
                out[k] = _num(v, -MAX_SHIFT, MAX_SHIFT)
            elif k == "scale":
                out[k] = _num(v, MIN_SCALE, MAX_SCALE)
            elif k == "hidden":
                out[k] = bool(v)
            elif k == "mode" and v in MODES:
                out[k] = v
            else:
                raise ValueError(k)
        except (ValueError, TypeError):
            log.warning("layout overrides: dropped bad value %r=%r", k, v)
    return out


def _read_layer(path: Path | None) -> dict:
    """One layer, validated: {"interiors": {int: {...}}, "bands": {"x": {int: int}, "y": {...}}}."""
    layer: dict = {"interiors": {}, "bands": {"x": {}, "y": {}}}
    if path is None:
        return layer
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        d = d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return layer
    for k, v in (d.get("interiors") or {}).items():
        try:
            clean = _clean_interior(v)
            if clean:
                layer["interiors"][int(k)] = clean
        except (ValueError, TypeError, AttributeError):
            log.warning("layout overrides: dropped bad interior entry %r", k)
    for ax in ("x", "y"):
        for k, v in ((d.get("bands") or {}).get(ax) or {}).items():
            try:
                layer["bands"][ax][int(k)] = int(_num(v, 0, MAX_BAND))
            except (ValueError, TypeError):
                log.warning("layout overrides: dropped bad %s band %r=%r", ax, k, v)
    return layer


@dataclass
class Overrides:
    defaults: dict = field(default_factory=lambda: {"interiors": {}, "bands": {"x": {}, "y": {}}})
    user: dict = field(default_factory=lambda: {"interiors": {}, "bands": {"x": {}, "y": {}}})
    path: Path | None = None

    @classmethod
    def load(cls, user: Path | None = USER, defaults: Path | None = DEFAULTS) -> "Overrides":
        return cls(_read_layer(defaults), _read_layer(user), user)

    # -- merged read view -------------------------------------------------------------
    @property
    def interiors(self) -> dict[int, dict]:
        out = {m: dict(o) for m, o in self.defaults["interiors"].items()}
        for m, o in self.user["interiors"].items():
            out.setdefault(m, {}).update(o)
        return out

    @property
    def bands(self) -> dict[str, dict[int, int]]:
        out = {ax: dict(self.defaults["bands"][ax]) for ax in ("x", "y")}
        for ax in ("x", "y"):
            for k, v in self.user["bands"][ax].items():
                out[ax][k] = out[ax].get(k, 0) + v
        return out

    @property
    def hidden(self) -> frozenset[int]:
        return frozenset(m for m, o in self.interiors.items() if o.get("hidden"))

    @property
    def inset_only(self) -> frozenset[int]:
        return frozenset(m for m, o in self.interiors.items() if o.get("mode") == "inset")

    def mode_of(self, m: int) -> str | None:
        return self.interiors.get(m, {}).get("mode")

    # -- edits (user layer) -----------------------------------------------------------
    def _u(self, m: int) -> dict:
        return self.user["interiors"].setdefault(m, {})

    def set(self, m: int, **kw) -> None:
        self._u(m).update(_clean_interior(kw))

    def move(self, m: int, ddx: float, ddy: float) -> None:
        o = self._u(m)
        cur = self.interiors.get(m, {})
        o["dx"] = round(_num(cur.get("dx", 0.0) + ddx, -MAX_SHIFT, MAX_SHIFT), 3)
        o["dy"] = round(_num(cur.get("dy", 0.0) + ddy, -MAX_SHIFT, MAX_SHIFT), 3)

    def rescale(self, m: int, base: float, factor: float) -> None:
        cur = self.interiors.get(m, {}).get("scale", base)
        self._u(m)["scale"] = round(min(MAX_SCALE, max(MIN_SCALE, cur * factor)), 3)

    def reset(self, m: int | None = None) -> None:
        if m is None:
            self.user["interiors"].clear()
        else:
            self.user["interiors"].pop(m, None)

    def save(self, path: Path | None = None) -> None:
        """Write the user layer only, atomically (temp file + replace)."""
        target = Path(path or self.path or USER)
        target.parent.mkdir(parents=True, exist_ok=True)
        body = {"interiors": {str(k): v for k, v in sorted(self.user["interiors"].items()) if v},
                "bands": {ax: {str(k): v for k, v in b.items()} for ax, b in self.user["bands"].items()}}
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(body, indent=1), encoding="utf-8")
        os.replace(tmp, target)

    def adjust(self, m: int, t: Xform, entry: tuple[int, int]) -> Xform:
        """Apply this interior's scale (about its entry tile, so the door stays put) and offset to a computed transform."""
        o = self.interiors.get(m)
        if not o:
            return t
        s = float(o.get("scale", t.s))
        return Xform(t.ox + entry[0] * (t.s - s) + o.get("dx", 0.0), t.oy + entry[1] * (t.s - s) + o.get("dy", 0.0), s)
