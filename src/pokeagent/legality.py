"""Legality: is this RAM state one the game could have produced? Read-only checks against the ROM-drained tables.

``check`` reads a loaded emulator and reports violations (bytes the game could never write), warnings (checks that are
unverified or whose table is missing) and the invariants that ran. It never writes RAM or a sidecar and never raises:
a read failure is a ``read:`` violation. ``kb`` is the ``kb/rom_tables.json`` dict, ``catalog`` the ``kb/items.json``
dict, ``hm`` the ``hm_compat`` table and ``rom`` the ROM bytes (only the walk-grid check uses them). Without ``kb``
the table-dependent invariants do not run - a ``no kb`` warning, never a violation.

Invariants: party_structure, party_stats, party_exp, party_moves, party_pp, party_evolution (party, in
legality_party); bag, money, badges, key_items, world, pokedex (here). Unverified checks are always WARNINGS:
gym-beaten flags, TM moves (there is no TM compatibility table in the repo), the S.S. Ticket flag, the map-view
pointer, evolution pending.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent import legality_party as party
from pokeagent import statefp
from pokeagent.atlas import rom_maps
from pokeagent.atlas.walkgrid import walk_grid
from pokeagent.novelty.discoveries import odd_map
from pokeagent.ramstructs import BAG_CAPACITY, BAG_COUNT
from pokeagent.ramworld import POKEDEX_BYTES, POKEDEX_OWNED, POKEDEX_SEEN

MAP, Y, X, BADGES, MONEY, RESPAWN = statefp.MAP, statefp.Y, statefp.X, statefp.BADGES, statefp.MONEY, statefp.RESPAWN
EVENT_HM01 = 0xD803          # bit 0 = got HM01 (verified, campaign.json 'hm01_cut'); bit 1 = captain's back rubbed
VIEW_PTR = 0xD35F            # wCurrentTileBlockMapViewPointer (unverified in ram_map.json)
HM01_ITEM, SS_TICKET = 0xC4, 0x3F
CATALOG_MAX, HM_LO, TM_HI = 83, 0xC4, 0xFA
MONEY_MAX = 999999

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
    for i, mon in enumerate(party._party(c)):
        _row, dex = c.species_row(mon.species)
        if dex and dex not in owned:
            c.violations.append(f"pokedex: slot {i} species {mon.species:#04x} (dex {dex}) not owned")


_INVARIANTS = {"party_structure": party.party_structure, "party_stats": party.party_stats,
               "party_exp": party.party_exp, "party_moves": party.party_moves, "party_pp": party.party_pp,
               "party_evolution": party.party_evolution,
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
