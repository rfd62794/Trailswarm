"""Party invariants for ``pokeagent.legality.check`` (split out to keep each module under 300 lines).

Each function takes the check run's ``_C`` context (emulator, ROM tables, collected verdicts) and appends
violations/warnings; a species with no table row warns rather than fails (the tables can only prove, not accuse).
"""
from __future__ import annotations

from pokeagent.explorer import stats
from pokeagent.grind.xpmath import exp_for_level
from pokeagent.ramstructs import MAX_PARTY, PARTY_COUNT, PARTY_MON_SIZE, PARTY_MON1, decode_party_mon

PARTY_SPECIES = 0xD164       # wPartySpecies: the 0xFF-terminated species list mirroring the party structs
MAX_PP_FORMULA = 61          # the game's own PP formula caps boosted PP at 61
# move-name -> hm_compat key (HMs ONLY: there is no TM compatibility table, so other moves can only warn)
HM_MOVE = {"CUT": "cut", "FLY": "fly", "SURF": "surf", "STRENGTH": "strength", "FLASH": "flash"}


def _party(c) -> list:
    n = c.emu.read(PARTY_COUNT)
    if not 1 <= n <= MAX_PARTY:
        return []
    raw = c.emu.read_range(PARTY_MON1, PARTY_MON_SIZE * n)
    return [decode_party_mon(raw[i * PARTY_MON_SIZE:(i + 1) * PARTY_MON_SIZE]) for i in range(n)]


def party_structure(c) -> None:
    """Count, species list and per-mon structure. Box level (struct offset +3) is deliberately NOT checked: the ROM
    validation (114 organic states, 161 party mons) found it 0 for every party mon, starters and fresh catches
    included. In Gen 1 that byte only means something for boxed mons, so comparing it to the level false-flagged 94
    legal states. A transient save (species list written, struct still empty) is a violation: not a resume point."""
    n = c.emu.read(PARTY_COUNT)
    if n > MAX_PARTY:
        c.violations.append(f"party_structure: count 0x{PARTY_COUNT:04X} = {n} (want 0..{MAX_PARTY})")
        return
    listed = c.emu.read_range(PARTY_SPECIES, n + 1)
    if n == 0:   # the bedroom start is organic with an empty party: only the (empty) species list must be sane
        if listed[0] not in (0x00, 0xFF):
            c.violations.append(f"party_structure: empty party but species list 0x{PARTY_SPECIES:04X} = {listed[0]:#04x} (want 0xFF or 0)")
        return
    raw = c.emu.read_range(PARTY_MON1, PARTY_MON_SIZE * n)
    if listed[n] != 0xFF:
        c.violations.append(f"party_structure: species list terminator 0x{PARTY_SPECIES + n:04X} = {listed[n]:#04x} (want 0xFF)")
    for i in range(n):
        mon = decode_party_mon(raw[i * PARTY_MON_SIZE:(i + 1) * PARTY_MON_SIZE])
        base = PARTY_MON1 + i * PARTY_MON_SIZE
        if listed[i] != mon.species and mon.species == 0:
            c.violations.append(f"party_structure: slot {i} transient save (struct empty): not a usable resume point "
                                f"(species list 0x{PARTY_SPECIES + i:04X} = {listed[i]:#04x}, struct 0x{base:04X} = 0)")
        elif listed[i] != mon.species:
            c.violations.append(f"party_structure: slot {i} species list 0x{PARTY_SPECIES + i:04X} = {listed[i]:#04x} "
                                f"but struct 0x{base:04X} = {mon.species:#04x}")
        if c.kb and str(mon.species) not in c.kb.get("name_of_internal", {}):
            c.violations.append(f"party_structure: slot {i} species {mon.species:#04x} not a valid internal id")
        if not 1 <= mon.level <= 100:
            c.violations.append(f"party_structure: slot {i} level 0x{base + 33:04X} = {mon.level} (want 1..100)")
        if mon.max_hp < 1:
            c.violations.append(f"party_structure: slot {i} max HP 0x{base + 34:04X}..{base + 35:04X} = {mon.max_hp} (want >= 1)")
        elif mon.hp > mon.max_hp:
            c.violations.append(f"party_structure: slot {i} HP {mon.hp} > max HP {mon.max_hp}")


def _band(c, i: int, mon) -> None:
    """Stored stats must lie in [formula(se=0), formula(se=mon's)]: Gen 1 lazily applies stat exp."""
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
            c.violations.append(f"party_stats: slot {i} {k} 0x{addr:04X}..{addr + 1:04X} = {stored[k]}, "
                                f"formula band {lo}..{hi}")
        addr += 2


def party_stats(c) -> None:
    for i, mon in enumerate(_party(c)):
        _band(c, i, mon)


def party_exp(c) -> None:
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


def _move_name(c, move_id: int) -> str:
    return (c.kb.get("moves", {}).get(str(move_id)) or {}).get("name", f"#{move_id}")


def _learnable(c, mon) -> set[str]:
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


def party_moves(c) -> None:
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


def party_pp(c) -> None:
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


def party_evolution(c) -> None:
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
