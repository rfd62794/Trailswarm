"""Read side of the XP meter: the console line, current per-member rates, the best spot per level band."""
from __future__ import annotations

from pokeagent.explorer import xp_spots


def _names(species: int, map_id) -> tuple[str, str]:
    try:
        from pokeagent.intervene.names import map_name, species_name
        return str(species_name(species)).upper(), map_name(map_id).upper().replace(" ", "_")
    except Exception:
        return f"#{species}", f"MAP_{map_id}"


def console_line(rows: list[dict]) -> str | None:
    """``[xp] KAKUNA L9 +412 xp/1k steps on ROUTE_24 (solo 0%, switched 100%)`` for the window's top XP earner."""
    rows = [r for r in rows if r.get("kind", "window") == "window" and r.get("xp_gain", 0) > 0]
    if not rows:
        return None
    r = max(rows, key=lambda r: r["xp_gain"])
    sp, mp = _names(r["species"], r.get("map"))
    n = max(1, r["solo"] + r["switched"])
    return (f"[xp] {sp} L{r['level']} +{r['xp_per_1k_steps']:.0f} xp/1k steps on {mp} "
            f"(solo {100 * r['solo'] // n}%, switched {100 * r['switched'] // n}%)")


def member_rates(ctx) -> dict[str, float]:
    """{member key: xp per 1000 steps in the last closed window} (viewer roster strip, Training v2)."""
    m = getattr(ctx, "xp_meter", None)
    return dict(m.latest) if m is not None else {}


def best_spots(path=xp_spots.LEDGER_PATH, min_n: int = 1) -> dict[str, dict]:
    """{level band: {"map", "xp_per_1k", "n"}}: the best measured training spot for each band, from the shared ledger."""
    return xp_spots.XpSpots.load(path).best_by_band(min_n)
