"""impossible_state: verified-RAM invariants the game itself should never break."""
from __future__ import annotations

from pokeagent.ramstructs import MAX_PARTY, PARTY_COUNT, read_party

MONEY, MAP_ID = 0xD347, 0xD35E  # money: 3 bytes BCD; wCurMap (both read by ram.read_state)


def bad_bcd(raw: bytes) -> bool:
    return any((b >> 4) > 9 or (b & 0xF) > 9 for b in raw)


def impossible_state(emu, valid_maps: frozenset[int] | None) -> list[str]:
    """Names of the invariants broken right now (empty = fine)."""
    broken = []
    count = emu.read(PARTY_COUNT)
    if count > MAX_PARTY:
        broken.append(f"party_count={count}")
    for i, mon in enumerate(read_party(emu)):
        if mon.max_hp and mon.hp > mon.max_hp:
            broken.append(f"hp_over_max slot{i} {mon.hp}>{mon.max_hp}")
        if mon.species and mon.level == 0:
            broken.append(f"level0 slot{i} species={mon.species}")
    if bad_bcd(emu.read_range(MONEY, 3)):
        broken.append("money_not_bcd=" + emu.read_range(MONEY, 3).hex())
    if valid_maps is not None and emu.read(MAP_ID) not in valid_maps:
        broken.append(f"map_id_unknown=0x{emu.read(MAP_ID):02X}")
    return broken
