"""The item catalog, drained from the ROM -> kb/items.json (gitignored, ROM-derived; never commit it).

Per item: id, name, price (ItemPrices 01:4608, 3-byte BCD), sell (half), use_class, key_item, usable in battle / overworld.
  * use_class comes from ItemUsePtrTable (03:55e1 = file 0xD5E1; entry id-1 is the routine pointer): items that share a routine
    share a group (balls, evolution stones, vitamins + RARE CANDY, medicines, the 'unusable' group ...). A group is named from
    ANCHORS (one well-known item per routine), then refined by the item's ROM name (medicine -> healing / status_cure / revive,
    RARE CANDY out of the vitamin routine, unusable -> key / valuable / badge).
  * key_item: pokered's KeyItemFlags bitfield could not be located in the ROM, so it is derived: price 0 and not a consumable
    class (a price-0 ball / stone / medicine is a gift item, not a key item). The ROM-gated tests pin the known cases.
  * TM01-50 / HM01-05 (ids 0xC9.. / 0xC4..) are tm_hm; their prices live in another table and are left 0.
  * mart_stocks: every Mart stock list in the ROM (FE n id.. FF); the first five follow the Marts' order in the ROM
    (Viridian Pewter Cerulean Vermilion Lavender) and are labelled with their map ids, the rest are unlabelled.
  * trainer_money: class base money (TrainerPicAndMoneyPointers 0e:5914, 5-byte entries: pic ptr + BCD money); a trainer pays
    base x the level of its LAST Pokemon. trainer_prize(cat, class, party) and map_income(cat, map) use it.
``load()`` reads kb/items.json, or builds it when the ROM + kb/rom_tables.json exist; None otherwise.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pokeagent.game.paths import default_rom
from pokeagent.game.stores import store_path

ROOT = Path(__file__).resolve().parents[3]
KB_PATH, ROM_PATH = store_path("kb/items.json", root=ROOT), default_rom(root=ROOT)  # POKEAGENT_GAME read once at import
ITEM_USE_TABLE, ITEM_PRICES, TRAINER_MONEY = 0xD5E1, 0x01 * 0x4000 + (0x4608 - 0x4000), 0x0E * 0x4000 + (0x5914 - 0x4000)
N_ITEMS, HM01, TM01, N_TM, N_HM = 83, 0xC4, 0xC9, 50, 5
MART_ORDER = (42, 56, 67, 91, 150)  # Viridian Pewter Cerulean Vermilion Lavender: the first five stock lists in the ROM

# one item per ItemUsePtrTable routine: names the group the pointer table builds
ANCHORS = {4: "ball", 10: "stone", 35: "vitamin", 20: "medicine", 29: "escape_rope", 30: "repel", 46: "battle_stat",
           51: "escape_battle", 73: "itemfinder", 69: "coin_case", 76: "rod", 79: "pp_up", 80: "pp_restore", 6: "bike",
           5: "town_map", 48: "card_key", 49: "unusable"}
# (usable in battle, usable in the overworld) per class
USE = {"ball": (True, False), "healing": (True, True), "status_cure": (True, True), "revive": (False, True), "drink": (False, True),
       "vitamin": (False, True), "rare_candy": (False, True), "stone": (False, True), "pp_up": (False, True),
       "pp_restore": (False, True), "escape_rope": (False, True), "repel": (False, True), "battle_stat": (True, False),
       "escape_battle": (True, False), "bike": (False, True), "rod": (False, True), "itemfinder": (False, True),
       "town_map": (False, True), "coin_case": (False, True), "card_key": (False, True), "flute": (True, True),
       "tm_hm": (False, True), "key": (False, False), "valuable": (False, False), "badge": (False, False), "unusable": (False, False)}
CONSUMABLE = frozenset({"ball", "healing", "status_cure", "revive", "drink", "vitamin", "rare_candy", "stone", "pp_up",
                        "pp_restore", "escape_rope", "repel", "battle_stat", "escape_battle", "tm_hm"})


def bcd(raw: bytes) -> int:
    return int("".join(f"{b:02x}" for b in raw))


def use_groups(rom: bytes, n: int = N_ITEMS) -> dict[int, int]:
    """{item id: routine pointer} from ItemUsePtrTable."""
    return {i: rom[ITEM_USE_TABLE + 2 * (i - 1)] | rom[ITEM_USE_TABLE + 2 * (i - 1) + 1] << 8 for i in range(1, n + 1)}


def _refine(name: str, price: int, cls: str) -> str:
    n = name.upper()
    if cls == "medicine":
        if "REVIVE" in n:
            return "revive"
        if "POTION" in n or "RESTORE" in n:
            return "healing"
        return "drink" if n in ("FRESH WATER", "SODA POP", "LEMONADE") else "status_cure"
    if n == "RARE CANDY":
        return "rare_candy"
    if "BADGE" in n:
        return "badge"
    if "FLUTE" in n:
        return "flute"
    if cls == "unusable":
        return "valuable" if price > 0 else "key"
    return cls


def _name_rule(name: str) -> str:
    n = name.upper()
    if "REPEL" in n:
        return "repel"
    if n.startswith("X ") or n in ("DIRE HIT", "GUARD SPEC."):
        return "battle_stat"
    if "ROD" in n:
        return "rod"
    if "FLUTE" in n:
        return "flute"
    return "key"


def item_rows(rom: bytes, names: dict[int, str]) -> dict[int, dict]:
    groups = use_groups(rom)
    label: dict[int, str] = {}
    for ptr in set(groups.values()):
        members = [i for i, p in groups.items() if p == ptr]
        label[ptr] = next((ANCHORS[i] for i in members if i in ANCHORS), "")
    out: dict[int, dict] = {}
    for i in range(1, N_ITEMS + 1):
        name = names.get(i, f"item{i}")
        price = bcd(rom[ITEM_PRICES + 3 * (i - 1): ITEM_PRICES + 3 * i])
        cls = _refine(name, price, label[groups[i]] or _name_rule(name))
        key = price == 0 and cls not in CONSUMABLE and cls not in ("badge",)
        out[i] = _row(i, name, price, cls, key)
    for k in range(N_HM):
        out[HM01 + k] = _row(HM01 + k, f"HM{k + 1:02d}", 0, "tm_hm", False)
    for k in range(N_TM):
        out[TM01 + k] = _row(TM01 + k, f"TM{k + 1:02d}", 0, "tm_hm", False)
    return out


def _row(i: int, name: str, price: int, cls: str, key: bool) -> dict:
    battle, over = USE.get(cls, (False, False))
    return {"id": i, "name": name, "price": price, "sell": price // 2, "use_class": cls, "key_item": key,
            "battle": battle, "overworld": over}


def mart_stocks(rom: bytes, priced: set[int]) -> list[dict]:
    out = []
    for i in range(0x10000):
        if rom[i] == 0xFE and 2 <= rom[i + 1] <= 10:
            n = rom[i + 1]
            ids = list(rom[i + 2:i + 2 + n])
            if rom[i + 2 + n] == 0xFF and len(set(ids)) == n and all(x in priced for x in ids):
                out.append({"offset": i, "items": ids})
    for k, row in enumerate(out):
        row["map"] = MART_ORDER[k] if k < len(MART_ORDER) else None
    return out


def trainer_money(rom: bytes, classes: list[str]) -> dict[str, int]:
    """Base money per trainer class name (class ids are 1-based, in the order of the kb trainer table)."""
    return {c: bcd(rom[TRAINER_MONEY + 5 * k + 2: TRAINER_MONEY + 5 * k + 4]) for k, c in enumerate(classes)}


def build(rom: bytes, kb: dict) -> dict:
    names = {int(k): v["name"] for k, v in kb["items"].items()}
    items = item_rows(rom, names)
    priced = {i for i, r in items.items() if r["price"] > 0}
    return {"source": "ROM: ItemPrices 01:4608, ItemUsePtrTable 03:55e1, Mart lists, TrainerPicAndMoneyPointers 0e:5914",
            "items": {str(i): r for i, r in sorted(items.items())}, "mart_stocks": mart_stocks(rom, priced),
            "trainer_money": trainer_money(rom, list(kb["trainers"])),
            "trainers": kb["trainers"], "map_trainers": kb["map_trainers"]}


@lru_cache(maxsize=1)
def load() -> dict | None:
    try:
        return json.loads(KB_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        from pokeagent.knowledge.kb import ROM_KB
        if ROM_KB is None or not ROM_PATH.exists():
            return None
        cat = build(ROM_PATH.read_bytes(), ROM_KB)
        KB_PATH.parent.mkdir(exist_ok=True)
        KB_PATH.write_text(json.dumps(cat), encoding="utf-8")
        return cat
    except Exception:
        return None


def item(cat: dict, item_id: int) -> dict | None:
    return cat["items"].get(str(item_id))


def category_of(item_id: int, cat: dict | None = None) -> str | None:
    """The item's use_class ('healing', 'stone', 'key', 'tm_hm', ...), or None when the catalog or the item is unknown."""
    cat = cat if cat is not None else load()
    row = item(cat, item_id) if cat else None
    return row["use_class"] if row else None


def stock_for_map(cat: dict, map_id: int) -> list[int] | None:
    return next((s["items"] for s in cat["mart_stocks"] if s["map"] == map_id), None)


def trainer_prize(cat: dict, cls: str, party: int) -> int | None:
    """Yen a trainer of ``cls`` pays for party number ``party`` (1-based): base money x level of its last Pokemon."""
    parties = cat["trainers"].get(cls) or []
    if not 1 <= party <= len(parties) or not parties[party - 1]:
        return None
    return cat["trainer_money"][cls] * parties[party - 1][-1][0]


def map_income(cat: dict, map_id: int) -> int:
    """Total prize money of the trainers on a map (entries whose party number is invalid are skipped)."""
    return sum(trainer_prize(cat, t["class"], t["party"]) or 0 for t in cat["map_trainers"].get(str(map_id), []))
