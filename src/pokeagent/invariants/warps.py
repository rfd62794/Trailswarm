"""Check 1: every learned warp in maps.json should be a ROM warp tile or a map-edge exit.

Reuses par_follow.legit_exit (the swarm's own phantom test) over the ROM grids from legs.grid.rom_grids.
"""
from __future__ import annotations

from pathlib import Path

from pokeagent.invariants.findings import ERROR, INFO, WARN, Finding, fmt_map, read_json


def check_warps(maps_path: Path, rom: Path | None = None, grid_get=None) -> list[Finding]:
    """``grid_get(map_id) -> Grid | None`` may be injected (tests); default is the ROM at ``rom``."""
    data, err = read_json(maps_path)
    if err or not isinstance(data, dict) or not isinstance(data.get("maps"), dict):
        return [Finding("warps", ERROR if err else INFO, "unreadable", f"{maps_path}: {err or 'missing or no maps table'}")]
    if grid_get is None:
        from pokeagent.legs import grid as G
        grid_get = G.rom_grids(rom)
    if grid_get is None:
        return [Finding("warps", INFO, "no_rom", "ROM not found: warp check skipped")]
    from pokeagent.explorer.par_follow import legit_exit
    bad = set(data.get("bad_warps") or [])
    out: list[Finding] = []
    for mid, m in data["maps"].items():
        warps = (m or {}).get("warps") or {}
        try:
            g = grid_get(int(mid))
        except (TypeError, ValueError):
            g = None
        if g is None:
            if warps:
                out.append(Finding("warps", INFO, "no_grid", f"map {fmt_map(mid)}: no ROM grid, {len(warps)} warps unchecked"))
            continue
        for key in warps:
            try:
                x, y, d = key.split(",")
                ok = legit_exit(g, (int(x), int(y)), d)
            except (ValueError, KeyError):
                out.append(Finding("warps", ERROR, "bad_key", f"map {fmt_map(mid)}: malformed warp key {key!r}", {"map": int(mid), "key": key}))
                continue
            if ok:
                continue
            taken = int((m.get("warp_taken") or {}).get(key, 0))
            disproof = int((m.get("warp_disproof") or {}).get(key, 0))
            tomb = f"{mid}:{key}" in bad
            out.append(Finding(
                "warps", WARN if tomb else ERROR, "phantom_warp",
                f"map {fmt_map(mid)} warp {key}: no ROM warp tile or map edge (taken {taken}, disproved {disproof}, "
                f"{'already' if tomb else 'NOT'} in bad_warps)",
                {"map": int(mid), "key": key, "warp_taken": taken, "warp_disproof": disproof, "tombstoned": tomb}))
    return out
