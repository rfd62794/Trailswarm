"""Wild encounter tables, trainer parties and per-map trainer placement, drained from the cartridge (called by rom_tables.py).

Offsets (pret/pokered pokered.sym, file offset = bank*0x4000 + addr - 0x4000):
  03:4eeb WildDataPointers   2-byte pointer per MAP ID (bank 3) -> grass rate, 10 x (level, species) if rate != 0, then water the same
  0e:59ff TrainerNames       0x50-terminated, trainer class order (class 1 = YOUNGSTER ...)
  0e:5d3b TrainerDataPointers 47 x 2-byte pointers (bank 0e) -> that class's parties back to back, each ending in 0:
                             level, species... (one level for all)  or  0xFF, (level, species)... (level per mon)
                             a class ends where the next higher pointer begins; TrainerAI starts at 0e:652e
  map object data (see rom_maps.py): after the warps come signs (3 bytes each) then objects (6 bytes: sprite, y, x, movement,
                             range, text id); text id bit 6 = trainer, followed by (200 + trainer class, party number 1-based)
"""
from __future__ import annotations

PTRS, BANKS = 0x01AE, 0xC23D
DATA_END = 0x652E  # TrainerAI, the first byte after LanceData


def off(bank: int, addr: int) -> int:
    return bank * 0x4000 + (addr - 0x4000)


def wild(data: bytes, mon_names: dict) -> dict:
    """{map id: {"grass_rate", "grass": [[level, species]*10], "water_rate", "water": [...]}} for maps with any encounters."""
    out = {}
    for m in range(248):
        ptr = data[off(3, 0x4EEB) + 2 * m] | data[off(3, 0x4EEB) + 2 * m + 1] << 8
        q = off(3, ptr)
        row = {}
        for kind in ("grass", "water"):
            rate = data[q]; q += 1
            row[f"{kind}_rate"] = rate
            if rate:
                row[kind] = [[data[q + 2 * k], mon_names.get(data[q + 2 * k + 1], "?")] for k in range(10)]
                q += 20
        if row["grass_rate"] or row["water_rate"]:
            out[m] = row
    return out


def trainer_classes(data: bytes) -> list[str]:
    from rom_tables import text
    names, p = [], off(0x0E, 0x59FF)
    for _ in range(47):
        end = data.index(0x50, p)
        names.append(text(data[p:end + 1])); p = end + 1
    return names


def trainers(data: bytes, mon_names: dict) -> dict:
    """{class name: [party, ...]} with party = [[level, species], ...] in party-number order (party 1 is index 0)."""
    names = trainer_classes(data)
    ptrs = [data[off(0x0E, 0x5D3B) + 2 * i] | data[off(0x0E, 0x5D3B) + 2 * i + 1] << 8 for i in range(47)]
    out = {}
    for i, name in enumerate(names):
        start = ptrs[i]
        later = [p for p in ptrs if p > start] + [DATA_END]
        end = min(later)
        if i + 1 < 47 and ptrs[i + 1] == start:
            out[name] = []  # unused twin (JUGGLER/FISHER, CHIEF/SCIENTIST share data; the later class owns it)
            continue
        q, stop, parties = off(0x0E, start), off(0x0E, end), []
        while q < stop:
            party = []
            if data[q] == 0xFF:
                q += 1
                while data[q] != 0:
                    party.append([data[q], mon_names.get(data[q + 1], "?")]); q += 2
            else:
                lvl = data[q]; q += 1
                while data[q] != 0:
                    party.append([lvl, mon_names.get(data[q], "?")]); q += 1
            q += 1
            parties.append(party)
        out[name] = parties
    return out


def map_trainers(data: bytes, class_names: list[str]) -> dict:
    """{map id: [{"class", "party", "x", "y"}]} for every map with trainer objects."""
    out = {}
    for m in range(248):
        b, ptr = data[BANKS + m], data[PTRS + 2 * m] | data[PTRS + 2 * m + 1] << 8
        if not 0 < b < 0x40 or ptr < 0x4000:
            continue
        o = b * 0x4000 + ptr - 0x4000
        q = o + 10 + 11 * sum(1 for bit in (8, 4, 2, 1) if data[o + 9] & bit)
        oo = b * 0x4000 + (data[q] | data[q + 1] << 8) - 0x4000
        if oo <= 0 or oo + 2 >= len(data):
            continue
        p = oo + 2 + 4 * data[oo + 1]
        p += 1 + 3 * data[p]
        found = []
        n, p = data[p], p + 1
        for _ in range(n):
            tx, ty, text_id = data[p + 2], data[p + 1], data[p + 5]
            p += 6
            if text_id & 0x40:
                cls, party = data[p] - 200, data[p + 1]; p += 2
                if 1 <= cls <= 47:
                    found.append({"class": class_names[cls - 1], "party": party, "x": tx - 4, "y": ty - 4})
            elif text_id & 0x80:
                p += 1
        if found:
            out[m] = found
    return out
