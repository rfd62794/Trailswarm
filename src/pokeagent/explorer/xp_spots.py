"""The persistent training-spot ledger: rolling XP rates by (map, member level band), shared across runs.

Lives in ``runs/xp_spots.json`` next to ``grind_points.json``/``grind_atlas.json`` (the caller resolves the path from the
run's runs dir; there is no CWD-relative default to write to). Concurrent agents share the file: ``save`` re-reads it and
merges cell by cell (counts summed, newest timestamp kept) before an atomic replace. Pure bookkeeping, measurement only:
nothing here picks a spot. Bounded to ``MAX_SPOTS`` cells (the least-measured, oldest are evicted first); every cell
is an exponential moving average, so old data fades. Reads/writes never raise.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pokeagent.fsutil import atomic_write_text

LEDGER_PATH = Path("runs/xp_spots.json")   # read-only default for reports; writers pass an explicit path
FILE = "xp_spots.json"
SCHEMA = 1
BAND_WIDTH = 5          # levels per band: L5-9, L10-14, ...
MAX_SPOTS = 200         # bound on (map, band) cells
ALPHA = 0.3             # EMA weight of the newest window
N_CAP = 1000            # window count stops growing here (the file stays small and numeric)


def band_of(level: int) -> str:
    lo = (max(0, int(level)) // BAND_WIDTH) * BAND_WIDTH
    return f"{lo}-{lo + BAND_WIDTH - 1}"


def _cell(map_id: int, band: str) -> str:
    return f"{int(map_id)}|{band}"


class XpSpots:
    def __init__(self, spots: dict | None = None, *, path: Path | str) -> None:
        self.spots: dict[str, dict] = spots or {}
        self.path = Path(path)
        self._base: dict[str, int] = {}     # per cell: window count already merged with the file (the rest is ours to add)

    @staticmethod
    def _read(path: Path | str) -> dict[str, dict]:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            return {k: v for k, v in (doc.get("spots") or {}).items()
                    if isinstance(v, dict) and isinstance(v.get("xp_per_1k"), (int, float))}
        except (OSError, ValueError, AttributeError):
            return {}

    @classmethod
    def load(cls, path: Path | str) -> "XpSpots":
        inst = cls(cls._read(path), path=path)
        inst._base = {k: int(v.get("n", 0)) for k, v in inst.spots.items()}
        return inst

    def record(self, map_id: int, level: int, xp_per_1k: float, battles_per_1k: float, xp_per_battle: float) -> dict:
        """Fold one measured window (one member on one map) into its (map, band) cell."""
        key = _cell(map_id, band_of(level))
        c = self.spots.get(key)
        vals = {"xp_per_1k": float(xp_per_1k), "battles_per_1k": float(battles_per_1k), "xp_per_battle": float(xp_per_battle)}
        if c is None:
            c = {**{k: round(v, 3) for k, v in vals.items()}, "n": 1}
        else:
            for k, v in vals.items():
                c[k] = round(c[k] * (1 - ALPHA) + v * ALPHA, 3) if k in c else round(v, 3)
            c["n"] = min(N_CAP, int(c.get("n", 0)) + 1)
        c["updated"] = int(time.time())
        self.spots[key] = c
        self._bound()
        return c

    def _bound(self) -> None:
        if len(self.spots) <= MAX_SPOTS:
            return
        order = sorted(self.spots, key=lambda k: (self.spots[k].get("n", 0), self.spots[k].get("updated", 0)))
        for k in order[:len(self.spots) - MAX_SPOTS]:
            del self.spots[k]

    def best_by_band(self, min_n: int = 1) -> dict[str, dict]:
        """{band: {"map": id, "xp_per_1k": ..., "n": ...}}: the highest-rate measured spot per level band."""
        best: dict[str, dict] = {}
        for key, c in self.spots.items():
            try:
                m, band = key.split("|", 1)
                if c.get("n", 0) >= min_n and c["xp_per_1k"] > best.get(band, {}).get("xp_per_1k", -1):
                    best[band] = {"map": int(m), "xp_per_1k": c["xp_per_1k"], "n": c.get("n", 0)}
            except (ValueError, KeyError):
                continue
        return best

    def _merge(self, disk: dict[str, dict]) -> None:
        """Fold what other writers put in the file into our cells: our new windows (n beyond ``_base``) are added to the
        file's count and blended into its rates by window count; the newest ``updated`` wins; cells only they hold are kept."""
        merged = {k: dict(v) for k, v in disk.items()}
        for k, mine in self.spots.items():
            d = merged.get(k)
            delta = max(0, int(mine.get("n", 0)) - self._base.get(k, 0))
            if d is None:
                merged[k] = dict(mine)
            elif delta:
                dn = max(1, int(d.get("n", 0)))
                for f in ("xp_per_1k", "battles_per_1k", "xp_per_battle"):
                    if f in mine:
                        d[f] = round((d.get(f, mine[f]) * dn + mine[f] * delta) / (dn + delta), 3)
                d["n"] = min(N_CAP, int(d.get("n", 0)) + delta)
                d["updated"] = max(int(d.get("updated", 0)), int(mine.get("updated", 0)))
        self.spots = merged
        self._bound()
        self._base = {k: int(v.get("n", 0)) for k, v in self.spots.items()}

    def save(self) -> bool:
        """Merge with the file's current content, then write it atomically (temp file + os.replace)."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._merge(self._read(self.path))
            atomic_write_text(self.path, json.dumps({"schema": SCHEMA, "spots": self.spots}, sort_keys=True))
            return True
        except OSError:
            return False
