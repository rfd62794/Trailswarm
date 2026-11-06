"""lessons: summarised battle, damage, tile-type and beat tables from maps.json."""
from __future__ import annotations

DAMAGE_TABLES = ("move_damage", "enemy_damage", "damage_dealt", "damage_taken", "item_heal")
KINDS = ("all", "battle", "damage", "tiles", "beats")
MAX_BEATS = 100


def _mean(vals: list) -> float | None:
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 2) if vals else None


def _battle(data: dict) -> dict:
    out = {}
    for sp in sorted((data.get("battle_lessons") or {}), key=str):
        ls = data["battle_lessons"][sp] or {}
        turns, hp_lost = ls.get("turns") or [], ls.get("hp_lost") or []
        fights = ls.get("fights", 0)
        out[str(sp)] = {
            "fights": fights, "wins": ls.get("wins", 0), "fled": ls.get("fled", 0),
            "win_rate": round(ls.get("wins", 0) / fights, 3) if fights else None,
            "avg_turns": _mean(turns), "avg_hp_lost": _mean(hp_lost),
            "best_move": ls.get("best_move"), "move_avg_damage": ls.get("move_avg_damage"),
        }
    return out


def _damage_table(table: dict) -> dict:
    vals = [v for row in (table or {}).values() if isinstance(row, list) for v in row
            if isinstance(v, (int, float))]
    return {"entries": len(table or {}), "samples": len(vals), "mean": _mean(vals)}


def _damage(data: dict) -> dict:
    return {name: _damage_table(data.get(name) or {}) for name in DAMAGE_TABLES}


def _tiles(data: dict) -> dict:
    tt = data.get("tile_types") or {}
    gi = data.get("grass_ids") or {}
    solid = walkable = 0
    for table in tt.values():
        for e in (table or {}).values():
            s, w = (e or {}).get("solid", 0), (e or {}).get("walkable", 0)
            if s >= 3 and w == 0:
                solid += 1
            elif w > s:
                walkable += 1
    return {
        "tile_types": {"tilesets": len(tt), "blocks": sum(len(t or {}) for t in tt.values()),
                       "solid": solid, "walkable": walkable},
        "grass_ids": {"tilesets": len(gi), "blocks": sum(len(t or {}) for t in gi.values())},
    }


def _beats(data: dict) -> dict:
    beats = data.get("beats") or {}
    out = {}
    for sig in sorted(beats, key=str)[:MAX_BEATS]:
        b = beats[sig] or {}
        out[str(sig)] = {"buttons": len(b.get("buttons") or []), "grade": b.get("grade"),
                         "replays": b.get("replays", 0), "seen": b.get("seen"),
                         "source": b.get("source")}
    return {"count": len(beats), "truncated": len(beats) > MAX_BEATS, "beats": out}


def lessons(data: dict, kind: str = "all") -> dict:
    """Summaries of the learned tables. ``kind``: all | battle | damage | tiles | beats."""
    kind = kind or "all"
    if kind not in KINDS:
        raise ValueError(f"unknown lessons kind {kind!r}; use one of {KINDS}")
    out = {}
    if kind in ("all", "battle"):
        out["battle"] = _battle(data)
    if kind in ("all", "damage"):
        out["damage"] = _damage(data)
    if kind in ("all", "tiles"):
        out["tiles"] = _tiles(data)
    if kind in ("all", "beats"):
        out["beats"] = _beats(data)
    return out
