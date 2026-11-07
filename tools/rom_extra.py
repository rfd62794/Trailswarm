"""Species base data extras, learnsets / evolutions and items, drained from the cartridge (called by rom_tables.py).

Offsets (pret/pokered pokered.sym, file offset = bank*0x4000 + addr - 0x4000):
  0e:43de BaseStats   28 bytes / species (dex order): dex, hp, atk, def, spd, spc, type1, type2, catch, exp, sprite size,
                      front ptr(2), back ptr(2), level-1 moves(4) @15, growth rate @19, TM/HM flags(7) @20
  0e:705c EvosMovesPointerTable  190 x 2-byte pointers (INTERNAL id order, bank 0e): evolutions then learnset
                      evolution: [1 level, to] / [2 item, min level, to] / [3 trade, level, to]; 0 ends; learnset: (level, move)..., 0 ends
  01:4608 ItemPrices  3-byte BCD per item id (1-based);  01:472b ItemNames  0x50-terminated, item id order
"""
from __future__ import annotations

GROWTH = {0: "MEDIUM_FAST", 3: "MEDIUM_SLOW", 4: "FAST", 5: "SLOW"}
EVO_HOW = {1: "level", 2: "item", 3: "trade"}


def off(bank: int, addr: int) -> int:
    return bank * 0x4000 + (addr - 0x4000)


def base_extras(data: bytes, species: dict, move_names: dict, dex_of: dict, mon_names: dict) -> None:
    """Add name / moves1 / growth to each species_by_dex row in place."""
    internal_of = {d: i for i, d in dex_of.items()}
    p = off(0x0E, 0x43DE)
    for dex, row in species.items():
        s = data[p + 28 * (dex - 1):p + 28 * dex]
        row["name"] = mon_names.get(internal_of.get(dex), f"#{dex}")
        row["moves1"] = [move_names[m] for m in s[15:19] if m in move_names]
        row["growth"] = GROWTH.get(s[19], str(s[19]))


def learnsets(data: bytes, mon_names: dict, move_names: dict, item_names: dict) -> dict:
    """{species name: {"evolves": [{how, level|item, into}], "learnset": [[level, move], ...]}} for internal ids with data."""
    table = off(0x0E, 0x705C)
    out = {}
    for internal in range(1, 191):
        name = mon_names.get(internal, "")
        if not name or name.startswith("MISSINGNO") or name == "?":
            continue
        ptr = data[table + 2 * (internal - 1)] | data[table + 2 * (internal - 1) + 1] << 8
        q = off(0x0E, ptr)
        evo = []
        while data[q] != 0:
            how = EVO_HOW.get(data[q], str(data[q]))
            if how == "item":
                evo.append({"how": how, "item": item_names.get(data[q + 1], str(data[q + 1])), "level": data[q + 2],
                            "into": mon_names.get(data[q + 3], "?")}); q += 4
            else:
                evo.append({"how": how, "level": data[q + 1], "into": mon_names.get(data[q + 2], "?")}); q += 3
        q += 1
        learn = []
        while data[q] != 0:
            learn.append([data[q], move_names.get(data[q + 1], f"move{data[q + 1]}")]); q += 2
        out[name] = {"evolves": evo, "learnset": learn}
    return out


def items(data: bytes, text) -> dict:
    """{item id: {"name", "price"}} - names until the first non-item gap, price from 3-byte BCD."""
    names, cur, p = {}, b"", off(0x01, 0x472B)
    i = 1
    while i <= 83:
        end = data.index(0x50, p)
        names[i] = text(data[p:end + 1]); p = end + 1; i += 1
    out = {}
    q = off(0x01, 0x4608)
    for i, n in names.items():
        b = data[q + 3 * (i - 1):q + 3 * i]
        price = int(f"{b[0]:02x}{b[1]:02x}{b[2]:02x}")
        out[i] = {"name": n, "price": price}
    return out
