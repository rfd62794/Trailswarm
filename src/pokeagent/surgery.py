"""State surgery: whitelisted RAM writes on a loaded save state (heal, money, respawn, items, HP/level, position).

``apply`` validates EVERY edit before the first write, so it is all-or-nothing from the caller's view. An edited
state is SYNTHETIC - usable for drills and A/B runs, never a chain checkpoint or a personal best - and
``tools/state_edit.py`` stamps it that way. ``position`` is UNSAFE in v1 and refused unless the edit dict carries
``"unsafe_pos": True``: it writes only the player tile bytes (0xD361/0xD362), so the map-view pointer (0xD35F..0xD360)
and scroll are not shifted and the screen desyncs from the coordinates (observed on the ROM: one tile off, and a RIGHT
from the edited x did nothing). Drills and A/B runs must not use it.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pokeagent import statefp
from pokeagent.explorer import stats
from pokeagent.ramstructs import (BAG_CAPACITY, BAG_COUNT, MAX_PARTY, PARTY_COUNT, PARTY_MON_SIZE, PARTY_MON1,
                                  decode_item_list, read_party)

MAP, Y, X, MONEY, RESPAWN = statefp.MAP, statefp.Y, statefp.X, statefp.MONEY, statefp.RESPAWN


class SurgeryError(ValueError):
    """Unknown field, out-of-range value, bag capacity exceeded, or a refused edit."""


WHITELIST = ("heal", "set_hp", "set_level", "money", "respawn", "give", "take", "position")
RESPAWN_TOWNS = range(11)   # 0 Pallet .. 10 Saffron; 15 was seen in the wild but is not understood


@dataclass(frozen=True)
class _Ctx:
    max_pp: Callable[[int], int | None] | None        # move id -> base PP (None = leave that move's PP byte alone)
    base_stats: Callable[[int], dict | None]          # species id -> base stats (None = cannot set_level)


def _u16(v: int) -> tuple[int, int]:
    return (v >> 8) & 0xFF, v & 0xFF


def _party(emu):
    return read_party(emu)


def _bag(emu) -> list[list[int]]:
    raw = emu.read_range(BAG_COUNT, 1 + 2 * BAG_CAPACITY + 1)
    return [[i, q] for i, q in decode_item_list(raw, BAG_CAPACITY)]


def _pairs(spec, name: str) -> list[tuple[int, int]]:
    try:
        pairs = [(int(i), int(q)) for i, q in spec]
    except (TypeError, ValueError):
        raise SurgeryError(f"{name}: expected [(item_id, qty), ...]") from None
    if not pairs:
        raise SurgeryError(f"{name}: empty list")
    for i, q in pairs:
        if not 1 <= i <= 0xFE or not 1 <= q <= 99:
            raise SurgeryError(f"{name}: bad item id / qty ({i}, {q})")
    return pairs


def _heal(emu, flag, ctx: _Ctx) -> list[tuple[int, int]]:
    if flag is not True:
        raise SurgeryError("heal must be True")
    writes = []
    for slot, mon in enumerate(_party(emu)):
        base = PARTY_MON1 + slot * PARTY_MON_SIZE
        hi, lo = _u16(mon.max_hp)
        writes += [(base + 1, hi), (base + 2, lo), (base + 4, 0)]     # HP = max HP, status cleared
        if ctx.max_pp is None:
            continue
        for i, move in enumerate(mon.moves):
            if not move:
                continue
            pp = ctx.max_pp(move)
            if pp is None:
                continue
            ups = mon.pp[i] >> 6                                       # PP Ups: top 2 bits, kept
            writes.append((base + 29 + i, (ups << 6) | min(63, pp + ups * (pp // 5))))
    return writes


def _set_hp(emu, spec, ctx: _Ctx) -> list[tuple[int, int]]:
    if not isinstance(spec, dict) or not spec:
        raise SurgeryError("set_hp: expected {slot: hp}")
    party = _party(emu)
    writes = []
    for slot, hp in spec.items():
        if not isinstance(slot, int) or not 0 <= slot < len(party):
            raise SurgeryError(f"set_hp: bad slot {slot!r}")
        if isinstance(hp, bool) or not isinstance(hp, int) or not 0 <= hp <= party[slot].max_hp:
            raise SurgeryError(f"set_hp: {hp!r} out of range for slot {slot} (max {party[slot].max_hp})")
        hi, lo = _u16(hp)
        base = PARTY_MON1 + slot * PARTY_MON_SIZE
        writes += [(base + 1, hi), (base + 2, lo)]
    return writes


def _set_level(emu, spec, ctx: _Ctx) -> list[tuple[int, int]]:
    if not isinstance(spec, dict) or not spec:
        raise SurgeryError("set_level: expected {slot: level}")
    party = _party(emu)
    writes = []
    for slot, level in spec.items():
        if not isinstance(slot, int) or not 0 <= slot < len(party):
            raise SurgeryError(f"set_level: bad slot {slot!r}")
        mon = party[slot]
        if isinstance(level, bool) or not isinstance(level, int) or not mon.level <= level <= 100:
            raise SurgeryError(f"set_level: {level!r} out of range for slot {slot} (level {mon.level}, raise only)")
        base_stats = ctx.base_stats(mon.species)
        if base_stats is None:
            raise SurgeryError("set_level needs base stats (kb/rom_tables.json)")
        try:
            d, sx = stats.dvs(mon), stats.stat_exp(mon)
            vals = {k: stats.stat_value(base_stats[k], d[k], sx[k], level, hp=(k == "hp"))
                    for k in stats.STAT_KEYS}
        except (KeyError, TypeError):
            raise SurgeryError("set_level needs base stats (kb/rom_tables.json)") from None
        base = PARTY_MON1 + slot * PARTY_MON_SIZE
        hp = max(0, min(mon.hp + vals["hp"] - mon.max_hp, vals["hp"]))   # HP rises by what max HP rose, never above max
        hi, lo = _u16(hp)
        mh, ml = _u16(vals["hp"])
        writes += [(base + 1, hi), (base + 2, lo), (base + 3, level), (base + 33, level),
                   (base + 34, mh), (base + 35, ml)]
        for i, k in enumerate(("attack", "defense", "speed", "special")):
            hi, lo = _u16(vals[k])
            writes += [(base + 36 + 2 * i, hi), (base + 37 + 2 * i, lo)]
    return writes


def _money(emu, n, ctx: _Ctx) -> list[tuple[int, int]]:
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 999999:
        raise SurgeryError(f"money: {n!r} out of range (0..999999)")
    return [(MONEY + i, (d // 10 << 4) | d % 10) for i, d in enumerate((n // 10000, n // 100 % 100, n % 100))]


def _respawn(emu, m, ctx: _Ctx) -> list[tuple[int, int]]:
    if not isinstance(m, int) or m not in RESPAWN_TOWNS:
        raise SurgeryError(f"respawn: {m!r} is not a town id (0..10)")
    return [(RESPAWN, m)]


def _give(emu, spec, ctx: _Ctx) -> list[tuple[int, int]]:
    pairs = _pairs(spec, "give")
    bag = _bag(emu)
    for item, qty in pairs:
        left = qty
        for slot in bag:                       # top up existing stacks of the same id first (max 99 per slot)
            if left and slot[0] == item:
                add = min(99 - slot[1], left)
                slot[1] += add
                left -= add
        if left:
            if len(bag) >= BAG_CAPACITY:
                raise SurgeryError(f"give: bag is full ({BAG_CAPACITY} slots)")
            bag.append([item, left])
    return _bag_writes(bag)


def _take(emu, spec, ctx: _Ctx) -> list[tuple[int, int]]:
    pairs = _pairs(spec, "take")
    bag = _bag(emu)
    for item, qty in pairs:
        if sum(q for i, q in bag if i == item) < qty:
            raise SurgeryError(f"take: bag holds less than {qty} of item {item:#04x}")
        left, keep = qty, []
        for i, q in bag:
            if i == item and left:
                use = min(q, left)
                q, left = q - use, left - use
            if q:
                keep.append([i, q])            # a slot reaching 0 drops out; later slots shift up
        bag = keep
    return _bag_writes(bag)


def _bag_writes(bag: list[list[int]]) -> list[tuple[int, int]]:
    """Count byte, the (id, qty) pairs, then the 0xFF terminator right after the last pair."""
    writes = [(BAG_COUNT, len(bag))]
    for k, (i, q) in enumerate(bag):
        writes += [(BAG_COUNT + 1 + 2 * k, i), (BAG_COUNT + 2 + 2 * k, q)]
    writes.append((BAG_COUNT + 1 + 2 * len(bag), 0xFF))
    return writes


def _position(emu, spec, ctx: _Ctx) -> list[tuple[int, int]]:
    if not isinstance(spec, dict):
        raise SurgeryError("position: expected {'map': m, 'x': x, 'y': y, 'unsafe_pos': True}")
    if spec.get("unsafe_pos") is not True:
        raise SurgeryError("position edits are unsafe in v1: the map view pointer (0xD35F) and scroll are not updated, "
                           "so the screen desyncs from the coordinates; not supported")
    if spec.get("map") != emu.read(MAP):
        raise SurgeryError("position: v1 cannot change maps (a map id write without a warp breaks the loaded tile data)")
    x, y = spec.get("x"), spec.get("y")
    if not all(isinstance(v, int) and 0 <= v <= 0xFF for v in (x, y)):
        raise SurgeryError("position: x and y must be bytes")
    return [(Y, y), (X, x)]


_PLAN = {"heal": _heal, "set_hp": _set_hp, "set_level": _set_level, "money": _money,
         "respawn": _respawn, "give": _give, "take": _take, "position": _position}

# Pairs whose plans read or write the same bytes against ORIGINAL RAM: in one call the later one clobbers the earlier.
_CONFLICTS = (("give", "take"), ("heal", "set_hp"), ("heal", "set_level"), ("set_hp", "set_level"))


def apply(emu, edits: dict, *, max_pp=None, base_stats=None) -> list[tuple[int, int, int]]:
    """Validate EVERY edit first (raise SurgeryError before the first write), then write.

    Returns the writes applied as [(addr, old_byte, new_byte)] in order (only bytes whose value changed)."""
    if not isinstance(edits, dict) or not edits:
        raise SurgeryError("empty edit dict")
    for a, b in _CONFLICTS:
        if a in edits and b in edits:
            raise SurgeryError(f"{a} and {b} cannot be combined in one edit (they clobber each other); "
                               f"run them as two sequential edits")
    ctx = _Ctx(max_pp, base_stats if base_stats is not None else stats.base_stats_of)
    plan: list[tuple[int, int]] = []
    for name, value in edits.items():
        fn = _PLAN.get(name)
        if fn is None:
            raise SurgeryError(f"unknown field: {name}")
        plan += fn(emu, value, ctx)
    writes = []
    for addr, new in plan:
        old = emu.read(addr)
        new &= 0xFF
        if old != new:
            emu.write(addr, new)
            writes.append((addr, old, new))
    return writes
