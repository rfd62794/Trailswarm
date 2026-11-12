"""Symbols pinned by tests/rom/test_party_states.py, mapped to a test that asserts each.

After the ROM run passes on the laptop, the controller flips "verified": true in
ram_map.json for each symbol whose mapped test passed (Robert's rule: verified
means a passing ROM test asserts it).
"""

COVERED = {   # symbol -> the test that asserts it, on at least one state
    "wPartyCount": "test_six_mons_with_box",
    "wPartySpecies": "test_six_mons_with_box",
    "wPartyMon1": "test_six_mons_with_box",
    "wPartyMonOT": "test_wild_stale_battle",
    "wPartyMonNicks": "test_wild_stale_battle",
    "wIsInBattle": "test_trainer_single_mon",
    "wBattleMon": "test_trainer_single_mon",
    "wEnemyMon": "test_trainer_single_mon",
    "wPlayerMonNumber": "test_trainer_second_slot_active",
    "wPartyGainExpFlags": "test_trainer_single_mon",
    "wPartyFoughtCurrentEnemyFlags": "test_trainer_single_mon",
    "wEnemyMonPartyPos": "test_trainer_single_mon",
    "wEnemyPartyCount": "test_trainer_single_mon",
    "wEnemyPartySpecies": "test_trainer_single_mon",
    "wEnemyMons": "test_trainer_second_slot_active",
    "wBoxCount": "test_six_mons_with_box",
    "wBoxSpecies": "test_six_mons_with_box",
    "wBoxMons": "test_six_mons_with_box",
    "wBoxMonOT": "test_six_mons_with_box",
    "wBoxMonNicks": "test_six_mons_with_box",
    "wTrainerClass": "test_trainer_single_mon",
    "wTrainerNo": "test_trainer_single_mon",
}
