"""Typed decoders for Gen 1 Pokemon structs read from RAM (party mons, battle mons, item lists).

Layouts follow pret/pokered (party_struct / battle_struct); addresses come from the pokered.sym
import in data/ram_map.json. Pure byte decoders take bytes; the read_* helpers take an Emulator.
"""

from __future__ import annotations

from dataclasses import dataclass

from pokeagent.emulator import Emulator

PARTY_MON1 = 0xD16B
PARTY_COUNT = 0xD163
PARTY_MON_SIZE = 44
MAX_PARTY = 6
BATTLE_MON = 0xD014          # wBattleMon (the player's active mon)
ENEMY_MON = 0xCFE5           # wEnemyMon
BATTLE_STRUCT_SIZE = 29
PLAYER_STAT_MODS = 0xCD1A    # wPlayerMonStatMods: atk, def, spd, spc, acc, eva (7 = no change)
ENEMY_STAT_MODS = 0xCD2E
ENEMY_BASE_STATS = 0xD002    # wEnemyMonBaseStats: hp, atk, def, spd, spc (valid during a battle)
BAG_COUNT, BOX_COUNT = 0xD31D, 0xD53A
BAG_CAPACITY, BOX_CAPACITY = 20, 50
STAT_NAMES = ("hp", "attack", "defense", "speed", "special")


def u16(data: bytes, off: int) -> int:
    return (data[off] << 8) | data[off + 1]       # Gen 1 stores multi-byte stats big-endian


@dataclass(frozen=True)
class PartyMon:
    """One 44-byte party_struct."""

    species: int
    hp: int
    box_level: int
    status: int
    type1: int
    type2: int
    catch_rate: int
    moves: tuple[int, int, int, int]
    ot_id: int
    exp: int
    stat_exp: tuple[int, int, int, int, int]   # hp, attack, defense, speed, special
    dv_word: int                               # raw 2-byte DVs; decode with explorer.stats.dvs
    pp: tuple[int, int, int, int]
    level: int
    max_hp: int
    stats: tuple[int, int, int, int]           # attack, defense, speed, special


def decode_party_mon(raw: bytes) -> PartyMon:
    """Decode a 44-byte party_struct (offsets per pret: DVs +27, PP +29, level +33, stats +34)."""
    if len(raw) < PARTY_MON_SIZE:
        raise ValueError(f"party mon needs {PARTY_MON_SIZE} bytes, got {len(raw)}")
    return PartyMon(
        species=raw[0], hp=u16(raw, 1), box_level=raw[3], status=raw[4], type1=raw[5], type2=raw[6],
        catch_rate=raw[7], moves=tuple(raw[8:12]),  # type: ignore[arg-type]
        ot_id=u16(raw, 12), exp=(raw[14] << 16) | (raw[15] << 8) | raw[16],
        stat_exp=tuple(u16(raw, 17 + 2 * i) for i in range(5)),  # type: ignore[arg-type]
        dv_word=u16(raw, 27), pp=tuple(raw[29:33]),  # type: ignore[arg-type]
        level=raw[33], max_hp=u16(raw, 34),
        stats=tuple(u16(raw, 36 + 2 * i) for i in range(4)),  # type: ignore[arg-type]
    )


@dataclass(frozen=True)
class BattleMon:
    """A battle_struct (wBattleMon / wEnemyMon) plus its six stat modifiers."""

    species: int
    hp: int
    party_pos: int
    status: int
    type1: int
    type2: int
    moves: tuple[int, int, int, int]
    dv_word: int
    level: int
    max_hp: int
    stats: tuple[int, int, int, int]           # attack, defense, speed, special
    pp: tuple[int, int, int, int]
    stat_mods: tuple[int, ...] = ()            # atk, def, spd, spc, acc, eva; 7 = unmodified

    def mod_stages(self) -> tuple[int, ...]:
        """Stat stages -6..+6 (raw 1..13 minus 7)."""
        return tuple(m - 7 for m in self.stat_mods)


def decode_battle_mon(raw: bytes, stat_mods: bytes = b"") -> BattleMon:
    if len(raw) < BATTLE_STRUCT_SIZE:
        raise ValueError(f"battle mon needs {BATTLE_STRUCT_SIZE} bytes, got {len(raw)}")
    return BattleMon(
        species=raw[0], hp=u16(raw, 1), party_pos=raw[3], status=raw[4], type1=raw[5], type2=raw[6],
        moves=tuple(raw[8:12]), dv_word=u16(raw, 12), level=raw[14],  # type: ignore[arg-type]
        max_hp=u16(raw, 15), stats=tuple(u16(raw, 17 + 2 * i) for i in range(4)),  # type: ignore[arg-type]
        pp=tuple(raw[25:29]), stat_mods=tuple(stat_mods[:6]),  # type: ignore[arg-type]
    )


def decode_item_list(raw: bytes, capacity: int) -> list[tuple[int, int]]:
    """Decode a Gen 1 item list: count byte, (id, qty) pairs, 0xFF terminator."""
    count = min(raw[0], capacity)
    return [(raw[1 + 2 * i], raw[2 + 2 * i]) for i in range(count)]


_PARTY_MEMO: dict = {}  # id(emu) -> (emu, key, {"count": int, "party": [PartyMon]})
_PARTY_MEMO_CAP = 8     # a live run shares one emulator; the test suite makes thousands - bound it


def _party_key(emu) -> tuple | None:
    """(agent-step marker, write-revision) a party read stays valid for. ``Engine.step`` bumps
    ``emu.agent_step`` once per decision cycle (and ``begin_press`` bumps it for claude/human
    presses), so every read inside one step - however many frames the press ticks - shares a single
    decode; an emulator without the marker keeps the old per-frame key. A RAM write or state load
    bumps ``_ram_rev`` and forces a re-read either way. An emulator with neither marker nor frames
    counter (a stub or mock) bypasses the memo entirely."""
    try:
        step = getattr(emu, "agent_step", None)
        if step is None:
            step = int(emu.frames)
        return (int(step), int(getattr(emu, "_ram_rev", 0)))
    except (TypeError, ValueError, AttributeError):
        return None


def note_agent_step(emu) -> None:
    """Bump the emulator's agent-step marker once per decision cycle. Only emulators that carry the
    marker (``PyBoyEmulator.agent_step``) are touched: ``FakeEmulator`` and stubs keep the per-frame
    memo. Never raises - a marker must not be able to stop a step."""
    try:
        if not hasattr(emu, "agent_step"):
            return
        emu.agent_step = (getattr(emu, "agent_step", None) or 0) + 1
    except Exception:
        pass


def _memoized(emu, kind: str, read):
    """One RAM read per agent step for the party block: the profile counted ~12 read_party calls per
    step and ~3 real decodes, because a press ticks enough frames to roll a per-frame key several
    times inside one decision cycle."""
    key = _party_key(emu)
    if key is None:
        return read()
    ent = _PARTY_MEMO.get(id(emu))
    if ent is None or ent[0] is not emu or ent[1] != key:
        if len(_PARTY_MEMO) >= _PARTY_MEMO_CAP:
            _PARTY_MEMO.clear()
        ent = _PARTY_MEMO[id(emu)] = (emu, key, {})
    vals = ent[2]
    if kind not in vals:
        vals[kind] = read()
    return vals[kind]


def read_party_count(emu: Emulator) -> int:
    return _memoized(emu, "count", lambda: min(emu.read(PARTY_COUNT), MAX_PARTY))


def _read_party(emu: Emulator) -> list[PartyMon]:
    n = min(emu.read(PARTY_COUNT), MAX_PARTY)
    raw = emu.read_range(PARTY_MON1, PARTY_MON_SIZE * n) if n else b""
    return [decode_party_mon(raw[i * PARTY_MON_SIZE:(i + 1) * PARTY_MON_SIZE]) for i in range(n)]


def read_party(emu: Emulator) -> list[PartyMon]:
    """The party as PartyMon records, one per occupied slot; one RAM read per agent step."""
    return list(_memoized(emu, "party", lambda: _read_party(emu)))


def read_battle_mon(emu: Emulator) -> BattleMon:
    return decode_battle_mon(emu.read_range(BATTLE_MON, BATTLE_STRUCT_SIZE), emu.read_range(PLAYER_STAT_MODS, 6))


def read_enemy_mon(emu: Emulator) -> BattleMon:
    return decode_battle_mon(emu.read_range(ENEMY_MON, BATTLE_STRUCT_SIZE), emu.read_range(ENEMY_STAT_MODS, 6))


def read_enemy_base_stats(emu: Emulator) -> dict[str, int]:
    """The wild/trainer mon's species base stats (hp, attack, defense, speed, special); battle only."""
    return dict(zip(STAT_NAMES, emu.read_range(ENEMY_BASE_STATS, 5)))


def read_bag(emu: Emulator) -> list[tuple[int, int]]:
    return decode_item_list(emu.read_range(BAG_COUNT, 1 + 2 * BAG_CAPACITY + 1), BAG_CAPACITY)


def read_pc_items(emu: Emulator) -> list[tuple[int, int]]:
    return decode_item_list(emu.read_range(BOX_COUNT, 1 + 2 * BOX_CAPACITY + 1), BOX_CAPACITY)
