from pokeagent.explorer import stat_records, stats
from pokeagent.ramstructs import decode_party_mon

BULBA = bytes([153, 0, 20, 0, 0, 22, 3, 45, 33, 45, 0, 0, 218, 55, 0, 0, 135, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               92, 87, 35, 40, 0, 0, 5, 0, 20, 0, 10, 0, 11, 0, 10, 0, 12])

BULBA_BASE = {"hp": 45, "attack": 49, "defense": 49, "speed": 45, "special": 65}


def test_dvs_decode_and_hp_dv():
    d = stats.dvs(0x5C57)
    assert (d["attack"], d["defense"], d["speed"], d["special"]) == (5, 12, 5, 7)
    assert d["hp"] == 0b1011                        # low bits of 5, 12, 5, 7 -> 1,0,1,1
    assert stats.dvs(0xFFFF)["hp"] == 15 and stats.dvs(0)["hp"] == 0
    assert stats.dv_total(stats.dvs(0xFFFF)) == 75


def test_stat_value_matches_a_real_level5_starter():
    mon = decode_party_mon(BULBA)
    assert stats.computed_stats(mon, BULBA_BASE) == stats.ram_stats(mon) == \
        {"hp": 20, "attack": 10, "defense": 11, "speed": 10, "special": 12}


def test_stat_value_known_values_and_stat_exp_bonus():
    assert stats.stat_value(100, 15, 0, 100) == 235            # (115*2)*100/100 + 5
    assert stats.stat_value(100, 15, 65535, 100) == 235 + 63   # ceil(sqrt)=256->capped 255, //4 = 63
    assert stats.stat_value(50, 0, 0, 1, hp=True) == 12        # 50*2*1//100=1 + level 1 + 10


def test_stat_exp_yield_and_text():
    assert stats.stat_exp_yield(BULBA_BASE) == 253 and stats.stat_exp_yield(None) == 0
    mon = decode_party_mon(BULBA)
    assert stats.dv_text(mon) == "A5 D12 S5 P7 H11" and stats.stat_exp_text(mon) == "0/0/0/0/0"


def _mon(species, dv_word, level=5):
    raw = bytearray(BULBA)
    raw[0], raw[27], raw[28], raw[33] = species, dv_word >> 8, dv_word & 255, level
    return decode_party_mon(bytes(raw))


def test_record_catch_prefers_better_dvs():
    data: dict = {}
    party = [_mon(153, 0x5C57), _mon(36, 0x1111), _mon(153, 0xFFFF)]
    rec = stat_records.record_catch(data, party, 153, step=9)
    assert rec["duplicate"] and rec["prefer_slot"] == 2 and len(rec["mons"]) == 2
    assert stat_records.record_catch(data, party, 99, 10) is None       # boxed: not in party
    assert len(data["dv_records"]) == 1
    stat_records.record_catch(data, party, 153, 11)                      # re-record replaces
    assert len(data["dv_records"]) == 1


def test_record_catch_tie_keeps_earlier_slot():
    rec = stat_records.record_catch({}, [_mon(153, 0x1234), _mon(153, 0x1234)], 153, 1)
    assert rec["prefer_slot"] == 0


def test_note_stat_exp_and_rate():
    tr = {"exp": 0, "steps": 10, "by_level": {}}
    stat_records.note_stat_exp(tr, 100, None)
    assert "stat_exp" not in tr
    stat_records.note_stat_exp(tr, 130, 100)
    stat_records.note_stat_exp(tr, 130, 130)
    assert tr["stat_exp"] == 30 and stat_records.stat_exp_per_step(tr) == 3.0
