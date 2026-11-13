"""One typed, gated view of the party and battle RAM, read once per emulator frame.

Built on ramstructs' decoders and per-frame memo; the gating rules that used to live
inside one-off callers are the view now: a stale wBattleMon (species byte 0) is never
exposed, the enemy party block is read only in trainer battles, and the active slot
is trusted only while it is verified against the battle species.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent import ramstructs
from pokeagent.ram_symbols import (BATTLE_MON, ENEMY_MON_PARTY_POS, ENEMY_MON_SIZE, ENEMY_MONS,
                                   ENEMY_PARTY_COUNT, ENEMY_PARTY_SPECIES, IS_IN_BATTLE, MAX_PARTY,
                                   NAME_SIZE, PARTY_FOUGHT_ENEMY_FLAGS, PARTY_GAIN_EXP_FLAGS,
                                   PARTY_MON_NICKS, PLAYER_MON_NUMBER, SPECIES_MAGIKARP)


def _u16(raw: bytes, off: int) -> int:
    return (raw[off] << 8) | raw[off + 1]


@dataclass(frozen=True)
class PartySlot:
    index: int
    species: int
    level: int
    hp: int
    max_hp: int
    status: int
    moves: tuple[int, int, int, int]
    pp: tuple[int, int, int, int]
    ot_id: int
    dv_word: int
    nickname: bytes

    @property
    def fainted(self) -> bool:
        return self.hp <= 0 or self.species == 0   # hp <= 0 (an empty slot, species 0, is also fainted)


@dataclass(frozen=True)
class PartyView:
    slots: tuple[PartySlot, ...]
    count: int                      # min(wPartyCount, 6)
    in_battle: int                  # 0, 1 or 2 (wIsInBattle normalised: 3/0xFF -> 0)
    active_slot: int | None         # only when in_battle AND verified against wBattleMon

    @property
    def lead(self) -> PartySlot | None:
        if not self.slots:
            return None
        if self.in_battle and self.active_slot is not None:
            return self.slots[self.active_slot]
        for s in self.slots:
            if not s.fainted:
                return s
        return self.slots[0]        # everyone is down: report the lead so callers see (0, max)

    def fighter(self) -> PartySlot | None:
        """Whoever is doing the fighting: the verified active slot in a fight, else the strongest healthy
        member (never a Magikarp while another member exists). The party stands lowest-level-first, so
        slot 0 is the weakest and is NOT the team's strength."""
        if not self.slots:
            return None
        if self.active_slot is not None:
            return self.slots[self.active_slot]
        others = [s for s in self.slots if s.species != SPECIES_MAGIKARP] or list(self.slots)
        return max(others, key=lambda q: (q.hp > 0, q.level, q.hp))

    @property
    def fainted_slots(self) -> tuple[int, ...]:
        return tuple(s.index for s in self.slots if s.species != 0 and s.hp <= 0)

    @property
    def any_fainted(self) -> bool:
        return bool(self.fainted_slots)


@dataclass(frozen=True)
class BattleMonView:
    species: int
    hp: int
    max_hp: int
    level: int
    status: int
    moves: tuple[int, int, int, int]
    pp: tuple[int, int, int, int]


@dataclass(frozen=True)
class EnemyMonView:
    species: int
    hp: int
    max_hp: int
    level: int
    status: int
    moves: tuple[int, int, int, int]
    pp: tuple[int, int, int, int]


@dataclass(frozen=True)
class EnemyPartyMon:
    species: int
    hp: int
    max_hp: int
    level: int


@dataclass(frozen=True)
class BattleView:
    kind: int                       # 0 no battle, 1 wild, 2 trainer (3/0xFF -> 0)
    battle_mon: BattleMonView | None   # None while wBattleMonSpecies is 0 (stale block)
    enemy_mon: EnemyMonView | None     # None while wEnemyMonSpecies is 0
    enemy_party_pos: int | None        # wEnemyMonPartyPos, trainer fights only
    participants: frozenset[int]       # party slots that fought this enemy
    enemy_party: tuple[EnemyPartyMon, ...]  # trainer fights only; () in wild fights


def _battle_kind(emu) -> int:
    k = emu.read(IS_IN_BATTLE)
    return k if k in (1, 2) else 0   # 3 / 0xFF read as no battle


def _active_slot(emu, in_battle: int, slots: tuple[PartySlot, ...]) -> int | None:
    """Only trusted while the battle mon is loaded and its species names a unique party slot."""
    if not in_battle:
        return None
    species = emu.read(BATTLE_MON)
    if not species:
        return None
    slot = emu.read(PLAYER_MON_NUMBER)
    if slot < len(slots) and slots[slot].species == species:
        return slot
    hits = [s.index for s in slots if s.species == species]
    return hits[0] if len(hits) == 1 else None


def _enemy_party(emu) -> tuple[EnemyPartyMon, ...]:
    n = min(emu.read(ENEMY_PARTY_COUNT), MAX_PARTY)
    if not n:
        return ()
    species = emu.read_range(ENEMY_PARTY_SPECIES, n)
    raw = emu.read_range(ENEMY_MONS, ENEMY_MON_SIZE * n)
    return tuple(EnemyPartyMon(species[i], _u16(raw, i * ENEMY_MON_SIZE + 1),
                               _u16(raw, i * ENEMY_MON_SIZE + 34), raw[i * ENEMY_MON_SIZE + 33])
                 for i in range(n))


def _party_view(emu) -> PartyView:
    party = ramstructs.read_party(emu)
    nicks = emu.read_range(PARTY_MON_NICKS, NAME_SIZE * len(party)) if party else b""
    slots = tuple(PartySlot(i, p.species, p.level, p.hp, p.max_hp, p.status, p.moves, p.pp,
                            p.ot_id, p.dv_word, nicks[i * NAME_SIZE:(i + 1) * NAME_SIZE])
                  for i, p in enumerate(party))
    in_battle = _battle_kind(emu)
    return PartyView(slots, len(slots), in_battle, _active_slot(emu, in_battle, slots))


def _battle_view(emu) -> BattleView:
    kind = _battle_kind(emu)
    if kind == 0:
        return BattleView(0, None, None, None, frozenset(), ())
    bm = ramstructs.read_battle_mon(emu)
    battle_mon = (BattleMonView(bm.species, bm.hp, bm.max_hp, bm.level, bm.status, bm.moves, bm.pp)
                  if bm.species else None)
    em = ramstructs.read_enemy_mon(emu)
    enemy_mon = (EnemyMonView(em.species, em.hp, em.max_hp, em.level, em.status, em.moves, em.pp)
                 if em.species else None)
    flags = emu.read(PARTY_GAIN_EXP_FLAGS) | emu.read(PARTY_FOUGHT_ENEMY_FLAGS)
    participants = frozenset(i for i in range(ramstructs.read_party_count(emu)) if flags >> i & 1)
    return BattleView(kind, battle_mon, enemy_mon,
                      emu.read(ENEMY_MON_PARTY_POS) if kind == 2 else None, participants,
                      _enemy_party(emu) if kind == 2 else ())


def read_party_view(emu) -> PartyView:
    """The party as typed slots plus the verified active slot; one RAM read per emulator frame."""
    return ramstructs._memoized(emu, "party_view", lambda: _party_view(emu))


def read_battle_view(emu) -> BattleView:
    """The battle as typed views with stale blocks gated out; one RAM read per emulator frame."""
    return ramstructs._memoized(emu, "battle_view", lambda: _battle_view(emu))
