from enum import IntEnum
import hashlib
import json
from pathlib import Path

from pokeagent.game.stores import store_path
from pokeagent.party_view import read_battle_view
from pokeagent.ram_symbols import IS_IN_BATTLE


def schema_id(segment, *, screen=False, spatial=False, combat=False, battle_learning=False, travel_priority=False, potential=False, hold=8, settle=8, maps_digest='', novelty=0.0, menu_controls=False):
    spec = dict(version=4, segment=segment, screen=screen, spatial=spatial, combat=combat,
                battle_learning=battle_learning, travel_priority=travel_priority, potential=potential,
                hold=hold, settle=settle, maps_digest=maps_digest, novelty=novelty, menu_controls=menu_controls)
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


class TileClass(IntEnum):
    UNKNOWN = 0
    WALKABLE = 1
    SOLID = 2
    GRASS = 3


def local_tile_window(tilemap: bytes) -> tuple[str, ...]:
    if len(tilemap) != 360:
        return ()
    cells = []
    for r in range(3, 6):
        for c in range(3, 6):
            indices = (2*r*20+2*c, 2*r*20+2*c+1, (2*r+1)*20+2*c, (2*r+1)*20+2*c+1)
            cells.append(','.join(f'{tilemap[i]:02X}' for i in indices))
    return tuple(cells)


class SpatialObserver:
    def __init__(self, path=store_path("runs/maps.json").as_posix()):  # POKEAGENT_GAME read once at def time
        self.memory = json.loads(Path(path).read_text())
        self.digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def observe(self, tilemap, map_id, x, y, tileset, *, obscured=False):
        if obscured or len(tilemap) != 360:
            return (0,) * 10
        types = self.memory.get('tile_types', {}).get(str(tileset), {})
        grass = self.memory.get('grass_ids', {}).get(str(tileset), {})
        blocked = set(self.memory.get('maps', {}).get(str(map_id), {}).get('blocked', []))
        cells = []
        for key in local_tile_window(tilemap):
            evidence = types.get(key, {})
            solid, walkable = evidence.get('solid', 0), evidence.get('walkable', 0)
            cells.append(int(TileClass.GRASS if key in grass else
                             TileClass.SOLID if solid >= 3 and walkable == 0 else
                             TileClass.WALKABLE if walkable > solid else TileClass.UNKNOWN))
        mask = sum(1 << i for i, d in enumerate(('UP', 'DOWN', 'LEFT', 'RIGHT')) if f'{x},{y},{d}' in blocked)
        return (*cells, mask)


def combat_observation(emu):
    bm = read_battle_view(emu).battle_mon  # None while wBattleMon is stale (species 0 at battle start)
    if bm is None:
        return (0,) * 13
    maximum = bm.max_hp
    return (emu.read(IS_IN_BATTLE), emu.read(0xCFE5), emu.read(0xCFF3),
            bm.level, min(4, 4*bm.hp//maximum) if maximum else 0,
            *bm.moves, *(p & 0x3F for p in bm.pp))
