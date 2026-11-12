"""Shared route-cache machinery for world.py: memory fingerprints, goal signatures, cache tables.

Split out of world.py to keep both under the explorer 300-line ceiling. ``maps_version`` fingerprints
everything a route can read from map memory EXCEPT ``visited``: a newly stood-on tile only ever adds
edges to the graph, it never invalidates a route planned over known walls. The learned-wall set stays
in it (the neighbour memo must see walls), while the last-result route cache keys on
``route_maps_version`` - walls excluded - and re-validates the cached path's own edges instead, so a
wall learned nowhere near the route is not its business. ``_immutable``/``_goal_sig`` decide whether a
goal callable can key a cache entry at all.
"""
from __future__ import annotations


def _route_fingerprint(d: dict, *, walls: bool) -> int:
    """One map's routing fingerprint: warps, jumps and every never-moving NPC's single recorded tile;
    the learned wall set only when ``walls`` (the last-result route cache checks its own path edges, so
    walls stay out of ITS key). ``visited`` is never part of it."""
    h = hash(frozenset(d.get("blocked", ()))) if walls else 0
    h = h * 31 + hash(frozenset((k, tuple(w)) for k, w in d.get("warps", {}).items()))
    h = h * 31 + hash(frozenset((k, tuple(j)) for k, j in d.get("jumps", {}).items()))
    for e in d.get("npcs", {}).values():
        pos = e.get("positions") or {}
        if not e.get("moves") and len(pos) == 1:
            h = h * 13 + hash(next(iter(pos)))
    return h


def maps_version(maps: dict) -> int:
    """A fingerprint of everything a route reads from memory: each map's blocked set, warps, jumps and
    every never-moving NPC's single recorded tile. ``visited`` is deliberately absent - it only grows,
    so its length must not roll the neighbour memo or the shared graph."""
    v = 0x9E3779B1
    for d in maps.values():
        v = v * 131 + _route_fingerprint(d, walls=True)
    return v


def route_maps_version(maps: dict) -> int:
    """``maps_version`` minus the learned-wall term: the key the last-result route caches use. A wall
    change still rolls ``maps_version`` (fresh neighbours, graph rebuilds); whether it may roll a
    cached ROUTE is decided per path by ``WorldGraph._edge_still_open``."""
    v = 0x9E3779B1
    for d in maps.values():
        v = v * 131 + _route_fingerprint(d, walls=False)
    return v


def _immutable(v) -> bool:
    """A value a route-cache key can trust: ``int``/``str``/``bool``/``float``/``None``, or a
    ``tuple``/``frozenset`` of them (recursively). Anything else - a live dict/set/list, or an
    identity-hashed object (``ctx``, ``self``, a ``Decision``) whose mutable state is not in the
    key - can change under the cached entry, so its goal must re-search every call."""
    if v is None or isinstance(v, (int, str, bool, float)):
        return True
    return isinstance(v, (tuple, frozenset)) and all(_immutable(x) for x in v)


def _goal_sig(goal_fn) -> tuple | None:
    """A repeatable identity for a per-step repeated goal lambda: code object + bound values. Any
    closure cell that is not immutable (see ``_immutable``) means no signature - that goal must
    re-search every call."""
    try:
        cells = tuple(c.cell_contents for c in (goal_fn.__closure__ or ()))
        if not all(_immutable(v) for v in cells):
            return None
        sig = (goal_fn.__code__, goal_fn.__defaults__ or (), cells,
               tuple(sorted((goal_fn.__kwdefaults__ or {}).items())))
        hash(sig)
        return sig
    except (TypeError, AttributeError, ValueError):
        return None


# Shared per-run caches. The neighbour memo is keyed by the full memory fingerprint (walls included),
# so a learned wall, warp, jump or static-NPC move rolls the key and stale entries are never served;
# the last-result route caches key on ``route_maps_version`` plus their own edge re-validation.
# Entries keep a strong ref to the maps dict: that pins it while the key's id() is live, so an id
# reused by a later dict can never alias an old bucket. Bounded: a run's versions churn, so both
# clear at CAP.
_NEIGH: dict = {}   # (id(maps), version, strict, blocked_now, allowed) -> (maps, {node: [(nxt, btn)]})
_ROUTES: dict = {}  # same key tuple (route version) + (goal signature, limit) -> (maps, start, nodes, buttons, full, seen)
_CACHE_CAP = 64
