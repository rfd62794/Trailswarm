import importlib.util
import json
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.ramlab import invariants as I
from pokeagent.ramlab.trust import tier_of

_spec = importlib.util.spec_from_file_location("ram_recheck", Path(__file__).resolve().parents[1] / "tools" / "ram_recheck.py")
recheck_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recheck_tool)


def E(name, addr, size, encoding="u8"):
    return {"name": name, "addr": f"0x{addr:04X}", "size": size, "encoding": encoding,
            "region": "other", "verified": False}


def snap(*writes):
    m = bytearray(0x2000)
    for a, v in writes:
        m[a - 0xC000:a - 0xC000 + len(v)] = v
    return bytes(m)


def run(cid, entry, wram, entries):
    applies, fn = I.CHECKS[cid]
    assert applies(entry)
    return fn(entry, wram, {e["name"]: e for e in entries})[0]


BATTLE = [E("wBattleMon", 0xD014, 29, "bytes"), E("wBattleMonHP", 0xD015, 2, "u16be"),
          E("wBattleMonLevel", 0xD022, 1), E("wBattleMonMaxHP", 0xD023, 2, "u16be"),
          E("wEnemyMon", 0xCFE5, 29, "bytes"), E("wEnemyMonHP", 0xCFE6, 2, "u16be"),
          E("wEnemyMonMaxHP", 0xCFF4, 2, "u16be"), E("wIsInBattle", 0xD057, 1)]
PARTY = [E("wPartyCount", 0xD163, 1), E("wPartySpecies", 0xD164, 7, "bytes"),
         E("wPartyMon1", 0xD16B, 44, "bytes"), E("wPartyMon2", 0xD197, 44, "bytes"),
         E("wPartyMon1Level", 0xD18C, 1), E("wPartyMon2Level", 0xD1B8, 1)]
ENEMY = [E("wEnemyPartyCount", 0xD89C, 1), E("wEnemyPartySpecies", 0xD89D, 7, "bytes"),
         E("wEnemyMon1", 0xD8A4, 44, "bytes")]
BAG = [E("wNumBagItems", 0xD31D, 1), E("wBagItems", 0xD31E, 41, "bytes")]


def test_bcd_ok_fail_skip():
    e = E("wPlayerMoney", 0xD347, 3, "bcd")
    assert run("bcd", e, snap((0xD347, b"\x12\x34\x56")), [e]) == "ok"
    assert run("bcd", e, snap((0xD347, b"\x1A\x00\x00")), [e]) == "fail"
    assert run("bcd", e, bytes(0x100), [e]) == "skip"          # outside the snapshot


def test_u16be_hp_ok_fail_skip():
    e = next(x for x in BATTLE if x["name"] == "wBattleMonHP")
    good = snap((0xD057, b"\x01"), (0xD014, b"\x99"), (0xD015, b"\x00\x0A"), (0xD023, b"\x00\x14"))
    assert run("u16be_hp", e, good, BATTLE) == "ok"
    bad = snap((0xD057, b"\x01"), (0xD014, b"\x99"), (0xD015, b"\x00\x1E"), (0xD023, b"\x00\x14"))
    assert run("u16be_hp", e, bad, BATTLE) == "fail"           # HP 30 > MaxHP 20
    assert run("u16be_hp", e, snap(), BATTLE) == "skip"        # not in battle


def test_level_range_ok_fail_skip():
    e = next(x for x in BATTLE if x["name"] == "wBattleMonLevel")
    in_battle = snap((0xD057, b"\x01"), (0xD014, b"\x99"), (0xD022, b"\x32"))
    assert run("level_range", e, in_battle, BATTLE) == "ok"
    bad = snap((0xD057, b"\x01"), (0xD014, b"\x99"), (0xD022, b"\x96"))
    assert run("level_range", e, bad, BATTLE) == "fail"        # level 150
    assert run("level_range", e, snap(), BATTLE) == "skip"     # not in battle


def test_party_list_ok_fail_skip():
    lst = [1, 4, 0xFF]
    good = snap((0xD163, b"\x02"), (0xD164, bytes(lst)), (0xD16B, b"\x01"), (0xD197, b"\x04"))
    by = {e["name"]: e for e in PARTY}
    for name in ("wPartyCount", "wPartySpecies", "wPartyMon1", "wPartyMon2"):
        assert run("party_list", by[name], good, PARTY) == "ok"
    over = snap((0xD163, b"\x03"), (0xD164, bytes(lst)))                # count 3 with the 2-mon list
    assert run("party_list", by["wPartyCount"], over, PARTY) == "fail"
    one = snap((0xD163, b"\x01"), (0xD164, bytes([1, 0xFF])), (0xD16B, b"\x01"))
    assert run("party_list", by["wPartyMon2"], one, PARTY) == "skip"   # slot beyond count


def test_enemy_party_list_ok_fail_skip():
    ents = ENEMY + [E("wIsInBattle", 0xD057, 1)]
    good = snap((0xD057, b"\x02"), (0xD89C, b"\x01"), (0xD89D, bytes([7, 0xFF])), (0xD8A4, b"\x07"))
    by = {e["name"]: e for e in ents}
    assert run("enemy_party_list", by["wEnemyPartySpecies"], good, ents) == "ok"
    assert run("enemy_party_list", by["wEnemyMon1"], good, ents) == "ok"
    bad = snap((0xD057, b"\x02"), (0xD89C, b"\x01"), (0xD89D, bytes([0, 0xFF])))
    assert run("enemy_party_list", by["wEnemyPartyCount"], bad, ents) == "fail"
    wild = snap((0xD057, b"\x01"))
    assert run("enemy_party_list", by["wEnemyMon1"], wild, ents) == "skip"   # wild battle


def test_bag_list_ok_fail_skip():
    good = snap((0xD31D, b"\x01"), (0xD31E, bytes([0x14, 0x01, 0xFF])))
    by = {e["name"]: e for e in BAG}
    for name in ("wNumBagItems", "wBagItems"):
        assert run("bag_list", by[name], good, BAG) == "ok"
    bad = snap((0xD31D, b"\x01"), (0xD31E, bytes([0x14, 0x01, 0x10])))
    assert run("bag_list", by["wBagItems"], bad, BAG) == "fail"
    assert run("bag_list", by["wNumBagItems"], snap(), BAG[:1]) == "skip"    # no wBagItems


def test_text_terminated_ok_fail_skip():
    e = E("wPlayerName", 0xD158, 11, "text")
    assert run("text_terminated", e, snap((0xD158, b"RED\x50")), [e]) == "ok"
    assert run("text_terminated", e, snap((0xD158, b"ABCDEFGHIJK")), [e]) == "fail"
    assert run("text_terminated", e, bytes(0x100), [e]) == "skip"


def _mkstate(path, mem):
    path.write_text(json.dumps({str(k): v for k, v in mem.items()}))
    return path


ENTRIES = [E("wPlayerMoney", 0xD347, 3, "bcd"), E("wPartyMon1Level", 0xD18C, 1),
           E("wPartyCount", 0xD163, 1), E("wPartySpecies", 0xD164, 7, "bytes"),
           E("wUncovered", 0xD500, 1)]


def _state_mem(money=b"\x01\x23\x45", count=1, level=5, species=(1, 0xFF)):
    mem = {0xD347 + i: b for i, b in enumerate(money)}
    mem[0xD163] = count
    for i, b in enumerate(species):
        mem[0xD164 + i] = b
    mem[0xD18C] = level
    return mem


def test_recheck_promotes_only_on_two_ok_states(tmp_path):
    emu = FakeEmulator()
    ok1 = _mkstate(tmp_path / "s1.state", _state_mem())
    ok2 = _mkstate(tmp_path / "s2.state", _state_mem(level=7, species=(4, 0xFF)))
    entries = [dict(e) for e in ENTRIES]
    assert recheck_tool.recheck(emu, [ok1, ok2], entries, today="2026-11-12", apply=False) == 0
    assert tier_of(entries[0]) == "sym"                                    # dry run writes nothing
    map_path = tmp_path / "ram_map.json"
    map_path.write_text(json.dumps(entries))
    assert recheck_tool.recheck(emu, [ok1, ok2], entries, today="2026-11-12", apply=True, map_path=map_path) == 0
    by = {e["name"]: e for e in json.loads(map_path.read_text())}
    assert by["wPlayerMoney"]["trust"] == "verified" and "invariant bcd held in 2/2" in by["wPlayerMoney"]["evidence"]
    assert tier_of(by["wUncovered"]) == "sym"                              # no check covers it: stays sym
    one_ok = _mkstate(tmp_path / "s3.state", _state_mem(count=0, species=(0xFF,)))   # level skips, money still ok
    entries = [dict(e) for e in ENTRIES]
    assert recheck_tool.recheck(emu, [ok1, one_ok], entries, today="2026-11-12", apply=True, map_path=map_path) == 0
    by = {e["name"]: e for e in json.loads(map_path.read_text())}
    assert tier_of(by["wPartyMon1Level"]) == "sym"                         # 1 ok + 1 skip: not promoted
    assert by["wPlayerMoney"]["trust"] == "verified"


def test_recheck_fail_blocks_and_exits_1(tmp_path):
    emu = FakeEmulator()
    ok1 = _mkstate(tmp_path / "s1.state", _state_mem())
    bad = _mkstate(tmp_path / "s2.state", _state_mem(money=b"\xFF\xFF\xFF"))
    entries = [dict(e) for e in ENTRIES]
    map_path = tmp_path / "ram_map.json"
    map_path.write_text(json.dumps(entries))
    before = map_path.read_bytes()
    assert recheck_tool.recheck(emu, [ok1, bad], entries, today="2026-11-12", apply=True, map_path=map_path) == 1
    assert map_path.read_bytes() == before                                 # a fail writes nothing
