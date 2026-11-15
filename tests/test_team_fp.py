"""fp["team"] records each member's moves; team_fp.build_key groups evolution lines, rounds levels down to 5,
ignores moves and party order; a fingerprint without ``team`` has no build (verdict unknown)."""
from pokeagent import party_rules, statefp, team_fp
from pokeagent.emulator import FakeEmulator

LEAD, SIZE = 0xD16B, 44
HARDEN, POISON_STING, TACKLE, EMBER, CUT = 106, 40, 33, 1, 15
KB = {"name_of_internal": {"112": "WEEDLE", "113": "KAKUNA", "114": "BEEDRILL", "176": "CHARMANDER",
                           "178": "CHARMELEON", "36": "PIDGEY", "165": "RATTATA"},
      "moves": {"1": {"name": "EMBER", "power": 40}, "15": {"name": "CUT", "power": 50},
                "33": {"name": "TACKLE", "power": 35}, "40": {"name": "POISON STING", "power": 15},
                "106": {"name": "HARDEN", "power": 0}}}


def _mon(emu, slot, species, level, moves=(0, 0, 0, 0), hp=20, mx=20, ot=0x1234, exp=321):
    b = LEAD + slot * SIZE
    emu.memory.update({b: species, b + 1: hp >> 8, b + 2: hp & 255, b + 3: level,
                       b + 12: ot >> 8, b + 13: ot & 255,
                       b + 14: exp >> 16 & 255, b + 15: exp >> 8 & 255, b + 16: exp & 255,
                       b + 33: level, b + 34: mx >> 8, b + 35: mx & 255})
    for i, mv in enumerate(moves):
        emu.memory[b + 8 + i] = mv


def world(mons):
    """A FakeEmulator whose party is [(species, level, moves)]."""
    emu = FakeEmulator({0xD35E: 14, 0xD362: 5, 0xD361: 3, 0xD719: 2, 0xD356: 0b1,
                        0xD163: len(mons), 0xD31D: 0, 0xD31E: 0xFF})
    for i, (sp, lv, mv) in enumerate(mons):
        _mon(emu, i, sp, lv, mv)
    return emu


def member(species, level, moves=()):
    return {"species": species, "level": level, "moves": list(moves), "hp": 10, "max_hp": 20, "ot_id": 1, "exp": 5}


def test_fingerprint_records_team_with_moves():
    fp = statefp.fingerprint(world([(113, 4, (HARDEN, 0, 0, 0)), (176, 13, (EMBER, TACKLE, 0, 0))]),
                             source_run="explore-x")
    assert fp["v"] == statefp.VERSION == 1                                     # the version stays
    assert fp["party"] == [[113, 4, 20, 20], [176, 13, 20, 20]]                 # the old summary stays
    assert fp["team"][0] == {"species": 113, "level": 4, "moves": [HARDEN, 0, 0, 0], "hp": 20,
                            "max_hp": 20, "ot_id": 0x1234, "exp": 321}
    assert fp["team"][1]["moves"] == [EMBER, TACKLE, 0, 0] and fp["source_run"] == "explore-x"


def test_build_key_groups_lines_rounds_levels_ignores_moves_and_order():
    a = {"team": [member(113, 7, (HARDEN,)), member(176, 13, (EMBER,))]}        # KAKUNA L7, CHARMANDER L13
    b = {"team": [member(176, 14, (TACKLE,)), member(114, 9, (POISON_STING,))]}  # CHARMANDER L14, BEEDRILL L9
    assert team_fp.build_key(a, KB) == team_fp.build_key(b, KB) == "CHARMANDER:L10|WEEDLE:L5"


def test_species_line_walks_the_evolution_table_backwards():
    assert team_fp.species_line(114, KB) == team_fp.species_line(113, KB) == "WEEDLE"
    assert team_fp.species_line(112, KB) == "WEEDLE" and team_fp.species_line(178, KB) == "CHARMANDER"
    assert team_fp.species_line(999, KB) == "999"                             # unknown species: its own id


def test_no_team_means_no_build_and_an_unknown_verdict():
    fp = {"v": 1, "party": [[113, 4, 5, 9]]}                                  # a v1 sidecar from before team
    assert team_fp.build_key(fp, KB) is None and team_fp.build_key({}, KB) is None
    assert party_rules.verdict(fp, KB) == "unknown" and party_rules.verdict({}, KB) == "unknown"


def test_moves_of_resolves_names_and_drops_unknown_ids():
    assert team_fp.moves_of(member(113, 4, (HARDEN, POISON_STING, 0, 7)), KB) == {"HARDEN", "POISON STING"}
    assert team_fp.moves_of(member(113, 4), KB) == frozenset()


def test_hm_capable_by_learnset_and_by_known_move():
    hm_table = {"cut": frozenset({"PIDGEY"}), "surf": frozenset({"GYARADOS"})}
    assert team_fp.hm_capable({"team": [member(36, 9)]}, KB, hm_table) == {"cut"}
    assert team_fp.hm_capable({"team": [member(165, 9, (CUT,))]}, KB, {"cut": frozenset()}) == {"cut"}
    assert team_fp.hm_capable({"team": [member(165, 9, (CUT,))]}, KB, None) == frozenset()


def test_provenance_starter_wild_caught_unknown():
    assert team_fp.provenance(member(113, 4, (HARDEN,)), KB, "CHARMANDER") == "wild-caught-harden-only"
    assert team_fp.provenance(member(178, 16), KB, "CHARMANDER") == "starter"
    assert team_fp.provenance(member(178, 16), KB) == "unknown"
