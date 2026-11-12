"""Field-by-field pins of party, battle, enemy-party and box RAM against real saved states.

Every value asserted here was probed by the controller (2026-11-12, headless
PyBoyEmulator on the laptop) and pasted into the directive; this run has no ROM,
so each test skips. A failing assertion on the ROM run means the pasted value or
the state drifted - fix the test, never the state.
"""
from pokeagent.ramstructs import read_battle_mon, read_enemy_mon, read_party

from rom_helpers import load

# Addresses pasted from pokered.sym in the directive (test literals are exempt
# from the one-constant rule); names follow their symbols.
wPlayerMonNumber = 0xCC2F
wPartyFoughtCurrentEnemyFlags = 0xCCF5
wEnemyMon = 0xCFE5                 # 29-byte battle struct; also read via read_enemy_mon
wEnemyMonPartyPos = 0xCFE8
wBattleMon = 0xD014                # 29-byte battle struct; also read via read_battle_mon
wTrainerClass = 0xD031
wIsInBattle = 0xD057
wPartyGainExpFlags = 0xD058
wTrainerNo = 0xD05D
wPartyCount = 0xD163
wPartySpecies = 0xD164
wPartyMon1 = 0xD16B                # 44-byte party structs; read through read_party
wPartyMonOT = 0xD273               # 11 bytes per slot
wPartyMonNicks = 0xD2B5            # 11 bytes per slot
CUR_MAP = 0xD35E
wEnemyPartyCount = 0xD89C
wEnemyPartySpecies = 0xD89D
wEnemyMons = 0xD8A4                # 44-byte structs; HP +1/+2, level +33, max HP +34/+35
wBoxCount = 0xDA80
wBoxSpecies = 0xDA81
wBoxMons = 0xDA96                  # 33-byte structs; species +0, HP +1/+2, level +3,
                                   # moves +8..+11, OTID +12/+13
wBoxMonOT = 0xDD2A                 # 11 bytes per slot
wBoxMonNicks = 0xDE06              # 11 bytes per slot


def be16(emu, addr):
    return (emu.read(addr) << 8) | emu.read(addr + 1)


def test_bedroom(rom_emu):
    emu = load(rom_emu, "bedroom")
    assert emu.read(wIsInBattle) == 0, "wIsInBattle"
    assert emu.read(wPartyCount) == 0, "wPartyCount"
    assert emu.read(wPlayerMonNumber) == 0, "wPlayerMonNumber"
    assert emu.read(CUR_MAP) == 38, "CUR_MAP"
    assert emu.read(wEnemyPartyCount) == 0, "wEnemyPartyCount"
    assert emu.read(wPartyGainExpFlags) == 0, "wPartyGainExpFlags"
    assert emu.read(wPartyFoughtCurrentEnemyFlags) == 0, "wPartyFoughtCurrentEnemyFlags"
    assert emu.read(wBoxCount) == 0, "wBoxCount"
    assert read_party(emu) == [], "wPartyMon1"
    battle = read_battle_mon(emu)
    assert battle.species == 0, "wBattleMon"
    assert battle.hp == 0, "wBattleMonHP"
    assert battle.level == 0, "wBattleMonLevel"
    enemy = read_enemy_mon(emu)
    assert enemy.species == 0, "wEnemyMon"
    assert enemy.hp == 0, "wEnemyMonHP"
    assert enemy.level == 0, "wEnemyMonLevel"
    assert list(emu.read_range(wEnemyPartySpecies, 7)) == [0] * 7, "wEnemyPartySpecies"


def test_wild_stale_battle(rom_emu):
    emu = load(rom_emu, "wild_stale_battle")
    assert emu.read(wIsInBattle) == 1, "wIsInBattle"
    assert emu.read(wPartyCount) == 1, "wPartyCount"
    assert emu.read(CUR_MAP) == 12, "CUR_MAP"
    assert emu.read(wPlayerMonNumber) == 0, "wPlayerMonNumber"

    party = read_party(emu)
    assert len(party) == 1, "wPartyMon1"
    mon = party[0]
    assert mon.species == 177, "wPartyMon1 species"
    assert mon.level == 6, "wPartyMon1Level"
    assert mon.hp == 21, "wPartyMon1HP"
    assert mon.max_hp == 21, "wPartyMon1MaxHP"
    assert mon.status == 0, "wPartyMon1Status"
    assert mon.moves == (33, 39, 0, 0), "wPartyMon1Moves"
    assert mon.pp == (35, 30, 0, 0), "wPartyMon1PP"
    assert mon.ot_id == 55863, "wPartyMon1OTID"
    assert mon.dv_word == 0x84C8, "wPartyMon1DVs"

    assert list(emu.read_range(wPartyMonNicks, 11)) == [
        146, 144, 148, 136, 145, 147, 139, 132, 80, 80, 80], "wPartyMonNicks"
    assert list(emu.read_range(wPartyMonOT, 11)) == [
        129, 130, 141, 80, 0, 0, 0, 0, 0, 0, 0], "wPartyMonOT"

    battle = read_battle_mon(emu)          # stale: the wild fight has not loaded it yet
    assert battle.species == 0, "wBattleMon (stale)"
    assert battle.hp == 15, "wBattleMonHP"
    assert battle.max_hp == 21, "wBattleMonMaxHP"
    assert battle.level == 6, "wBattleMonLevel"
    assert battle.party_pos == 0, "wBattleMon party_pos"

    enemy = read_enemy_mon(emu)
    assert enemy.species == 165, "wEnemyMon species"
    assert enemy.hp == 14, "wEnemyMonHP"
    assert enemy.max_hp == 14, "wEnemyMonMaxHP"
    assert enemy.level == 3, "wEnemyMonLevel"

    # Stale enemy-party block left over from an earlier trainer fight (this is a
    # wild fight); wTrainerClass/wTrainerNo are stale leftovers too, not asserted.
    assert emu.read(wEnemyPartyCount) == 1, "wEnemyPartyCount (stale)"
    assert list(emu.read_range(wEnemyPartySpecies, 7)) == [
        153, 255, 0, 0, 0, 0, 0], "wEnemyPartySpecies (stale)"
    assert emu.read(wPartyGainExpFlags) == 0, "wPartyGainExpFlags"
    assert emu.read(wPartyFoughtCurrentEnemyFlags) == 0, "wPartyFoughtCurrentEnemyFlags"
    assert emu.read(wBoxCount) == 0, "wBoxCount"


def test_fainted_lead_overworld(rom_emu):
    emu = load(rom_emu, "fainted_lead_overworld")
    assert emu.read(wIsInBattle) == 0, "wIsInBattle"
    assert emu.read(wPartyCount) == 2, "wPartyCount"
    assert emu.read(CUR_MAP) == 54, "CUR_MAP"
    assert emu.read(wPlayerMonNumber) == 1, "wPlayerMonNumber (stale: no fight)"

    party = read_party(emu)
    assert len(party) == 2, "wPartyMon1"
    lead = party[0]
    assert lead.species == 176, "wPartyMon1 species"
    assert lead.level == 12, "wPartyMon1Level"
    assert lead.hp == 0, "wPartyMon1HP"
    assert lead.max_hp == 35, "wPartyMon1MaxHP"
    assert lead.status == 0, "wPartyMon1Status"
    assert lead.moves == (10, 45, 52, 0), "wPartyMon1Moves"
    assert lead.pp == (35, 40, 12, 0), "wPartyMon1PP"
    assert lead.ot_id == 55863, "wPartyMon1OTID"
    assert lead.dv_word == 0x5DA5, "wPartyMon1DVs"

    second = party[1]
    assert second.species == 36, "wPartyMon2 species"
    assert second.level == 12, "wPartyMon2Level"
    assert second.hp == 25, "wPartyMon2HP"
    assert second.max_hp == 32, "wPartyMon2MaxHP"
    assert second.status == 0, "wPartyMon2Status"
    assert second.moves == (16, 28, 98, 0), "wPartyMon2Moves"
    assert second.pp == (30, 15, 30, 0), "wPartyMon2PP"
    assert second.ot_id == 55863, "wPartyMon2OTID"
    assert second.dv_word == 0xC4CD, "wPartyMon2DVs"

    assert list(emu.read_range(wPartyMonNicks, 11)) == [
        130, 135, 128, 145, 140, 128, 141, 131, 132, 145, 80], "wPartyMonNicks"
    assert list(emu.read_range(wPartyMonOT, 11)) == [
        129, 130, 141, 80, 0, 0, 0, 0, 0, 0, 0], "wPartyMonOT"

    # Stale wBattleMon equals slot 1 out of battle (why active_slot gates on wIsInBattle).
    battle = read_battle_mon(emu)
    assert battle.species == 36, "wBattleMon species (stale)"
    assert battle.hp == 25, "wBattleMonHP"
    assert battle.max_hp == 32, "wBattleMonMaxHP"
    assert battle.level == 12, "wBattleMonLevel"

    enemy = read_enemy_mon(emu)
    assert enemy.species == 34, "wEnemyMon species"
    assert enemy.hp == 0, "wEnemyMonHP"
    assert enemy.max_hp == 36, "wEnemyMonMaxHP"
    assert enemy.level == 14, "wEnemyMonLevel"

    assert emu.read(wPartyGainExpFlags) == 2, "wPartyGainExpFlags"
    assert emu.read(wPartyFoughtCurrentEnemyFlags) == 2, "wPartyFoughtCurrentEnemyFlags"
    assert emu.read(wEnemyMonPartyPos) == 1, "wEnemyMonPartyPos"
    assert emu.read(wEnemyPartyCount) == 2, "wEnemyPartyCount"
    assert list(emu.read_range(wEnemyPartySpecies, 7)) == [
        169, 34, 255, 0, 0, 0, 0], "wEnemyPartySpecies"
    assert emu.read(wBoxCount) == 0, "wBoxCount"


def test_trainer_single_mon(rom_emu):
    emu = load(rom_emu, "trainer_single_mon")
    assert emu.read(wIsInBattle) == 2, "wIsInBattle"
    assert emu.read(wPartyCount) == 1, "wPartyCount"
    assert emu.read(CUR_MAP) == 14, "CUR_MAP"
    assert emu.read(wPlayerMonNumber) == 0, "wPlayerMonNumber"

    party = read_party(emu)
    assert len(party) == 1, "wPartyMon1"
    mon = party[0]
    assert mon.species == 177, "wPartyMon1 species"
    assert mon.level == 15, "wPartyMon1Level"
    assert mon.hp == 37, "wPartyMon1HP"
    assert mon.max_hp == 43, "wPartyMon1MaxHP"
    assert mon.status == 0, "wPartyMon1Status"
    assert mon.moves == (33, 39, 145, 0), "wPartyMon1Moves"
    assert mon.pp == (27, 30, 27, 0), "wPartyMon1PP"
    assert mon.ot_id == 55863, "wPartyMon1OTID"
    assert mon.dv_word == 0x5B69, "wPartyMon1DVs"

    battle = read_battle_mon(emu)
    assert battle.species == 177, "wBattleMon species"
    assert battle.hp == 37, "wBattleMonHP"
    assert battle.max_hp == 43, "wBattleMonMaxHP"
    assert battle.level == 15, "wBattleMonLevel"

    enemy = read_enemy_mon(emu)
    assert enemy.species == 112, "wEnemyMon species"
    assert enemy.hp == 0, "wEnemyMonHP"
    assert enemy.max_hp == 29, "wEnemyMonMaxHP"
    assert enemy.level == 10, "wEnemyMonLevel"
    assert enemy.party_pos == 1, "wEnemyMon party_pos"

    assert emu.read(wTrainerClass) == 2, "wTrainerClass"
    assert emu.read(wTrainerNo) == 4, "wTrainerNo"
    assert emu.read(wPartyGainExpFlags) == 1, "wPartyGainExpFlags"
    assert emu.read(wPartyFoughtCurrentEnemyFlags) == 1, "wPartyFoughtCurrentEnemyFlags"
    assert emu.read(wEnemyMonPartyPos) == 1, "wEnemyMonPartyPos"
    assert emu.read(wEnemyPartyCount) == 3, "wEnemyPartyCount"
    assert list(emu.read_range(wEnemyPartySpecies, 7)) == [
        123, 112, 123, 255, 0, 0, 0], "wEnemyPartySpecies"

    # wEnemyMons party structs (HP / level / max HP only; the species byte is
    # unreliable - use wEnemyPartySpecies).
    for i, (hp, level, max_hp) in enumerate([(0, 10, 30), (0, 10, 29), (30, 10, 30)]):
        base = wEnemyMons + 44 * i
        assert be16(emu, base + 1) == hp, f"wEnemyMons[{i}] HP"
        assert emu.read(base + 33) == level, f"wEnemyMons[{i}] level"
        assert be16(emu, base + 34) == max_hp, f"wEnemyMons[{i}] max HP"

    assert emu.read(wBoxCount) == 0, "wBoxCount"


def test_trainer_second_slot_active(rom_emu):
    emu = load(rom_emu, "trainer_second_slot_active")
    assert emu.read(wIsInBattle) == 2, "wIsInBattle"
    assert emu.read(wPartyCount) == 2, "wPartyCount"
    assert emu.read(CUR_MAP) == 3, "CUR_MAP"
    assert emu.read(wPlayerMonNumber) == 1, "wPlayerMonNumber"

    party = read_party(emu)
    assert len(party) == 2, "wPartyMon1"
    first = party[0]
    assert first.species == 133, "wPartyMon1 species"
    assert first.level == 9, "wPartyMon1Level"
    assert first.hp == 23, "wPartyMon1HP"
    assert first.max_hp == 23, "wPartyMon1MaxHP"
    assert first.moves == (150, 0, 0, 0), "wPartyMon1Moves"
    assert first.pp == (40, 0, 0, 0), "wPartyMon1PP"
    assert first.ot_id == 55863, "wPartyMon1OTID"
    assert first.dv_word == 0x82DC, "wPartyMon1DVs"

    second = party[1]
    assert second.species == 179, "wPartyMon2 species"
    assert second.level == 25, "wPartyMon2Level"
    assert second.hp == 63, "wPartyMon2HP"
    assert second.max_hp == 69, "wPartyMon2MaxHP"
    assert second.moves == (44, 39, 145, 55), "wPartyMon2Moves"
    assert second.pp == (21, 30, 30, 25), "wPartyMon2PP"
    assert second.ot_id == 55863, "wPartyMon2OTID"
    assert second.dv_word == 0x8E6C, "wPartyMon2DVs"

    battle = read_battle_mon(emu)
    assert battle.species == 179, "wBattleMon species"
    assert battle.hp == 63, "wBattleMonHP"
    assert battle.max_hp == 69, "wBattleMonMaxHP"
    assert battle.level == 25, "wBattleMonLevel"

    enemy = read_enemy_mon(emu)
    assert enemy.species == 150, "wEnemyMon species"
    assert enemy.hp == 0, "wEnemyMonHP"
    assert enemy.max_hp == 53, "wEnemyMonMaxHP"
    assert enemy.level == 18, "wEnemyMonLevel"
    assert enemy.party_pos == 0, "wEnemyMon party_pos"

    assert emu.read(wTrainerClass) == 25, "wTrainerClass"
    assert emu.read(wTrainerNo) == 8, "wTrainerNo"
    assert emu.read(wPartyGainExpFlags) == 3, "wPartyGainExpFlags"
    assert emu.read(wPartyFoughtCurrentEnemyFlags) == 3, "wPartyFoughtCurrentEnemyFlags"
    assert emu.read(wEnemyMonPartyPos) == 0, "wEnemyMonPartyPos"
    assert emu.read(wEnemyPartyCount) == 4, "wEnemyPartyCount"
    assert list(emu.read_range(wEnemyPartySpecies, 7)) == [
        150, 148, 165, 153, 255, 0, 0], "wEnemyPartySpecies"

    for i, (hp, level, max_hp) in enumerate(
            [(0, 18, 53), (34, 15, 34), (36, 15, 36), (45, 17, 45)]):
        base = wEnemyMons + 44 * i
        assert be16(emu, base + 1) == hp, f"wEnemyMons[{i}] HP"
        assert emu.read(base + 33) == level, f"wEnemyMons[{i}] level"
        assert be16(emu, base + 34) == max_hp, f"wEnemyMons[{i}] max HP"


def test_six_mons_with_box(rom_emu):
    emu = load(rom_emu, "six_mons_with_box")
    assert emu.read(wIsInBattle) == 0, "wIsInBattle"
    assert emu.read(wPartyCount) == 6, "wPartyCount"
    assert emu.read(CUR_MAP) == 65, "CUR_MAP"
    assert emu.read(wPlayerMonNumber) == 2, "wPlayerMonNumber (stale)"

    party = read_party(emu)
    assert len(party) == 6, "wPartyMon1"
    slots = [
        (133, 11, 26, 26, (150, 0, 0, 0), (40, 0, 0, 0), 0x4346),
        (109, 8, 23, 23, (10, 0, 0, 0), (35, 0, 0, 0), 0x0447),
        (178, 23, 63, 69, (10, 45, 52, 43), (35, 40, 19, 30), 0x199B),
        (169, 10, 29, 29, (33, 0, 0, 0), (35, 0, 0, 0), 0xA5B3),
        (142, 11, 42, 42, (1, 45, 0, 0), (35, 40, 0, 0), 0x60DA),
        (107, 9, 28, 28, (141, 0, 0, 0), (15, 0, 0, 0), 0x38BF),
    ]
    for i, (species, level, hp, max_hp, moves, pp, dv) in enumerate(slots):
        mon = party[i]
        sym = f"wPartyMon{i + 1}"
        assert mon.species == species, f"{sym} species"
        assert mon.level == level, f"{sym}Level"
        assert mon.hp == hp, f"{sym}HP"
        assert mon.max_hp == max_hp, f"{sym}MaxHP"
        assert mon.status == 0, f"{sym}Status"
        assert mon.moves == moves, f"{sym}Moves"
        assert mon.pp == pp, f"{sym}PP"
        assert mon.ot_id == 55863, f"{sym}OTID"
        assert mon.dv_word == dv, f"{sym}DVs"

    assert list(emu.read_range(wPartySpecies, 6)) == [
        133, 109, 178, 169, 142, 107], "wPartySpecies"

    battle = read_battle_mon(emu)          # stale: slot 2 from an earlier fight
    assert battle.species == 178, "wBattleMon species (stale)"
    assert battle.hp == 63, "wBattleMonHP"
    assert battle.max_hp == 69, "wBattleMonMaxHP"
    assert battle.level == 23, "wBattleMonLevel"

    assert emu.read(wPartyGainExpFlags) == 4, "wPartyGainExpFlags"
    assert emu.read(wPartyFoughtCurrentEnemyFlags) == 4, "wPartyFoughtCurrentEnemyFlags"
    assert emu.read(wEnemyMonPartyPos) == 1, "wEnemyMonPartyPos"

    assert emu.read(wBoxCount) == 2, "wBoxCount"
    assert list(emu.read_range(wBoxSpecies, 3)) == [36, 185, 255], "wBoxSpecies"
    box = [(36, 9, 13, (16, 28, 98, 0)), (185, 9, 13, (71, 0, 0, 0))]
    for i, (species, hp, level, moves) in enumerate(box):
        base = wBoxMons + 33 * i
        assert emu.read(base) == species, f"wBoxMons[{i}] species"
        assert be16(emu, base + 1) == hp, f"wBoxMons[{i}] HP"
        assert emu.read(base + 3) == level, f"wBoxMons[{i}] level"
        assert tuple(emu.read_range(base + 8, 4)) == moves, f"wBoxMons[{i}] moves"
        assert be16(emu, base + 12) == 55863, f"wBoxMons[{i}] OTID"

    assert list(emu.read_range(wBoxMonOT, 11)) == [
        129, 130, 141, 80, 0, 0, 0, 0, 0, 0, 0], "wBoxMonOT"
    assert list(emu.read_range(wBoxMonNicks, 11)) == [
        143, 136, 131, 134, 132, 152, 80, 80, 80, 80, 80], "wBoxMonNicks"
