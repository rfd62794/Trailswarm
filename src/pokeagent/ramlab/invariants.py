"""Pure RAM invariants over WRAM snapshots: bytes in, ``("ok"|"fail"|"skip", reason)`` out.

Each check is tied to the entries it covers by name or encoding; an entry no check covers
stays ``sym`` (no vacuous promotion). ``skip`` means the validity precondition was not met in
that state - an out-of-range party slot, no battle in progress, an empty daycare - so it is
neither a pass nor a fail. Entries whose populate condition is not measurable (loaded-mon
scratch, hall-of-fame display) are left uncovered on purpose: a guess there could fail on a
real state, and a fail is for the controller, not a silent skip. ram_recheck drives these.
"""
from __future__ import annotations

import re

WRAM_LO = 0xC000
MAX_SPECIES = 190
TERMINATOR = 0xFF
TEXT_END = 0x50


def _entry_bytes(e: dict, wram: bytes) -> bytes | None:
    off = int(e["addr"], 16) - WRAM_LO
    if off < 0 or off + e["size"] > len(wram):
        return None
    return wram[off:off + e["size"]]


def _named_byte(by_name: dict, wram: bytes, name: str) -> int | None:
    e = by_name.get(name)
    raw = _entry_bytes(e, wram) if e else None
    return raw[0] if raw else None


def _battle_gate(by_name: dict, wram: bytes, struct: str) -> tuple | None:
    """None when usable; a skip when not in battle or the struct's species byte is 0 (stale start)."""
    inb = _named_byte(by_name, wram, "wIsInBattle")
    if inb is None:
        return ("skip", "no wIsInBattle entry")
    if inb == 0:
        return ("skip", "not in battle")
    if not _named_byte(by_name, wram, struct):
        return ("skip", f"{struct} species byte missing or 0")
    return None


def _is_bcd(e: dict) -> bool:
    return e.get("encoding") == "bcd"


def _bcd(e: dict, wram: bytes, by_name: dict) -> tuple:
    raw = _entry_bytes(e, wram)
    if raw is None:
        return ("skip", "outside the snapshot")
    for i, b in enumerate(raw):
        if b >> 4 > 9 or b & 0xF > 9:
            return ("fail", f"byte {i} 0x{b:02X} has a non-bcd nibble")
    return ("ok", f"{len(raw)} bytes all bcd")


_HP_NAME = re.compile(r"w(PartyMon[1-6]|BattleMon|EnemyMon)HP\Z")


def _is_hp(e: dict) -> bool:
    return bool(_HP_NAME.fullmatch(e["name"]))


def _hp(e: dict, wram: bytes, by_name: dict) -> tuple:
    name = e["name"]
    raw = _entry_bytes(e, wram)
    mate = by_name.get(name[:-2] + "MaxHP")
    mraw = _entry_bytes(mate, wram) if mate else None
    if raw is None or mraw is None or len(raw) < 2 or len(mraw) < 2:
        return ("skip", "HP/MaxHP bytes unavailable")
    m = re.fullmatch(r"wPartyMon([1-6])HP", name)
    if m is not None:
        cnt = _named_byte(by_name, wram, "wPartyCount")
        if cnt is None or not 0 <= cnt <= 6:
            return ("skip", "wPartyCount invalid")
        if int(m.group(1)) > cnt:
            return ("skip", "slot beyond wPartyCount")
    else:
        gate = _battle_gate(by_name, wram, "wEnemyMon" if "Enemy" in name else "wBattleMon")
        if gate is not None:
            return gate
    hp, mx = int.from_bytes(raw[:2], "big"), int.from_bytes(mraw[:2], "big")
    if not 1 <= mx <= 999:
        return ("fail", f"MaxHP {mx} out of 1..999")
    if hp > mx:
        return ("fail", f"HP {hp} > MaxHP {mx}")
    return ("ok", f"HP {hp}/{mx}")


def _level_gate(name: str):
    """The validity precondition for a `...Level` u8 entry, or None when none is measurable."""
    for pat, gate in ((r"wPartyMon([1-6])(?:Box)?Level", ("count", "wPartyCount", 6)),
                      (r"wEnemyMon([1-6])(?:Box)?Level", ("enemy", "wEnemyPartyCount", 6)),
                      (r"wBoxMon([1-9]|1[0-9]|20)(?:Box)?Level", ("count", "wBoxCount", 20))):
        m = re.fullmatch(pat, name)
        if m:
            return (gate[0], gate[1], int(m.group(1)), gate[2])
    if re.fullmatch(r"wDayCare(Mon(Box)?Level|StartLevel)", name):
        return ("flag", "wDayCareMon")
    if name in ("wBattleMonLevel", "wBattleMonBoxLevel", "wPlayerMonUnmodifiedLevel"):
        return ("battle", "wBattleMon")
    if name in ("wEnemyMonLevel", "wEnemyMonBoxLevel", "wCurEnemyLevel", "wEnemyMonUnmodifiedLevel"):
        return ("battle", "wEnemyMon")
    return None


def _is_level(e: dict) -> bool:
    return e["size"] == 1 and e["name"].endswith("Level") and _level_gate(e["name"]) is not None


def _level(e: dict, wram: bytes, by_name: dict) -> tuple:
    raw = _entry_bytes(e, wram)
    if raw is None:
        return ("skip", "outside the snapshot")
    gate = _level_gate(e["name"])
    if gate[0] in ("count", "enemy"):
        if gate[0] == "enemy" and _named_byte(by_name, wram, "wIsInBattle") != 2:
            return ("skip", "enemy party valid only in trainer battles")
        cnt = _named_byte(by_name, wram, gate[1])
        if cnt is None or not 0 <= cnt <= gate[3]:
            return ("skip", f"{gate[1]} invalid")
        if gate[2] > cnt:
            return ("skip", f"slot beyond {gate[1]}")
    elif gate[0] == "flag":
        if not _named_byte(by_name, wram, gate[1]):
            return ("skip", f"{gate[1]} not set")
    else:
        res = _battle_gate(by_name, wram, gate[1])
        if res is not None:
            return res
    v = raw[0]
    if not 1 <= v <= 100:
        return ("fail", f"level {v} out of 1..100")
    return ("ok", f"level {v}")


def _is_party_list(e: dict) -> bool:
    return e["name"] in ("wPartyCount", "wPartySpecies") or bool(re.fullmatch(r"wPartyMon[1-6]", e["name"]))


def _is_enemy_party_list(e: dict) -> bool:
    return e["name"] in ("wEnemyPartyCount", "wEnemyPartySpecies") or bool(re.fullmatch(r"wEnemyMon[1-6]", e["name"]))


def _mon_list(e: dict, wram: bytes, by_name: dict, count_name: str, list_name: str,
              struct_pat: str) -> tuple:
    """Shared shape: count in 0..6, that many species bytes in 1..MAX_SPECIES, then 0xFF; each
    mon struct's species byte equals its list slot."""
    cnt = _named_byte(by_name, wram, count_name)
    if cnt is None:
        return ("skip", f"no {count_name} entry")
    if not 0 <= cnt <= 6:
        return ("fail", f"{count_name} {cnt} out of 0..6")
    lst = _entry_bytes(by_name[list_name], wram) if list_name in by_name else None
    if lst is None or cnt >= len(lst):
        return ("skip", f"no {list_name} entry")
    for i in range(cnt):
        if not 1 <= lst[i] <= MAX_SPECIES:
            return ("fail", f"{list_name}[{i}] {lst[i]} out of 1..{MAX_SPECIES}")
    if lst[cnt] != TERMINATOR:
        return ("fail", f"{list_name}[{cnt}] terminator is 0x{lst[cnt]:02X}, not 0xFF")
    m = re.fullmatch(struct_pat, e["name"])
    if m is None:
        return ("ok", f"party of {cnt}, list terminated")
    slot = int(m.group(1))
    if slot > cnt:
        return ("skip", f"slot beyond {count_name}")
    sp = _entry_bytes(e, wram)[0]
    if sp != lst[slot - 1]:
        return ("fail", f"{e['name']} species {sp} != list[{slot - 1}] {lst[slot - 1]}")
    return ("ok", f"slot {slot} species {sp}")


def _party_list(e: dict, wram: bytes, by_name: dict) -> tuple:
    return _mon_list(e, wram, by_name, "wPartyCount", "wPartySpecies", r"wPartyMon([1-6])")


def _enemy_party_list(e: dict, wram: bytes, by_name: dict) -> tuple:
    if _named_byte(by_name, wram, "wIsInBattle") != 2:
        return ("skip", "enemy party valid only in trainer battles")
    return _mon_list(e, wram, by_name, "wEnemyPartyCount", "wEnemyPartySpecies", r"wEnemyMon([1-6])")


def _is_bag_list(e: dict) -> bool:
    return e["name"] in ("wNumBagItems", "wBagItems")


def _bag_list(e: dict, wram: bytes, by_name: dict) -> tuple:
    cnt = _named_byte(by_name, wram, "wNumBagItems")
    if cnt is None:
        return ("skip", "no wNumBagItems entry")
    if not 0 <= cnt <= 20:
        return ("fail", f"wNumBagItems {cnt} out of 0..20")
    items = _entry_bytes(by_name["wBagItems"], wram) if "wBagItems" in by_name else None
    if items is None or 2 * cnt >= len(items):
        return ("skip", "wBagItems bytes unavailable")
    if items[2 * cnt] != TERMINATOR:
        return ("fail", f"terminator after {cnt} items is 0x{items[2 * cnt]:02X}, not 0xFF")
    return ("ok", f"{cnt} items, terminated")


def _is_name_text(e: dict) -> bool:
    return e.get("encoding") == "text" and e["name"].endswith("Name")


def _text(e: dict, wram: bytes, by_name: dict) -> tuple:
    raw = _entry_bytes(e, wram)
    if raw is None:
        return ("skip", "outside the snapshot")
    if TEXT_END not in raw:
        return ("fail", f"no 0x50 terminator within {len(raw)} bytes")
    return ("ok", "0x50-terminated")


CHECKS = {
    "bcd": (_is_bcd, _bcd),
    "u16be_hp": (_is_hp, _hp),
    "level_range": (_is_level, _level),
    "party_list": (_is_party_list, _party_list),
    "enemy_party_list": (_is_enemy_party_list, _enemy_party_list),
    "bag_list": (_is_bag_list, _bag_list),
    "text_terminated": (_is_name_text, _text),
}


def evaluate(entries: list[dict], snapshots: list[tuple[str, bytes]]) -> dict[str, dict[str, dict]]:
    """Run every applicable check on every entry over the (state-name, WRAM-bytes) snapshots.
    Returns {entry name: {check id: {ok: [states], fail: [(state, reason)], skip: n}}}; entries
    covered by no check are absent from the result."""
    by_name = {e["name"]: e for e in entries}
    out: dict[str, dict[str, dict]] = {}
    for e in entries:
        for cid, (applies, fn) in CHECKS.items():
            if not applies(e):
                continue
            r = out.setdefault(e["name"], {}).setdefault(cid, {"ok": [], "fail": [], "skip": 0})
            for sname, wram in snapshots:
                res = fn(e, wram, by_name)
                if res[0] == "ok":
                    r["ok"].append(sname)
                elif res[0] == "fail":
                    r["fail"].append((sname, res[1]))
                else:
                    r["skip"] += 1
    return out
