"""Drain the cartridge for battle knowledge: moves, type chart, base stats, names -> kb/rom_tables.json.

    uv run python tools/rom_tables.py            # reads roms/Pokemon Red.gb, writes kb/rom_tables.json, prints checks

Offsets come from pret's pokered.sym (bank:addr -> file offset = bank*0x4000 + (addr - 0x4000)):
  0e:4000 Moves        6 bytes per move: animation(=id), effect, power, type, accuracy, pp
  0f:6474 TypeEffects  triplets (attacker type, defender type, effect x10: 0/5/20), 0xFF terminator
  0e:43de BaseStats    28 bytes per species in POKEDEX order: dex, hp, atk, def, spd, spc, type1, type2, catch, exp, ...
  2c:4000 MoveNames    0x50-terminated names, in move id order
  07:421e MonsterNames 10 bytes each, fixed width, in INTERNAL id order (the byte at 0xD16B / 0xCFE5)
  10:5024 PokedexOrder internal id -> dex number (1-based), 190 entries
Extras (species names/level-1 moves/growth, learnsets + evolutions, wild tables, trainer parties, items) come from
rom_extra.py and rom_world.py; their offsets are in those docstrings and in docs/KNOWLEDGE.md. The file is written ONLY if
every check passes. Checks printed: Scratch power 40 / Tackle 35 / Ember 40, Fire vs Grass 2x, Charmander base HP 39 and types.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.screentext import CHARMAP  # noqa: E402
import rom_extra, rom_world  # noqa: E402  (tools/ is on sys.path when run as a script)

TYPES = {0: "NORMAL", 1: "FIGHTING", 2: "FLYING", 3: "POISON", 4: "GROUND", 5: "ROCK", 7: "BUG", 8: "GHOST",
         20: "FIRE", 21: "WATER", 22: "GRASS", 23: "ELECTRIC", 24: "PSYCHIC", 25: "ICE", 26: "DRAGON"}


def off(bank: int, addr: int) -> int:
    return bank * 0x4000 + (addr - 0x4000)


def text(raw: bytes) -> str:
    out = ""
    for b in raw:
        if b == 0x50:
            break
        out += CHARMAP.get(b, "?")
    return out.strip()


def main(rom="roms/Pokemon Red.gb", out="kb/rom_tables.json") -> int:
    data = Path(rom).read_bytes()
    moves = {}
    p = off(0x0E, 0x4000)
    names_p = off(0x2C, 0x4000)
    names = []
    cur = b""
    for b in data[names_p:names_p + 4000]:
        if b == 0x50:
            names.append(text(cur)); cur = b""
            if len(names) >= 165:
                break
        else:
            cur += bytes([b])
    for i in range(165):
        anim, effect, power, typ, acc, pp = data[p + 6 * i:p + 6 * i + 6]
        moves[i + 1] = {"name": names[i] if i < len(names) else f"move{i + 1}", "effect": effect, "power": power,
                        "type": TYPES.get(typ, str(typ)), "accuracy": round(acc / 255, 2), "pp": pp}
    chart = []
    p = off(0x0F, 0x6474)
    while data[p] != 0xFF:
        a, d, e = data[p:p + 3]; chart.append([TYPES.get(a, str(a)), TYPES.get(d, str(d)), e / 10]); p += 3
    dex_of = {}
    p = off(0x10, 0x5024)
    for internal in range(1, 191):
        dex_of[internal] = data[p + internal - 1]
    mon_names = {}
    p = off(0x07, 0x421E)
    for internal in range(1, 191):
        mon_names[internal] = text(data[p + 10 * (internal - 1):p + 10 * internal] + b"\x50")
    species = {}
    p = off(0x0E, 0x43DE)
    for dex in range(1, 151):
        s = data[p + 28 * (dex - 1):p + 28 * dex]
        species[dex] = {"hp": s[1], "atk": s[2], "def": s[3], "spd": s[4], "spc": s[5],
                        "type1": TYPES.get(s[6], str(s[6])), "type2": TYPES.get(s[7], str(s[7])), "catch_rate": s[8], "base_exp": s[9]}
    move_names = {i: m["name"] for i, m in moves.items()}
    items = rom_extra.items(data, text)
    rom_extra.base_extras(data, species, move_names, dex_of, mon_names)
    learn = rom_extra.learnsets(data, mon_names, move_names, {i: v["name"] for i, v in items.items()})
    classes = rom_world.trainer_classes(data)
    kb = {"source": "ROM via pokered.sym offsets", "moves": moves, "type_chart": chart, "species_by_dex": species,
          "dex_of_internal": dex_of, "name_of_internal": mon_names, "learnsets": learn, "items": items,
          "wild_by_map": rom_world.wild(data, mon_names), "trainers": rom_world.trainers(data, mon_names),
          "map_trainers": rom_world.map_trainers(data, classes)}
    by_name = {m["name"]: m for m in moves.values()}
    sp = {v["name"]: v for v in species.values()}
    fire_grass = next((e for a, d, e in chart if a == "FIRE" and d == "GRASS"), None)
    charm = species.get(4, {})
    print("SCRATCH", by_name.get("SCRATCH"), "| TACKLE", by_name.get("TACKLE"), "| EMBER", by_name.get("EMBER"))
    print("FIRE vs GRASS:", fire_grass, "| Charmander base:", charm, "| internal 0xB0 ->", mon_names.get(0xB0), "dex", dex_of.get(0xB0))
    r1 = kb["wild_by_map"].get(0x0C, {}).get("grass", [])
    brock = (kb["trainers"].get("BROCK") or [[]])[0]
    checks = {
        "SCRATCH 40 / TACKLE 35": by_name.get("SCRATCH", {}).get("power") == 40 and by_name.get("TACKLE", {}).get("power") == 35,
        "FIRE vs GRASS 2x": fire_grass == 2.0,
        "CHARMANDER HP 39 FIRE/FIRE": charm.get("hp") == 39 and charm.get("type1") == "FIRE" and mon_names.get(0xB0) == "CHARMANDER",
        "PIDGEY NORMAL/FLYING": (sp["PIDGEY"]["type1"], sp["PIDGEY"]["type2"]) == ("NORMAL", "FLYING"),
        "GEODUDE ROCK/GROUND": (sp["GEODUDE"]["type1"], sp["GEODUDE"]["type2"]) == ("ROCK", "GROUND"),
        "ONIX ROCK/GROUND": (sp["ONIX"]["type1"], sp["ONIX"]["type2"]) == ("ROCK", "GROUND"),
        "CHARMANDER EMBER at 9": [9, "EMBER"] in learn["CHARMANDER"]["learnset"],
        "CHARMANDER evolves at 16": any(e["how"] == "level" and e["level"] == 16 and e["into"] == "CHARMELEON" for e in learn["CHARMANDER"]["evolves"]),
        "BULBASAUR VINE WHIP at 13": [13, "VINE WHIP"] in learn["BULBASAUR"]["learnset"],
        "Route 1 PIDGEY+RATTATA L2-5": {n for _, n in r1} == {"PIDGEY", "RATTATA"} and all(2 <= lv <= 5 for lv, _ in r1) and len(r1) == 10,
        "BROCK = GEODUDE 12, ONIX 14": brock == [[12, "GEODUDE"], [14, "ONIX"]],
        "POTION 300": items[20] == {"name": "POTION", "price": 300},
        "Pewter Gym (0x36) has BROCK trainer": any(t["class"] == "BROCK" for t in kb["map_trainers"].get(0x36, [])),
    }
    for name, ok in checks.items():
        print(("PASS  " if ok else "FAIL  ") + name)
    ok = all(checks.values())
    if ok:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(kb, indent=1), encoding="utf-8")
    print("ALL CHECKS", "PASS -> wrote " + out if ok else "FAIL -> nothing written")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
