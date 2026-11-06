from pokeagent.ramlab.flags import by_place, describe, flag_bits


def test_bit_level_flag_flips_named_by_place_and_text():
    recs = [{"run": "r", "map": 40, "x": 5, "y": 6, "text": "OAK: Hey! Wait!", "d": [[0xD74B, 0b0001, 0b1001], [0xC100, 1, 2]]},
            {"run": "r2", "map": 40, "x": 5, "y": 6, "text": "OAK: Hey! Wait!", "d": [[0xD74B, 0b0001, 0b1001]]}]
    maps_events = [{"map": 1, "at": [3, 4], "text": "Got a parcel", "flags": [["0xD74C", 0, 128]], "run": "m"}]
    bits = {b.key: b for b in flag_bits(recs, maps_events)}
    assert set(bits) == {"D74B.3", "D74C.7"}
    assert bits["D74B.3"].count == 2 and bits["D74B.3"].direction == "set" and bits["D74B.3"].runs == {"r", "r2"}
    assert describe(bits["D74B.3"], {"40": "OAKS_LAB"}) == 'Oaks Lab (5,6): "OAK: Hey! Wait!"'
    assert by_place(list(bits.values()))[(40, 5, 6)] == ["D74B.3:set"]


def test_trainer_flags_are_labelled():
    recs = [{"run": "r", "map": 0, "x": 1, "y": 2, "text": "BCN got $60 | for winning!", "d": [[0xD7F3, 0, 4]]}]
    assert describe(flag_bits(recs)[0], {"0": "PALLET_TOWN"}).startswith("[trainer beaten] Pallet Town (1,2)")


def test_clear_direction_and_block_bounds():
    recs = [{"run": "r", "map": 1, "x": 0, "y": 0, "text": "", "d": [[0xD750, 0b11, 0b01], [0xD887, 0, 1]]}]
    bits = flag_bits(recs)
    assert [(b.key, b.direction) for b in bits] == [("D750.1", "clear")]
