"""Editable layout overrides: source-controlled defaults + a user file. Never touches ROM data (pure JSON in/out).

{"interiors": {"<map id>": {"dx": cells, "dy": cells, "scale": float, "hidden": bool, "mode": "inplace"|"inplace_full"|"inset"}},
 "bands": {"x": {"<logical column>": extra cells}, "y": {"<logical row>": extra cells}}}
The user file (runs/atlas/layout_overrides.json) wins per interior key over atlas/layout_defaults.json; bands add up.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pokeagent.atlas.world import Xform

DEFAULTS = Path(__file__).with_name("layout_defaults.json")
USER = Path("runs") / "atlas" / "layout_overrides.json"
MIN_SCALE, MAX_SCALE = 0.25, 2.0


def _read(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


@dataclass
class Overrides:
    interiors: dict[int, dict] = field(default_factory=dict)
    bands: dict[str, dict[int, int]] = field(default_factory=lambda: {"x": {}, "y": {}})

    @classmethod
    def load(cls, user: Path | None = USER, defaults: Path | None = DEFAULTS) -> "Overrides":
        out = cls()
        for path in (defaults, user):
            d = _read(path) if path else {}
            for k, v in (d.get("interiors") or {}).items():
                try:
                    out.interiors.setdefault(int(k), {}).update(v)
                except (ValueError, TypeError, AttributeError):
                    continue
            for ax in ("x", "y"):
                for k, v in ((d.get("bands") or {}).get(ax) or {}).items():
                    try:
                        out.bands[ax][int(k)] = out.bands[ax].get(int(k), 0) + int(v)
                    except (ValueError, TypeError):
                        continue
        return out

    def save(self, user: Path = USER) -> None:
        """Write the user's own file (defaults stay in source control)."""
        user.parent.mkdir(parents=True, exist_ok=True)
        body = {"interiors": {str(k): v for k, v in sorted(self.interiors.items()) if v},
                "bands": {ax: {str(k): v for k, v in b.items()} for ax, b in self.bands.items()}}
        user.write_text(json.dumps(body, indent=1), encoding="utf-8")

    def set(self, m: int, **kw) -> None:
        self.interiors.setdefault(m, {}).update(kw)

    def move(self, m: int, ddx: float, ddy: float) -> None:
        o = self.interiors.setdefault(m, {})
        o["dx"], o["dy"] = round(o.get("dx", 0.0) + ddx, 3), round(o.get("dy", 0.0) + ddy, 3)

    def rescale(self, m: int, base: float, factor: float) -> None:
        o = self.interiors.setdefault(m, {})
        o["scale"] = round(min(MAX_SCALE, max(MIN_SCALE, o.get("scale", base) * factor)), 3)

    def reset(self, m: int | None = None) -> None:
        if m is None:
            self.interiors.clear()
        else:
            self.interiors.pop(m, None)

    @property
    def hidden(self) -> frozenset[int]:
        return frozenset(m for m, o in self.interiors.items() if o.get("hidden"))

    @property
    def inset_only(self) -> frozenset[int]:
        return frozenset(m for m, o in self.interiors.items() if o.get("mode") == "inset")

    def mode_of(self, m: int) -> str | None:
        return self.interiors.get(m, {}).get("mode")

    def adjust(self, m: int, t: Xform, entry: tuple[int, int]) -> Xform:
        """Apply this interior's scale (about its entry tile, so the door stays put) and offset to a computed transform."""
        o = self.interiors.get(m)
        if not o:
            return t
        s = float(o.get("scale", t.s))
        return Xform(t.ox + entry[0] * (t.s - s) + o.get("dx", 0.0), t.oy + entry[1] * (t.s - s) + o.get("dy", 0.0), s)
