import hashlib
import json
from pathlib import Path


def schema_id(segment, *, screen=False, spatial=False, combat=False, battle_learning=False, travel_priority=False, potential=False, hold=8, settle=8, maps_digest='', novelty=0.0, menu_controls=False):
    spec = dict(version=3, segment=segment, screen=screen, spatial=spatial, combat=combat,
                battle_learning=battle_learning, travel_priority=travel_priority, potential=potential,
                hold=hold, settle=settle, maps_digest=maps_digest, novelty=novelty, menu_controls=menu_controls)
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


class SpatialObserver:
    def __init__(self, path='runs/maps.json'):
        self.memory = json.loads(Path(path).read_text())
        self.digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def observe(self, tilemap, map_id, x, y, tileset, *, obscured=False):
        if obscured or len(tilemap) != 360:
            return (0,) * 10
        types = self.memory.get('tile_types', {}).get(str(tileset), {})
        grass = self.memory.get('grass_ids', {}).get(str(tileset), {})
        blocked = set(self.memory.get('maps', {}).get(str(map_id), {}).get('blocked', []))
        cells = []
        for r in range(3, 6):
            for c in range(3, 6):
                indices = (2*r*20+2*c, 2*r*20+2*c+1, (2*r+1)*20+2*c, (2*r+1)*20+2*c+1)
                key = ','.join(f'{tilemap[i]:02X}' for i in indices)
                evidence = types.get(key, {})
                solid, walkable = evidence.get('solid', 0), evidence.get('walkable', 0)
                cells.append(3 if key in grass else 2 if solid >= 3 and walkable == 0 else 1 if walkable > solid else 0)
        mask = sum(1 << i for i, d in enumerate(('UP', 'DOWN', 'LEFT', 'RIGHT')) if f'{x},{y},{d}' in blocked)
        return (*cells, mask)


def combat_observation(emu):
    if not emu.read(0xD057):
        return (0,) * 13
    u16 = lambda a: (emu.read(a) << 8) | emu.read(a + 1)
    maximum = u16(0xD023)
    return (emu.read(0xD057), emu.read(0xCFE5), emu.read(0xCFF3),
            emu.read(0xD022), min(4, 4*u16(0xD015)//maximum) if maximum else 0,
            *(emu.read(0xD01C+i) for i in range(4)),
            *(emu.read(0xD02D+i) & 0x3F for i in range(4)))
