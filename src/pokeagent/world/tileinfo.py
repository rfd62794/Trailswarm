"""Everything known about one tile, as text (pure): ROM truth + the union of the agents' beliefs + who learned it first."""
from __future__ import annotations

from pokeagent.atlas.rom_maps import MapHeader, map_name
from pokeagent.world.model import WorldModel


def describe(map_id: int, x: int, y: int, headers: dict[int, MapHeader], world: WorldModel) -> list[str]:
    out = [f"{map_name(map_id)} (0x{map_id:02X})  cell ({x}, {y})"]
    hd = headers.get(map_id)
    if hd is not None:
        out += [f"ROM: warp to 0x{dm:02X} {map_name(dm)}" for wx, wy, _dw, dm in hd.warps if (wx, wy) == (x, y)]
        out += [f"ROM: sign (text {t})" for sx, sy, t in hd.signs if (sx, sy) == (x, y)]
        out += [f"ROM: {o['kind']} object, sprite {o['sprite']}" for o in hd.objects if (o["x"], o["y"]) == (x, y)]
    belief = [f"learned {v.kind}{' ' + v.dir if v.dir else ''}"
              + (f" -> {v.dest}" if v.dest else "") + f" first by {v.agent}" + (f", also {', '.join(v.also)}" if v.also else "")
              for v in world.who_learned(map_id, x, y)]
    visits = world.union_model()["maps"].get(str(map_id), {}).get("visited", {}).get(f"{x},{y}", 0)
    out += belief or ["no agent has learned anything here"]
    if visits:
        out.append(f"visited {visits}x by all agents")
    return out
