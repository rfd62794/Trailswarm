"""ram_symbols: every named WRAM constant the party/battle view reads lives in one module, at its
documented address, and is the same number the legacy readers used."""
from __future__ import annotations

import pokeagent.ram_symbols as rs

EXPECTED = {
    "PARTY_COUNT": 0xD163, "PARTY_SPECIES": 0xD164, "PARTY_MON1": 0xD16B, "PARTY_MON_SIZE": 44,
    "PARTY_MON1_HP": 0xD16C, "PARTY_MON1_MOVES": 0xD173, "PARTY_MON1_LEVEL": 0xD18C,
    "PARTY_MON1_MAX_HP": 0xD18D,
    "MAX_PARTY": 6, "PARTY_MON_OT": 0xD273, "PARTY_MON_NICKS": 0xD2B5, "NAME_SIZE": 11,
    "BATTLE_MON": 0xD014, "ENEMY_MON": 0xCFE5, "BATTLE_STRUCT_SIZE": 29,
    "BATTLE_MON_HP": 0xD015, "BATTLE_MON_MOVES": 0xD01C, "BATTLE_MON_LEVEL": 0xD022,
    "BATTLE_MON_MAX_HP": 0xD023,
    "BATTLE_MON_PP": 0xD02D, "ENEMY_MON_PP": 0xCFFE, "IS_IN_BATTLE": 0xD057,
    "PLAYER_MON_NUMBER": 0xCC2F, "ENEMY_MON_PARTY_POS": 0xCFE8,
    "PARTY_GAIN_EXP_FLAGS": 0xD058, "PARTY_FOUGHT_ENEMY_FLAGS": 0xCCF5,
    "ENEMY_PARTY_COUNT": 0xD89C, "ENEMY_PARTY_SPECIES": 0xD89D, "ENEMY_MONS": 0xD8A4,
    "ENEMY_MON_SIZE": 44, "BOX_COUNT_ADDR": 0xDA80, "BOX_SPECIES": 0xDA81, "BOX_MONS": 0xDA96,
    "BOX_MON_SIZE": 33, "BOX_MON_OT": 0xDD2A, "BOX_MON_NICKS": 0xDE06,
    "MENU_ITEM": 0xCC26, "TRAINER_CLASS": 0xD031, "TRAINER_NO": 0xD05D, "SPECIES_MAGIKARP": 133,
}


def test_every_section_3_1_symbol_is_named_at_its_address():
    for name, addr in EXPECTED.items():
        assert getattr(rs, name) == addr, name


def test_no_extra_public_constants():
    public = {n for n in dir(rs) if n.isupper()}
    assert public == set(EXPECTED)


def test_struct_sizes():
    assert (rs.PARTY_MON_SIZE, rs.ENEMY_MON_SIZE, rs.BOX_MON_SIZE, rs.BATTLE_STRUCT_SIZE) == (44, 44, 33, 29)


def test_ramstructs_and_magikarp_names_alias_the_symbols():
    import pokeagent.magikarp as mk
    import pokeagent.ramstructs as rt
    assert rt.PARTY_COUNT == rs.PARTY_COUNT and rt.PARTY_MON1 == rs.PARTY_MON1
    assert rt.PLAYER_MON == rs.PLAYER_MON_NUMBER
    assert mk.MAGIKARP == rs.SPECIES_MAGIKARP and mk.IN_BATTLE == rs.IS_IN_BATTLE
