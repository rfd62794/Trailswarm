"""No-ROM checks of the COVERED table against ram_map.json and the pasted addresses.

Runs in every worktree: asserts each covered symbol exists in the map by name at
the pokered.sym address pasted in the directive, that the table lists exactly the
asserted symbols, and that the no-stable-value symbols stay out of it.
"""
from pokeagent.ram_lookup import load_map

from party_states_covered import COVERED

# name -> expected address, pasted from the pokered.sym block in the directive
# (never recomputed from the map).
EXPECTED_ADDR = {
    "wPlayerMonNumber": 0xCC2F,
    "wPartyFoughtCurrentEnemyFlags": 0xCCF5,
    "wEnemyMon": 0xCFE5,
    "wEnemyMonPartyPos": 0xCFE8,
    "wBattleMon": 0xD014,
    "wTrainerClass": 0xD031,
    "wIsInBattle": 0xD057,
    "wPartyGainExpFlags": 0xD058,
    "wTrainerNo": 0xD05D,
    "wPartyCount": 0xD163,
    "wPartySpecies": 0xD164,
    "wPartyMon1": 0xD16B,
    "wPartyMonOT": 0xD273,
    "wPartyMonNicks": 0xD2B5,
    "wEnemyPartyCount": 0xD89C,
    "wEnemyPartySpecies": 0xD89D,
    "wEnemyMons": 0xD8A4,
    "wBoxCount": 0xDA80,
    "wBoxSpecies": 0xDA81,
    "wBoxMons": 0xDA96,
    "wBoxMonOT": 0xDD2A,
    "wBoxMonNicks": 0xDE06,
}

# The unverified party/battle/box symbols from the audit ("Why" list) that the
# tests now cover.
WHY_LIST = [
    "wPlayerMonNumber",
    "wPartyGainExpFlags",
    "wPartyFoughtCurrentEnemyFlags",
    "wEnemyPartyCount",
    "wEnemyPartySpecies",
    "wEnemyMons",
    "wBoxCount",
    "wBoxMons",
    "wBoxMonOT",
    "wBoxMonNicks",
    "wEnemyMonPartyPos",
]


def test_covered_keys_exist_in_ram_map_at_pasted_addresses():
    by_name = {e.name: e for e in load_map()}
    for name, addr in EXPECTED_ADDR.items():
        assert name in by_name, f"{name} missing from ram_map.json"
        assert by_name[name].addr == addr, f"{name} addr"


def test_covered_lists_exactly_the_asserted_symbols():
    assert set(COVERED) == set(EXPECTED_ADDR)


def test_why_symbols_are_covered():
    for name in WHY_LIST:
        assert name in COVERED, f"{name} from the audit list not in COVERED"


def test_no_stable_value_symbols_not_covered():
    assert "wWhichPokemon" not in COVERED
    assert "wPartyMenuTypeOrMessageID" not in COVERED


def test_covered_values_name_real_test_functions():
    import test_party_states

    for name, fn in COVERED.items():
        assert callable(getattr(test_party_states, fn, None)), f"{name} -> {fn}"
