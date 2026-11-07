"""Legality: is this RAM state one the game could have produced? Read-only checks against the ROM-drained tables.

``check`` reads a loaded emulator and reports violations (bytes the game could never write), warnings (checks that are
unverified or whose table is missing) and the invariants that ran. It never writes RAM or a sidecar and never raises:
a read failure is a ``read:`` violation. ``kb`` is the ``kb/rom_tables.json`` dict, ``catalog`` the ``kb/items.json``
dict, ``hm`` the ``hm_compat`` table and ``rom`` the ROM bytes (only the walk-grid check uses them). Without ``kb``
the table-dependent invariants do not run - a ``no kb`` warning, never a violation.

Invariants: party_structure, party_stats, party_exp, party_moves, party_pp, party_evolution (party);
bag, money, badges, key_items, world, pokedex (world). Unverified checks are always WARNINGS: gym-beaten flags, TM
moves (there is no TM compatibility table in the repo), the S.S. Ticket flag, the map-view pointer, evolution pending.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent import statefp
from pokeagent.atlas import rom_maps
from pokeagent.atlas.walkgrid import walk_grid
from pokeagent.explorer import stats
from pokeagent.grind.xpmath import exp_for_level
from pokeagent.novelty.discoveries import odd_map
from pokeagent.ramstructs import (BAG_CAPACITY, BAG_COUNT, MAX_PARTY, PARTY_COUNT, PARTY_MON_SIZE, PARTY_MON1,
                                  decode_party_mon)
from pokeagent.ramworld import POKEDEX_BYTES, POKEDEX_OWNED, POKEDEX_SEEN

PARTY_SPECIES = 0xD164       # wPartySpecies: the 0xFF-terminated species list mirroring the party structs

MAP, Y, X, BADGES, MONEY, RESPAWN = statefp.MAP, statefp.Y, statefp.X, statefp.BADGES, statefp.MONEY, statefp.RESPAWN
EVENT_HM01 = 0xD803          # bit 0 = got HM01 (verified, campaign.json 'hm01_cut'); bit 1 = captain's back rubbed
VIEW_PTR = 0xD35F            # wCurrentTileBlockMapViewPointer (unverified in ram_map.json)
HM01_ITEM, SS_TICKET = 0xC4, 0x3F
CATALOG_MAX, HM_LO, TM_HI = 83, 0xC4, 0xFA
MAX_PP_FORMULA = 61          # the game's own PP formula caps boosted PP at 61
MONEY_MAX = 999999
# move-name -> hm_compat key (HMs ONLY: there is no TM compatibility table, so other moves can only warn)
HM_MOVE = {"CUT": "cut", "FLY": "fly", "SURF": "surf", "STRENGTH": "strength", "FLASH": "flash"}

PARTY_TABLE_INVARIANTS = ("party_stats", "party_exp", "party_moves", "party_pp", "party_evolution")


@dataclass(frozen=True)
class Legality:
    ok: bool                       # no violations (warnings do not fail)
    violations: list[str]          # "<invariant>: <what> (bytes ...)"
    warnings: list[str]            # unverifiable or unverified checks
    checked: list[str]             # invariant names that actually ran


def expected_view_pointer(map_w: int, x: int, y: int) -> int | None:
    """The (map, x, y) -> wCurrentTileBlockMapViewPointer (0xD35F) relation. NOT derived anywhere in the repo, so it
    returns None: the controller derives it from organic states afterwards and fills this hook in."""
    return None


class _C:
    """One check run: the emulator, the tables, and the collected verdicts."""

    def __init__(self, emu, kb, catalog, hm, rom):
        self.emu, self.kb, self.rom = emu, kb or {}, rom
        self.catalog = (catalog or {}).get("items") or {}
        self.hms = (hm or {}).get("hms", hm or {})
        self.violations: list[str] = []
        self.warnings: list[str] = []

    def species_row(self, species: int) -> tuple[dict | None, int]:
        """(species_by_dex row, dex number) for an internal species id; (None, 0) when unknown."""
        dex = int(self.kb.get("dex_of_internal", {}).get(str(species), 0) or 0)
        row = self.kb.get("species_by_dex", {}).get(str(dex))
        return row, dex

    def pre_forms(self, name: str) -> list[str]:
        """Species names that evolve (transitively) into ``name``, per learnsets[*].evolves walked backwards."""
        out, frontier = [], [name]
        while frontier:
            n = frontier.pop()
            for prev, row in self.kb.get("learnsets", {}).items():
                if prev in out or prev == name:
                    continue
                if any(e.get("into") == n for e in row.get("evolves") or []):
                    out.append(prev)
                    frontier.append(prev)
        return out

    def _finish(self, name: str, fn) -> str | None:
        """Run one invariant; a read failure becomes a ``read:`` violation, never an exception."""
        try:
            fn(self)
        except Exception as e:  # noqa: BLE001 - a failed read is evidence of a bad state, not a crash
            self.violations.append(f"read: {name} ({e!r})")
        return name


def _party_structure(c: _C) -> None:
    n = c.emu.read(PARTY_COUNT)
    if not 1 <= n <= MAX_PARTY:
        c.violations.append(f"party_structure: count 0x{PARTY_COUNT:04X} = {n} (want 1..{MAX_PARTY})")
        return
    listed = c.emu.read_range(PARTY_SPECIES, n + 1)
    raw = c.emu.read_range(PARTY_MON1, PARTY_MON_SIZE * n)
    if listed[n] != 0xFF:
        c.violations.append(f"party_structure: species list terminator 0x{PARTY_SPECIES + n:04X} = {listed[n]:#04x} (want 0xFF)")
    for i in range(n):
        mon = decode_party_mon(raw[i * PARTY_MON_SIZE:(i + 1) * PARTY_MON_SIZE])
        base = PARTY_MON1 + i * PARTY_MON_SIZE
        if listed[i] != mon.species:
            c.violations.append(f"party_structure: slot {i} species list 0x{PARTY_SPECIES + i:04X} = {listed[i]:#04x} "
                                f"but struct 0x{base:04X} = {mon.species:#04x}")
        if c.kb and str(mon.species) not in c.kb.get("name_of_internal", {}):
            c.violations.append(f"party_structure: slot {i} species {mon.species:#04x} not a valid internal id")
        if not 1 <= mon.level <= 100:
            c.violations.append(f"party_structure: slot {i} level 0x{base + 33:04X} = {mon.level} (want 1..100)")
        if mon.box_level != mon.level:
            c.violations.append(f"party_structure: slot {i} box level 0x{base + 3:04X} = {mon.box_level} "
                                f"!= level 0x{base + 33:04X} = {mon.level}")
        if mon.max_hp < 1:
            c.violations.append(f"party_structure: slot {i} max HP 0x{base + 34:04X}..{base + 35:04X} = {mon.max_hp} (want >= 1)")
        elif mon.hp > mon.max_hp:
            c.violations.append(f"party_structure: slot {i} HP {mon.hp} > max HP {mon.max_hp}")


def _band(c: _C, i: int, mon, name: str) -> None:
    """party_stats: stored stats must lie in [formula(se=0), formula(se=mon's)] - Gen 1 lazily applies stat exp."""
    row, _dex = c.species_row(mon.species)
    if not row:
        c.warnings.append(f"party_stats: slot {i} species {mon.species:#04x} has no base stats")
        return
    base = {k: int(row[v]) for k, v in stats.KB_KEYS.items()}
    d, sx = stats.dvs(mon), stats.stat_exp(mon)
    stored = dict(zip(stats.STAT_KEYS, (mon.max_hp, *mon.stats)))
    addr = PARTY_MON1 + i * PARTY_MON_SIZE + 34
    for k in stats.STAT_KEYS:
        lo = stats.stat_value(base[k], d[k], 0, mon.level, hp=(k == "hp"))
        hi = stats.stat_value(base[k], d[k], sx[k], mon.level, hp=(k == "hp"))
        if not lo <= stored[k] <= hi:
            c.violations.append(f"party_stats: slot {i} {name} {k} 0x{addr:04X}..{addr + 1:04X} = {stored[k]}, "
                                f"formula band {lo}..{hi}")
        addr += 2


def _party_stats(c: _C) -> None:
    for i, mon in enumerate(_party(c)):
        _band(c, i, mon, "stat")


def _party_exp(c: _C) -> None:
    for i, mon in enumerate(_party(c)):
        row, _dex = c.species_row(mon.species)
        growth = (row or {}).get("growth")
        if growth is None:
            c.warnings.append(f"party_exp: slot {i} species {mon.species:#04x} has no growth group")
            continue
        lo = exp_for_level(growth, mon.level)
        base = PARTY_MON1 + i * PARTY_MON_SIZE + 14
        if mon.level >= 100:
            ok = mon.exp <= exp_for_level(growth, 100)
        else:
            ok = lo <= mon.exp < exp_for_level(growth, mon.level + 1)
        if not ok:
            c.violations.append(f"party_exp: slot {i} exp 0x{base:04X}..{base + 2:04X} = {mon.exp} "
                                f"outside {growth} L{mon.level} band")


def _move_name(c: _C, move_id: int) -> str:
    return (c.kb.get("moves", {}).get(str(move_id)) or {}).get("name", f"#{move_id}")


def _learnable(c: _C, mon) -> set[str]:
    """Move names provable for this mon: moves1 + level-up learnsets of it and its pre-evolutions at <= its level,
    plus HMs it can learn. TMs cannot be proven (no TM table): unlisted moves are warnings, not violations."""
    row, _dex = c.species_row(mon.species)
    name = (row or {}).get("name", "")
    out: set[str] = set()
    chain = {name, *c.pre_forms(name)}
    learnsets = c.kb.get("learnsets", {})
    for who in chain:
        for lv, mv in (learnsets.get(who) or {}).get("learnset") or []:
            if lv <= mon.level:
                out.add(mv)
    for drow in c.kb.get("species_by_dex", {}).values():
        if drow.get("name") in chain:
            out |= set(drow.get("moves1") or [])
    for move_name, hm_key in HM_MOVE.items():
        if name in (c.hms.get(hm_key) or ()):
            out.add(move_name)
    return out


def _party_moves(c: _C) -> None:
    for i, mon in enumerate(_party(c)):
        learnable = _learnable(c, mon)
        seen_zero = False
        for j, mv in enumerate(mon.moves):
            base = PARTY_MON1 + i * PARTY_MON_SIZE + 8
            if not mv:
                seen_zero = True
                continue
            if seen_zero:
                c.violations.append(f"party_moves: slot {i} move {j} 0x{base + j:04X} non-zero after an empty move slot")
            if str(mv) not in c.kb.get("moves", {}):
                c.violations.append(f"party_moves: slot {i} move {j} 0x{base + j:04X} = {mv:#04x} not in the moves table")
            elif _move_name(c, mv) not in learnable:
                c.warnings.append(f"party_moves: slot {i} move {_move_name(c, mv)} not provable "
                                  f"(TM/other source; no TM table)")


def _party_pp(c: _C) -> None:
    for i, mon in enumerate(_party(c)):
        for j, (mv, pp) in enumerate(zip(mon.moves, mon.pp)):
            base = PARTY_MON1 + i * PARTY_MON_SIZE + 29
            if not mv:
                if pp:
                    c.violations.append(f"party_pp: slot {i} move {j} is empty but PP 0x{base + j:04X} = {pp:#04x}")
                continue
            row = c.kb.get("moves", {}).get(str(mv)) or {}
            try:
                base_pp = int(row["pp"])
            except (KeyError, TypeError, ValueError):
                continue  # no PP to judge by (an unknown move id is already a party_moves violation)
            ups, have = pp >> 6, pp & 63
            allowed = min(MAX_PP_FORMULA, base_pp + ups * (base_pp // 5))
            if have > allowed:
                c.violations.append(f"party_pp: slot {i} move {j} PP 0x{base + j:04X} = {have} + {ups} ups "
                                    f"(max {allowed} for base {base_pp})")


def _party_evolution(c: _C) -> None:
    learnsets = c.kb.get("learnsets", {})
    for i, mon in enumerate(_party(c)):
        row, _dex = c.species_row(mon.species)
        name = (row or {}).get("name", "")
        for e in (learnsets.get(name) or {}).get("evolves") or []:  # this mon can still evolve by level: pending
            if e.get("how") == "level" and mon.level >= int(e.get("level", 0)):
                c.warnings.append(f"party_evolution: slot {i} {name} L{mon.level} >= {e['level']}: evolution pending")
        for prev, prow in learnsets.items():                        # evolved form below its pre-form's level: illegal
            for e in prow.get("evolves") or []:
                if e.get("how") == "level" and e.get("into") == name and mon.level < int(e.get("level", 0)):
                    c.violations.append(f"party_evolution: slot {i} {name} L{mon.level} < {e['level']} "
                                        f"({prev} evolves by level)")


def _bag(c: _C) -> None:
    n = c.emu.read(BAG_COUNT)
    if n > BAG_CAPACITY:
        c.violations.append(f"bag: count 0x{BAG_COUNT:04X} = {n} (max {BAG_CAPACITY})")
        return
    raw = c.emu.read_range(BAG_COUNT + 1, 2 * n + 1)
    if raw[2 * n] != 0xFF:
        c.violations.append(f"bag: terminator 0x{BAG_COUNT + 1 + 2 * n:04X} = {raw[2 * n]:#04x} (want 0xFF)")
    if not c.catalog:
        c.warnings.append("bag: no items catalog; item ids checked by range only")
    seen = set()
    for i in range(n):
        item, qty = raw[2 * i], raw[2 * i + 1]
        in_range = 1 <= item <= CATALOG_MAX or HM_LO <= item <= TM_HI
        known = (str(item) in c.catalog or HM_LO <= item <= TM_HI) if c.catalog else in_range
        if not known:
            c.violations.append(f"bag: item id 0x{BAG_COUNT + 2 + 2 * i:04X} = {item:#04x} not in the catalog "
                                f"(1..{CATALOG_MAX} or {HM_LO:#04x}..{TM_HI:#04x})")
        if not 1 <= qty <= 99:
            c.violations.append(f"bag: qty 0x{BAG_COUNT + 3 + 2 * i:04X} = {qty} (want 1..99)")
        if item in seen:
            c.violations.append(f"bag: duplicate item id {item:#04x} (slots merge in the real game)")
        seen.add(item)


def _money(c: _C) -> None:
    raw = c.emu.read_range(MONEY, 3)
    if not all((b >> 4) <= 9 and (b & 15) <= 9 for b in raw):
        c.violations.append(f"money: 0x{MONEY:04X}..{MONEY + 2:04X} = {raw.hex()} not BCD")
    elif int("".join(f"{b:02x}" for b in raw)) > MONEY_MAX:
        c.violations.append(f"money: 0x{MONEY:04X}..{MONEY + 2:04X} over {MONEY_MAX}")


def _badges(c: _C) -> None:
    c.emu.read(BADGES)   # the byte is read and the invariant checked in; the gym flags are unverified -> warning only
    c.warnings.append("badges: gym-beaten flags unverified")


def _key_items(c: _C) -> None:
    ids = {c.emu.read(BAG_COUNT + 1 + 2 * i) for i in range(min(c.emu.read(BAG_COUNT), BAG_CAPACITY))}
    if HM01_ITEM in ids and not c.emu.read(EVENT_HM01) & 1:
        c.violations.append(f"key_items: HM01 (0xC4) in bag but 0x{EVENT_HM01:04X} bit0 clear")
    if SS_TICKET in ids:
        c.warnings.append("key_items: S.S. Ticket in bag but its event flag is unknown (unverified)")


def _world(c: _C) -> None:
    m, x, y, respawn = c.emu.read(MAP), c.emu.read(X), c.emu.read(Y), c.emu.read(RESPAWN)
    if odd_map(m):
        c.violations.append(f"world: glitch map 0x{MAP:04X} = {m:#04x}")
    if not 0 <= respawn <= 10:
        c.violations.append(f"world: respawn 0x{RESPAWN:04X} = {respawn} not a town id (0..10)")
    hd = None
    if c.rom is None:
        c.warnings.append("world: walk check skipped: no rom")
    else:
        try:
            hd = rom_maps.header(c.rom, m) if rom_maps.is_sane(c.rom, m) else None
        except Exception:  # noqa: BLE001
            hd = None
        if hd is None:
            c.warnings.append(f"world: walk check skipped (no ROM header for map {m:#04x})")
        elif not (0 <= x < hd.w * 2 and 0 <= y < hd.h * 2):
            c.violations.append(f"world: (x,y) = ({x},{y}) outside map {m:#04x} ({hd.w * 2}x{hd.h * 2})")
        elif not walk_grid(c.rom, hd)[y][x]:
            c.violations.append(f"world: ({x},{y}) not walkable on map {m:#04x}")
    if expected_view_pointer(hd.w if hd else 0, x, y) is None:
        c.warnings.append("world: view pointer relation unverified")


def _pokedex(c: _C) -> None:
    owned = {i + 1 for i in range(POKEDEX_BYTES * 8)
             if c.emu.read(POKEDEX_OWNED + i // 8) & (1 << (i % 8))}
    seen = {i + 1 for i in range(POKEDEX_BYTES * 8)
            if c.emu.read(POKEDEX_SEEN + i // 8) & (1 << (i % 8))}
    owned, seen = {i for i in owned if i <= 151}, {i for i in seen if i <= 151}
    if owned - seen:
        c.violations.append(f"pokedex: owned {sorted(owned - seen)} not seen (owned is a subset of seen)")
    if not c.kb:
        return
    for i, mon in enumerate(_party(c)):
        _row, dex = c.species_row(mon.species)
        if dex and dex not in owned:
            c.violations.append(f"pokedex: slot {i} species {mon.species:#04x} (dex {dex}) not owned")


def _party(c: _C) -> list:
    n = c.emu.read(PARTY_COUNT)
    if not 1 <= n <= MAX_PARTY:
        return []
    raw = c.emu.read_range(PARTY_MON1, PARTY_MON_SIZE * n)
    return [decode_party_mon(raw[i * PARTY_MON_SIZE:(i + 1) * PARTY_MON_SIZE]) for i in range(n)]


_INVARIANTS = {"party_structure": _party_structure, "party_stats": _party_stats, "party_exp": _party_exp,
               "party_moves": _party_moves, "party_pp": _party_pp, "party_evolution": _party_evolution,
               "bag": _bag, "money": _money, "badges": _badges, "key_items": _key_items,
               "world": _world, "pokedex": _pokedex}


def check(emu, kb: dict | None, *, catalog: dict | None = None, hm: dict | None = None,
          rom: bytes | None = None) -> Legality:
    """Read-only legality verdict for the state ``emu`` is standing in (never writes, never raises)."""
    c = _C(emu, kb, catalog, hm, rom)
    if kb is None:
        c.warnings.append("no kb: party tables skipped")
    checked = []
    for name, fn in _INVARIANTS.items():
        if kb is None and name in PARTY_TABLE_INVARIANTS:
            continue
        checked.append(c._finish(name, fn))
    return Legality(not c.violations, c.violations, c.warnings, checked)
