"""Grind points: a shared ledger of known-good level-grind spots, chosen by the team's level gap.

The atlas (grind/atlas.py) ranks every wild map by ROM math plus folded battle stats; nothing chose
from it. This module keeps one ``GrindPoint`` per map and ``choose`` picks the best point for the
trainee's level. The ledger file is ``runs/grind_points.json``; the swarm-shared copy lives in
``mem.data["grind_points"]`` (merged by tools/swarm_merge.py with the same ``merge_point`` rule).
Each measured episode is recorded by id (``run@start_step``) as [xp_per_min, blackouts, provenance]:
that is what makes ``merge`` both an episode-weighted mean and idempotent, and what lets a synthetic
episode never overwrite organic data.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pokeagent.grind import atlas
from pokeagent.grind.points_io import band_of, patch_of, points_of, species_of

log = logging.getLogger(__name__)

LEDGER_PATH = Path("runs/grind_points.json")
SCHEMA = 1
MIN_MEASURED = 2              # episodes before measured xp/min beats the prior in choose()
HOP_STEPS = 32                # steps a map crossing costs when only map ids are known
FAR_TRAVEL = 10_000           # "unreachable": dwarfs any real travel term
BAND_LO, BAND_HI = -2, 6      # default band around the top wild level
DEFAULT_BAND = (0, 100)       # no species data yet: any level may use the point
PROVENANCES = ("organic", "mixed", "synthetic", "unknown")


@dataclass
class GrindPoint:
    map_id: int
    name: str = ""
    patch: list = field(default_factory=list)            # [[x, y]] grass tiles (encounter-proven)
    species: list = field(default_factory=list)          # [[species, min_level, max_level]]
    level_band: tuple = DEFAULT_BAND                     # party levels this point is good for
    xp_per_min_measured: float | None = None
    xp_per_min_prior: float = 0.0
    n_measured: int = 0
    center_map: int | None = None                        # nearest Pokecenter map
    center_cost_frames: float = 0.0
    blackout_rate: float = atlas.PRIOR_BLACKOUT          # blackouts per episode (prior until measured)
    provenance: str = "organic"                          # worst provenance of the data behind the point
    updated: str = ""
    episodes: dict = field(default_factory=dict)         # {"run@step": [xp_per_min, blackouts, provenance]}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["patch"], d["species"] = [list(t) for t in self.patch], [list(t) for t in self.species]
        d["level_band"] = list(self.level_band)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "GrindPoint":
        p = cls(int(d["map_id"]))
        for k, f in (("name", str), ("xp_per_min_prior", float), ("n_measured", int),
                     ("center_cost_frames", float), ("blackout_rate", float), ("updated", str)):
            if d.get(k) is not None:
                setattr(p, k, f(d[k]))
        p.patch, p.species = [list(t) for t in d.get("patch") or []], [list(t) for t in d.get("species") or []]
        band = d.get("level_band") or DEFAULT_BAND
        p.level_band = (int(band[0]), int(band[1]))
        v = d.get("xp_per_min_measured")
        p.xp_per_min_measured = float(v) if v is not None else None
        p.center_map = int(d["center_map"]) if d.get("center_map") is not None else None
        p.provenance = d["provenance"] if d.get("provenance") in PROVENANCES else "organic"
        p.n_measured = int(d.get("n_measured") or len(d.get("episodes") or {}))
        p.episodes = {k: list(v) for k, v in (d.get("episodes") or {}).items() if isinstance(v, (list, tuple))}
        return p


def _recompute(p: GrindPoint) -> None:
    if not p.episodes:
        p.n_measured, p.xp_per_min_measured = 0, None
        return
    p.n_measured = len(p.episodes)
    p.xp_per_min_measured = sum(v[0] for v in p.episodes.values()) / p.n_measured
    p.blackout_rate = sum(v[1] for v in p.episodes.values()) / p.n_measured
    provs = {v[2] if len(v) > 2 else "unknown" for v in p.episodes.values()}
    p.provenance = provs.pop() if len(provs) == 1 else "mixed"


def episode_result(p: GrindPoint, xp_gained: float, steps: int, blackouts: int,
                   provenance: str = "organic", ep_id: str | None = None, now: str | None = None) -> GrindPoint:
    rate = xp_gained / (steps / atlas.STEPS_PER_MIN) if steps > 0 else 0.0  # fold one episode in by episode id
    prov = provenance if provenance in PROVENANCES else "unknown"
    p.episodes[ep_id or f"e{len(p.episodes) + 1}"] = [rate, blackouts, prov]
    _recompute(p)
    p.updated = now or time.strftime("%Y-%m-%dT%H:%M:%S")
    return p


def merge_point(d: dict | None, s: dict) -> dict:
    """Merge a serialized point dict ``s`` into ``d``: union of episode ids, each folded once (idempotent);
    a synthetic episode never lands on a point holding organic/mixed data; ``d`` None = take ``s``."""
    if not isinstance(s, dict) or "map_id" not in s:
        return d or {}
    if d is None:
        return GrindPoint.from_dict(s).to_dict()
    a, b = GrindPoint.from_dict(d), GrindPoint.from_dict(s)
    organic_d = a.provenance in ("organic", "mixed")
    for eid, v in b.episodes.items():
        if eid not in a.episodes and not (organic_d and len(v) > 2 and v[2] == "synthetic"):
            a.episodes[eid] = list(v)                      # organic data is never diluted by synthetic
    if a.episodes:
        _recompute(a)
    elif a.n_measured == 0 and b.n_measured > 0 and not b.episodes:
        # anonymous aggregate (no episode ids): seed from it only when dst has none of its own
        a.n_measured, a.xp_per_min_measured, a.blackout_rate = b.n_measured, b.xp_per_min_measured, b.blackout_rate
        if a.provenance == "unknown":
            a.provenance = b.provenance
    else:
        a.n_measured = max(a.n_measured, b.n_measured if not b.episodes else 0)
    a.xp_per_min_prior = max(a.xp_per_min_prior, b.xp_per_min_prior)
    a.patch = sorted({tuple(t) for t in a.patch} | {tuple(t) for t in b.patch})
    sp = {t[0]: list(t) for t in a.species}
    for t in b.species:
        cur = sp.get(t[0])
        sp[t[0]] = [t[0], min(cur[1], t[1]) if cur else t[1], max(cur[2], t[2]) if cur else t[2]]
    a.species = sorted(sp.values())
    if a.level_band == DEFAULT_BAND:
        a.level_band = b.level_band
    a.name, a.center_map = a.name or b.name, a.center_map if a.center_map is not None else b.center_map
    a.center_cost_frames = min((a.center_cost_frames, b.center_cost_frames), key=lambda c: c <= 0 and 1e18 or c)
    a.updated = max(a.updated, b.updated)
    return a.to_dict()


def _maps_of(mem) -> dict:
    data = getattr(mem, "data", mem) or {}
    return data.get("maps", data) if isinstance(data, dict) else {}


def travel_steps(maps: dict, current, map_id: int) -> float:
    """Steps from ``current`` (map id, (map,x,y) pos, or None) to ``map_id``: exact BFS count from a pos,
    a map-hop estimate from a bare map id, 0 from None."""
    if current is None:
        return 0.0
    if isinstance(current, (tuple, list)):
        if current[0] == map_id:
            return 0.0
        from pokeagent.explorer.world import WorldGraph
        p = WorldGraph(maps).path(tuple(current), lambda n: n[0] == map_id)
        return float(len(p)) if p else float(FAR_TRAVEL)
    if int(current) == int(map_id):
        return 0.0
    seen, q, hops = {int(current)}, deque([int(current)]), 0
    while q:                                                # map-level BFS over learned warp destinations
        for _ in range(len(q)):
            for dest in ((maps.get(str(q.popleft())) or {}).get("warps") or {}).values():
                dm = int(dest[0])
                if dm == int(map_id):
                    return (hops + 1) * HOP_STEPS
                if dm not in seen:
                    seen.add(dm)
                    q.append(dm)
        hops += 1
    return float(FAR_TRAVEL)


def choose(ledger: "GrindLedger", party_levels: list, need_level: int, current_map, mem=None,
           trainee_slot: int | None = None) -> GrindPoint | None:
    """The best point for the trainee's level (``trainee_slot``, else the lead), or None when there is
    no gap. Deterministic: measured xp/min once MIN_MEASURED episodes exist (else prior) minus travel
    and blackout costs; ties by map id."""
    if not party_levels:
        return None
    lvl = party_levels[trainee_slot] if trainee_slot is not None and 0 <= trainee_slot < len(party_levels) \
        else party_levels[0]
    if need_level - lvl <= 0:
        return None
    maps, best = _maps_of(mem), None
    for p in ledger.points.values():
        lo, hi = p.level_band
        if not lo <= lvl <= hi:
            continue
        xp = p.xp_per_min_measured if (p.n_measured >= MIN_MEASURED and p.xp_per_min_measured is not None) \
            else p.xp_per_min_prior
        score = xp - travel_steps(maps, current_map, p.map_id) / atlas.STEPS_PER_MIN - p.blackout_rate * atlas.BLACKOUT_STEPS
        key = (-score, p.map_id)
        if best is None or key < best[0]:
            best = (key, p)
    return best[1] if best else None


class GrindLedger:  # the point table plus its run-local file; ``points``: {map_id: GrindPoint}

    def __init__(self, points: dict | None = None, path: Path | str | None = None):
        self.points: dict[int, GrindPoint] = points or {}
        self.path = Path(path) if path else None

    # --- file: {"version": 1, "points": {"35": {...}}, "updated": iso} ---
    @classmethod
    def load(cls, path: Path | str = LEDGER_PATH) -> "GrindLedger":
        path = Path(path)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            rows = doc.get("points") if isinstance(doc, dict) else None
            if not isinstance(rows, dict):
                raise ValueError("no points table")
            pts = points_of(rows)
        except (OSError, ValueError) as e:
            if path.exists():
                log.info("grind points: ignoring unreadable %s (%r); starting empty", path, e)
            return cls({}, path)
        return cls(pts, path)

    def save(self, path: Path | str | None = None) -> None:
        path = Path(path or self.path or LEDGER_PATH)
        doc = {"version": SCHEMA, "points": {str(k): v.to_dict() for k, v in sorted(self.points.items())},
               "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    # --- the swarm-shared table under mem.data["grind_points"]: {map_id: point dict} ---
    def to_table(self) -> dict:
        return {str(k): v.to_dict() for k, v in self.points.items()}

    @classmethod
    def from_table(cls, table: dict, path: Path | str | None = None) -> "GrindLedger":
        rows = (table or {}).get("points", table) if isinstance(table, dict) else {}
        return cls(points_of(rows), path)

    def upsert(self, point: GrindPoint) -> None:
        self.points[int(point.map_id)] = point

    def merge(self, other) -> None:
        """Fold another ledger or shared table dict in (``merge_point`` per map id)."""
        rows = other.points if isinstance(other, GrindLedger) else \
            {int(k): v for k, v in (other.get("points", other) or {}).items() if isinstance(v, dict)}
        for k, v in rows.items():
            d = self.points.get(int(k))
            merged = merge_point(d.to_dict() if d else None, v.to_dict() if isinstance(v, GrindPoint) else v)
            if merged:
                self.points[int(k)] = GrindPoint.from_dict(merged)

    def seed_from_atlas(self, doc: dict, kb: dict | None = None, maps: dict | None = None,
                        now: str | None = None) -> int:
        """Prior-only points from a runs/grind_atlas.json doc; returns spot rows contributed."""
        n = 0
        costs = (doc.get("inputs") or {}).get("center_cost") or {}
        for goals in (doc.get("atlas") or {}).values():
            for levels in goals.values():
                for spots in levels.values():
                    for s in spots or []:
                        mid = int(s["map_id"])
                        p = self.points.get(mid)
                        if p is None:
                            p = self.points[mid] = GrindPoint(mid, s.get("name") or "",
                                                            center_cost_frames=float(costs.get(str(mid), 0.0)))
                        p.xp_per_min_prior = max(p.xp_per_min_prior, float(s.get("xp_per_min") or 0.0))
                        p.name = p.name or s.get("name") or ""
                        n += 1
        for p in self.points.values():
            if not p.species:
                p.species = species_of(kb, p.map_id)
            if p.level_band == DEFAULT_BAND and p.species:
                p.level_band = band_of(p.species)
            if not p.patch and maps:
                p.patch = patch_of(maps, p.map_id)
            p.updated = now or p.updated or time.strftime("%Y-%m-%dT%H:%M:%S")
        return n
