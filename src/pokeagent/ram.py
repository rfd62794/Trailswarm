"""RAM map and typed game-state reads for Pokemon Red."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pokeagent.emulator import Emulator

RAM_MAP = {   # believed addresses from pret/pokered wram.asm - UNVERIFIED, calibrated later; keep in this one table
    "map_id": 0xD35E, "player_y": 0xD361, "player_x": 0xD362, "party_count": 0xD163,
    "badges": 0xD356, "in_battle": 0xD057, "money": 0xD347,   # money: 3 bytes BCD
}


def decode_bcd(data: bytes) -> int:
    """Decode packed BCD bytes to an int: b"\\x01\\x23\\x45" -> 12345."""
    value = 0
    for byte in data:
        value = value * 100 + (byte >> 4) * 10 + (byte & 0x0F)
    return value


@dataclass(frozen=True)
class GameState:
    map_id: int
    x: int
    y: int
    party_count: int
    badges: int
    badge_count: int
    in_battle: bool
    money: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        battle = "yes" if self.in_battle else "no"
        return (
            f"map=0x{self.map_id:02x} pos=({self.x},{self.y}) "
            f"party={self.party_count} badges={self.badge_count} "
            f"battle={battle} money={self.money}"
        )


def read_state(emu: Emulator) -> GameState:
    """Read the RAM_MAP addresses through the emulator into a GameState."""
    badges = emu.read(RAM_MAP["badges"])
    return GameState(
        map_id=emu.read(RAM_MAP["map_id"]),
        x=emu.read(RAM_MAP["player_x"]),
        y=emu.read(RAM_MAP["player_y"]),
        party_count=emu.read(RAM_MAP["party_count"]),
        badges=badges,
        badge_count=bin(badges).count("1"),
        in_battle=emu.read(RAM_MAP["in_battle"]) != 0,
        money=decode_bcd(emu.read_range(RAM_MAP["money"], 3)),
    )
