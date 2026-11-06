"""Human-readable renderers for brain CLI ``--text`` output (JSON stays the default)."""
from __future__ import annotations


def maps_text(s: dict) -> str:
    lines = [f"{'map':>4} {'visited':>7} {'blocked':>7} {'warps':>5} {'inter':>5} {'enc':>4} {'npcs':>4} {'jumps':>5}"]
    for mid, e in s["maps"].items():
        lines.append(f"{mid:>4} {e['visited']:>7} {e['blocked']:>7} {e['warps']:>5} {e['interactions']:>5} "
                     f"{e['encounters']:>4} {e['npcs']:>4} {e['jumps']:>5}")
    t = s["totals"]
    lines.append(f"totals: maps={t['maps']} visited={t['visited']} blocked={t['blocked']} warps={t['warps']} "
                 f"interactions={t['interactions']} tiles={t['tiles']} bad_warps={s['bad_warps']} "
                 f"beats={s['beats']} updated={s.get('updated')}")
    return "\n".join(lines)


def map_text(v: dict) -> str:
    if v.get("error"):
        return f"map {v['map']}: {v['error']}"
    out = [f"map {v['map']}  {v['width']}x{v['height']} at ({v['bounds']['min_x']},{v['bounds']['min_y']})"
           f"-{(v['bounds']['max_x'], v['bounds']['max_y'])}  known={v['tiles_known']}"]
    out += v["rows"]
    out.append(v["legend"])
    cells = v["overlay"]["cells"]
    if cells:
        out.append(f"overlay {v['overlay']['mode']}:")
        for k, val in cells.items():
            out.append(f"  {k}: {val}")
    return "\n".join(out)


def tile_text(f: dict) -> str:
    lines = [f"map {f['map']} tile ({f['x']},{f['y']})  kind={f['kind']}"
             + (f"  override={f['tile_kind_override']}" if f.get("tile_kind_override") else "")]
    for label in ("visited", "encounters"):
        if f.get(label):
            lines.append(f"  {label}: {f[label]}")
    for sect in ("warps", "warp_cand", "warp_taken", "jumps", "interactions", "fails", "outcomes",
                 "blocked_from", "blocked_into", "ledge_into", "interactions_aimed"):
        if f.get(sect):
            lines.append(f"  {sect}: {f[sect]}")
    if f.get("npcs"):
        lines.append(f"  npcs: {f['npcs']}")
    if f.get("edits"):
        lines.append(f"  edits: {[e.get('id') for e in f['edits']]}")
    return "\n".join(lines)


def diff_text(d: dict) -> str:
    lines = []
    for mid, e in d.get("maps", {}).items():
        if e.get("added") or e.get("removed"):
            lines.append(f"map {mid}: {'added' if e.get('added') else 'removed'}")
            continue
        for field, fd in (e.get("fields") or {}).items():
            parts = []
            for side in ("added", "removed", "changed"):
                blk = fd.get(side)
                if isinstance(blk, dict) and blk.get("count"):
                    parts.append(f"{side}={blk['count']}")
            if fd.get("a") is not None or fd.get("b") is not None:
                parts.append(f"{fd.get('a')!r}->{fd.get('b')!r}")
            if parts:
                lines.append(f"map {mid} {field}: {', '.join(parts)}")
    for key in (d.get("globals") or {}):
        lines.append(f"global {key}: changed")
    return "\n".join(lines) or "(no differences)"


def edits_text(recs: list) -> str:
    return "\n".join(f"{e.get('id', '?'):>12} {e.get('ts', '')} {e.get('op', '')} map={e.get('map')} "
                     f"key={e.get('key')} value={e.get('value')} note={e.get('note', '')} by={e.get('by', '')}"
                     for e in recs) or "(journal empty)"
