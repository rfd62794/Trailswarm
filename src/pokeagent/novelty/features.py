"""Game-state snapshot and the novelty feature keys read from it. Pure functions, no emulator beyond ``read_snapshot``.

Keys: ``t:map:x:y`` tile, ``m:map`` map, ``w:from>to`` map transition, ``f:bit`` event-flag bit (0..2559 from 0xD747),
``i:id`` item in the bag, ``so:id`` species in the party, ``ss:id`` species seen as a battle opponent, ``mv:id`` move known.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

FLAGS_ADDR, FLAGS_LEN = 0xD747, 320     # wEventFlags (ram_map.json: bitmask, verified)
ENEMY_SPECIES = 0xCFE5                  # wEnemyMon species, valid while a battle is on

WEIGHTS = {"m": 5.0, "f": 3.0, "i": 2.0, "so": 1.5, "ss": 1.0, "mv": 1.2, "w": 1.0, "t": 0.1}  # map > flag > item > species > warp > tile


@dataclass(frozen=True)
class Snapshot:
    map: int = 0
    x: int = 0
    y: int = 0
    flags: bytes = b""
    bag: tuple = ()          # ((item id, qty), ...)
    pc: tuple = ()           # PC box items, same shape
    money: int = 0
    party: tuple = ()        # ((species, level, exp, moves, ident), ...); ident = (ot_id, dv_word) follows a mon across slots
    in_battle: bool = False
    enemy: int = 0


def read_snapshot(emu) -> Snapshot:
    from pokeagent.ram import read_state
    from pokeagent.ramstructs import read_bag, read_party, read_pc_items
    s = read_state(emu)
    party = tuple((m.species, m.level, m.exp, tuple(m.moves), (m.ot_id, m.dv_word)) for m in read_party(emu))
    return Snapshot(s.map_id, s.x, s.y, bytes(emu.read_range(FLAGS_ADDR, FLAGS_LEN)), tuple(read_bag(emu)), tuple(read_pc_items(emu)),
                    s.money, party, s.in_battle, emu.read(ENEMY_SPECIES) if s.in_battle else 0)


def flag_bits(cur: bytes, prev: bytes | None = None) -> list[int]:
    """Bit indexes set in ``cur`` (all of them, or only those newly set versus ``prev``)."""
    out = []
    for i, b in enumerate(cur):
        p = prev[i] if prev is not None and i < len(prev) else 0
        new = b & ~p & 0xFF if prev is not None else b
        for k in range(8):
            if new >> k & 1:
                out.append(i * 8 + k)
    return out


def features(cur: Snapshot, prev: Snapshot | None = None) -> list[str]:
    """Every feature visible in ``cur``; event-flag bits only the newly set ones when ``prev`` is given (cheap per step)."""
    keys = [f"t:{cur.map}:{cur.x}:{cur.y}", f"m:{cur.map}"]
    if prev is not None and prev.map != cur.map:
        keys.append(f"w:{prev.map}>{cur.map}")
    if prev is None or prev.flags != cur.flags:
        keys += [f"f:{b}" for b in flag_bits(cur.flags, None if prev is None else prev.flags)]
    keys += [f"i:{i}" for i, q in cur.bag if q > 0]
    for sp, _lv, _exp, moves, _id in cur.party:
        keys.append(f"so:{sp}")
        keys += [f"mv:{m}" for m in moves if m]
    if cur.in_battle and cur.enemy:
        keys.append(f"ss:{cur.enemy}")
    return keys


def kind(key: str) -> str:
    return key.split(":", 1)[0]


def weight(key: str) -> float:
    return WEIGHTS.get(kind(key), 0.0)


def bonus(key: str, count: int) -> float:
    """w_type / sqrt(1 + global count): the first-ever discovery gets the full weight."""
    return weight(key) / math.sqrt(1 + max(0, count))
