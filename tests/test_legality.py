"""legality.check: one fixture that passes every invariant, then one byte off per invariant."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent import legality  # noqa: E402
from pokeagent.emulator import FakeEmulator  # noqa: E402
from pokeagent.explorer import stats  # noqa: E402
from pokeagent.grind.xpmath import exp_for_level  # noqa: E402

LEAD, SIZE = 0xD16B, 44
GYARADOS, WARTORTLE = 22, 179          # internal species ids (dex 130, 8)

KB = {"dex_of_internal": {"22": "130", "179": "8", "133": "129", "8": "7"},
      "name_of_internal": {"22": "GYARADOS", "179": "WARTORTLE", "133": "MAGIKARP", "8": "SQUIRTLE"},
      "species_by_dex": {
          "130": {"hp": 95, "atk": 125, "def": 79, "spd": 81, "spc": 100, "name": "GYARADOS",
                  "moves1": ["THRASH"], "growth": "SLOW"},
          "129": {"hp": 20, "atk": 10, "def": 55, "spd": 80, "spc": 20, "name": "MAGIKARP",
                  "moves1": ["SPLASH"], "growth": "SLOW"},
          "8": {"hp": 59, "atk": 63, "def": 80, "spd": 58, "spc": 65, "name": "WARTORTLE",
                "moves1": ["TACKLE"], "growth": "MEDIUM_SLOW"},
          "7": {"hp": 44, "atk": 48, "def": 65, "spd": 43, "spc": 50, "name": "SQUIRTLE",
                "moves1": ["TACKLE"], "growth": "MEDIUM_SLOW"}},
      "learnsets": {
          "MAGIKARP": {"evolves": [{"how": "level", "level": 20, "into": "GYARADOS"}],
                       "learnset": [[15, "TACKLE"]]},
          "GYARADOS": {"evolves": [], "learnset": [[20, "BITE"]]},
          "SQUIRTLE": {"evolves": [{"how": "level", "level": 16, "into": "WARTORTLE"}],
                       "learnset": [[8, "BUBBLE"], [15, "WATER GUN"]]},
          "WARTORTLE": {"evolves": [{"how": "level", "level": 36, "into": "BLASTOISE"}],
                        "learnset": [[24, "BITE"], [31, "WITHDRAW"]]},
          "BLASTOISE": {"evolves": [], "learnset": [[42, "SKULL BASH"]]}},
      "moves": {"150": {"name": "SPLASH", "pp": 40}, "33": {"name": "TACKLE", "pp": 35},
              "44": {"name": "BITE", "pp": 25}, "57": {"name": "SURF", "pp": 15},
              "55": {"name": "WATER GUN", "pp": 25}, "37": {"name": "THRASH", "pp": 20},
              "15": {"name": "CUT", "pp": 30}, "126": {"name": "FLAMETHROWER", "pp": 15}}}
CATALOG = {"items": {"20": {"id": 20, "name": "POTION", "price": 300}, "63": {"id": 63, "name": "S.S.TICKET", "price": 0}}}
HM = {"hms": {"surf": ["GYARADOS", "WARTORTLE"], "cut": ["WARTORTLE"]}}
BASE = {"hp": 95, "attack": 125, "defense": 79, "speed": 81, "special": 100}


def _mon(emu, slot, species, level, growth, base, dv_word=0xF0F5, stat_exp=(0, 0, 0, 0, 0),
         moves=(0, 0, 0, 0), pp=(0, 0, 0, 0), exp=None):
    """Write a full 44-byte party struct whose stats satisfy the stat band exactly."""
    d = stats.dvs(dv_word)
    vals = {k: stats.stat_value(base[k], d[k], stat_exp[i], level, hp=(k == "hp"))
            for i, k in enumerate(stats.STAT_KEYS)}
    b = LEAD + slot * SIZE
    emu.memory[b] = species
    emu.memory[b + 1], emu.memory[b + 2] = vals["hp"] >> 8, vals["hp"] & 255
    emu.memory[b + 3] = emu.memory[b + 33] = level
    for i, mv in enumerate(moves):
        emu.memory[b + 8 + i] = mv
        emu.memory[b + 29 + i] = pp[i]
    exp = exp_for_level(growth, level) if exp is None else exp
    emu.memory[b + 14], emu.memory[b + 15], emu.memory[b + 16] = exp >> 16 & 255, exp >> 8 & 255, exp & 255
    for i, se in enumerate(stat_exp):
        emu.memory[b + 17 + 2 * i], emu.memory[b + 18 + 2 * i] = se >> 8, se & 255
    emu.memory[b + 27], emu.memory[b + 28] = dv_word >> 8, dv_word & 255
    emu.memory[b + 34], emu.memory[b + 35] = vals["hp"] >> 8, vals["hp"] & 255
    for i, k in enumerate(("attack", "defense", "speed", "special")):
        emu.memory[b + 36 + 2 * i], emu.memory[b + 37 + 2 * i] = vals[k] >> 8, vals[k] & 255
    return vals


def world():
    """GYARADOS L20 (SLOW, exp just under the L21 boundary) + WARTORTLE L29 on map 0x61; every invariant passes."""
    emu = FakeEmulator({0xD35E: 0x61, 0xD362: 13, 0xD361: 6, 0xD719: 5, 0xD356: 0b11,
                        0xD347: 0x00, 0xD348: 0x12, 0xD349: 0x34, 0xD163: 2,
                        0xD164: GYARADOS, 0xD165: WARTORTLE, 0xD166: 0xFF, 0xD803: 0})
    g_base = {k: int(KB["species_by_dex"]["130"][v]) for k, v in stats.KB_KEYS.items()}
    w_base = {k: int(KB["species_by_dex"]["8"][v]) for k, v in stats.KB_KEYS.items()}
    _mon(emu, 0, GYARADOS, 20, "SLOW", g_base, stat_exp=(0, 0, 0, 0, 0),
         moves=(150, 33, 44, 57), pp=(40, 35, 25, 15), exp=exp_for_level("SLOW", 21) - 1)
    _mon(emu, 1, WARTORTLE, 29, "MEDIUM_SLOW", w_base, stat_exp=(500, 500, 500, 500, 500),
         moves=(55, 44, 15, 0), pp=(25, 25, 30, 0))
    emu.memory.update({0xD31D: 1, 0xD31E: 0x14, 0xD31F: 5, 0xD320: 0xFF})
    emu.memory[0xD2F7] = emu.memory[0xD30A] = 0x80        # dex 8 (WARTORTLE) owned + seen
    emu.memory[0xD2F7 + 16] = emu.memory[0xD30A + 16] = 0x02   # dex 130 (GYARADOS) owned + seen
    return emu


def check(emu, **kw):
    kw.setdefault("catalog", CATALOG)
    kw.setdefault("hm", HM)
    return legality.check(emu, KB, **kw)


def test_the_fixture_passes_every_invariant():
    r = check(world())
    assert r.ok and r.violations == []
    assert set(r.checked) == {"party_structure", "party_stats", "party_exp", "party_moves", "party_pp",
                            "party_evolution", "bag", "money", "badges", "key_items", "world", "pokedex"}
    assert "badges: gym-beaten flags unverified" in r.warnings and "world: view pointer relation unverified" in r.warnings


@pytest.mark.parametrize("name,edit", [
    ("party_structure", lambda m: m.__setitem__(0xD163, 0)),
    ("party_stats", lambda m: m.__setitem__(LEAD + 37, m[LEAD + 37] + 1)),
    ("party_exp", lambda m: m.__setitem__(LEAD + 16, m[LEAD + 16] + 1)),          # exp hits the L21 boundary
    ("party_moves", lambda m: m.__setitem__(LEAD + 8, 0xEE)),                     # move id not in the table
    ("party_pp", lambda m: m.__setitem__(LEAD + 29, 0x7F)),                       # 63 PP + 1 up over the formula
    ("bag", lambda m: m.__setitem__(0xD31D, 21)),
    ("money", lambda m: m.__setitem__(0xD347, 0xAA)),
    ("pokedex", lambda m: m.__setitem__(0xD2F7, 0)),                              # WARTORTLE no longer owned
])
def test_one_byte_off_per_invariant(name, edit):
    emu = world()
    edit(emu.memory)
    r = check(emu)
    assert not r.ok and any(v.startswith(name) for v in r.violations)


def test_party_structure_terminator_and_species_list_mismatch():
    emu = world()
    emu.memory[0xD166] = 0x00
    r = check(emu)
    assert any(v.startswith("party_structure: species list terminator") for v in r.violations)
    emu = world()
    emu.memory[0xD165] = 133
    r = check(emu)
    assert any(v.startswith("party_structure: slot 1 species list") for v in r.violations)


def test_box_level_is_not_checked_so_zero_is_legal():
    """Box level (struct +3) is 0 for every organic party mon: it must never be a violation, not even a warning."""
    emu = world()
    assert emu.memory[LEAD + SIZE + 3] == 29 and emu.memory[LEAD + SIZE + 33] == 29
    emu.memory[LEAD + SIZE + 3] = 0                                         # WARTORTLE L29 with box level 0
    r = check(emu)
    assert r.ok and not any("box level" in w for w in r.warnings)
    emu.memory[LEAD + 3] = 5                                                # any other box-level value: still legal
    assert check(emu).ok


def test_transient_save_with_empty_struct_is_a_violation_with_its_own_message():
    emu = world()
    emu.memory[0xD164 + 1] = WARTORTLE                                      # species list written, struct zero
    for a in range(LEAD + SIZE, LEAD + 2 * SIZE):                          # slot 1 struct zeroed
        emu.memory[a] = 0
    r = check(emu)
    assert not r.ok
    assert any("transient save (struct empty): not a usable resume point" in v for v in r.violations)


def test_hp_over_max():
    emu = world()
    emu.memory[LEAD + 34], emu.memory[LEAD + 35] = 0, 1                    # max HP 1 under current HP
    r = check(emu)
    assert any("HP" in v and v.startswith("party_structure") for v in r.violations)


def test_stat_band_accepts_lazily_applied_stat_exp():
    emu = world()
    # stored stats computed with the mon's own stat exp (500) pass; se=0 stats also pass (the band covers both)
    r = check(emu)
    assert r.ok
    emu.memory[LEAD + SIZE + 37] += 1                                       # one point above the band fails
    assert any(v.startswith("party_stats") for v in check(emu).violations)


def test_stat_below_the_band_fails():
    emu = world()
    lo = stats.stat_value(BASE["attack"], stats.dvs(0xF0F5)["attack"], 0, 20)
    emu.memory[LEAD + 36], emu.memory[LEAD + 37] = (lo - 1) >> 8, (lo - 1) & 255
    assert any("attack" in v and v.startswith("party_stats") for v in check(emu).violations)


def test_unprovable_move_is_a_warning_not_a_violation():
    emu = world()
    emu.memory[LEAD + 10], emu.memory[LEAD + 31] = 126, 15                  # FLAMETHROWER: not provable here
    r = check(emu)
    assert r.ok and any("not provable" in w and "FLAMETHROWER" in w for w in r.warnings)


def test_evolution_pending_is_a_warning_below_level_is_a_violation():
    emu = world()
    _mon(emu, 1, 133, 20, "SLOW", {k: int(KB["species_by_dex"]["129"][v]) for k, v in stats.KB_KEYS.items()},
         moves=(150, 33, 0, 0), pp=(40, 35, 0, 0))                          # slot 1: MAGIKARP at its evolution level
    emu.memory[0xD165] = 133
    emu.memory[0xD2F7 + 16] = emu.memory[0xD30A + 16] = 0x03                # dex 129 + 130 owned + seen
    r = check(emu)
    assert r.ok and any("evolution pending" in w for w in r.warnings)
    emu.memory[LEAD + SIZE] = emu.memory[0xD165] = GYARADOS                 # the same bytes, now a GYARADOS L5...
    emu.memory[LEAD + SIZE + 33] = emu.memory[LEAD + SIZE + 3] = 5          # ...impossible: pre-form evolves at 20
    r = check(emu)
    assert any(v.startswith("party_evolution") and "GYARADOS L5" in v for v in r.violations)


def test_key_items_hm01_needs_its_flag_and_ss_ticket_warns():
    emu = world()
    emu.memory.update({0xD31D: 1, 0xD31E: 0xC4, 0xD31F: 1, 0xD320: 0xFF})   # HM01 in the bag
    assert any(v.startswith("key_items") for v in check(emu).violations)
    emu.memory[0xD803] = 1
    assert check(emu).ok
    emu = world()
    emu.memory.update({0xD31D: 1, 0xD31E: 0x3F, 0xD31F: 1, 0xD320: 0xFF})   # S.S. Ticket: flag unknown -> warning
    r = check(emu)
    assert r.ok and any("S.S. Ticket" in w for w in r.warnings)


def test_respawn_maps_accept_town_and_route_pokecenters_reject_others():
    for respawn in (0, 5, 10, 15, 21):
        emu = world()
        emu.memory[0xD719] = respawn
        assert not any(v.startswith("world: respawn") for v in check(emu).violations), respawn
    emu = world()
    emu.memory[0xD719] = 99
    assert any(v.startswith("world: respawn") and "99" in v for v in check(emu).violations)


VIEW_ROWS = [  # (map, width_blocks, x, y, expected pointer): validated on organic states
    (90, 4, 2, 1, 0xC6F4),     # bike_voucher
    (40, 5, 6, 4, 0xC70D),     # first_pokemon
    (61, 20, 15, 27, 0xC85C),  # mt_moon_b2f
    (38, 4, 0, 2, 0xC6FD),     # rl_potion
    (90, 4, 2, 7, 0xC712),     # ss_anne_2f@5a
    (99, 10, 13, 6, 0xC72F),   # ss_anne_captain@63
    (36, 30, 0, 8, 0xC79D),    # to_bill@24.best
    (2, 20, 19, 35, 0xC8C6),   # to_pewter
    (16, 10, 17, 0, 0xC701),   # to_route5
    (1, 20, 21, 35, 0xC8C7),   # to_viridian.best
]


@pytest.mark.parametrize("map_id,w,x,y,want", VIEW_ROWS)
def test_expected_view_pointer_matches_validated_states(map_id, w, x, y, want):
    assert legality.expected_view_pointer(map_id, x, y, w) == want


def _walkable_rom(monkeypatch, w):
    hd = SimpleNamespace(map_id=0, tileset=0, h=40, w=w, blocks_ptr=0, border=0,
                         connections=[], warps=[], signs=[], objects=[])
    monkeypatch.setattr(legality.rom_maps, "is_sane", lambda rom, m: True)
    monkeypatch.setattr(legality.rom_maps, "header", lambda rom, m: hd)
    monkeypatch.setattr(legality, "walk_grid", lambda rom, h: [[True] * (h.w * 2) for _ in range(h.h * 2)])


@pytest.mark.parametrize("map_id,w,x,y,want", VIEW_ROWS)
def test_view_pointer_matching_is_silent(monkeypatch, map_id, w, x, y, want):
    _walkable_rom(monkeypatch, w)
    emu = world()
    emu.memory.update({0xD35E: map_id, 0xD362: x, 0xD361: y, 0xD35F: want & 255, 0xD360: want >> 8})
    r = check(emu, rom=b"rom")
    assert r.ok and not any("view pointer" in w_ for w_ in r.warnings)


def test_view_pointer_mismatch_is_a_warning_not_a_violation(monkeypatch):
    _walkable_rom(monkeypatch, 10)
    emu = world()
    emu.memory.update({0xD35E: 0, 0xD362: 2, 0xD361: 7, 0xD35F: 0x12, 0xD360: 0xC7})   # pointer 0xC712
    r = check(emu, rom=b"rom")
    assert r.ok and "world: view pointer 0xC712 != expected 0xC72A (transitional saves differ)" in r.warnings


def test_view_pointer_without_header_keeps_the_unverified_warning():
    r = check(world())
    assert "world: view pointer relation unverified" in r.warnings


def test_world_glitch_map_and_bad_respawn():
    emu = world()
    emu.memory[0xD35E] = 0xFF
    assert any(v.startswith("world: glitch map") for v in check(emu).violations)
    emu = world()
    emu.memory[0xD719] = 11
    assert any(v.startswith("world: respawn") for v in check(emu).violations)


def test_world_walk_grid_with_a_fake_rom(monkeypatch):
    hd = SimpleNamespace(map_id=0x61, tileset=0, h=9, w=10, blocks_ptr=0, border=0,
                         connections=[], warps=[], signs=[], objects=[])
    monkeypatch.setattr(legality.rom_maps, "is_sane", lambda rom, m: True)
    monkeypatch.setattr(legality.rom_maps, "header", lambda rom, m: hd)
    grid = [[True] * 20 for _ in range(18)]
    monkeypatch.setattr(legality, "walk_grid", lambda rom, h: grid)
    assert check(world(), rom=b"rom").ok
    grid[6][13] = False                                                    # standing on an unwalkable cell
    r = check(world(), rom=b"rom")
    assert any(v.startswith("world: (") and "not walkable" in v for v in r.violations)
    emu = world()
    emu.memory[0xD362] = 30                                                  # outside a 20-wide map
    grid[6][13] = True
    r = check(emu, rom=b"rom")
    assert any("outside map" in v for v in r.violations)


def test_no_kb_and_a_bare_emulator_never_raise():
    r = legality.check(world(), None)
    assert r.ok and any("no kb" in w for w in r.warnings)
    assert not (set(r.checked) & set(legality.PARTY_TABLE_INVARIANTS))

    class Bare:
        def read(self, a):
            raise OSError("gone")

        def read_range(self, a, n):
            raise OSError("gone")

    r = legality.check(Bare(), None)
    assert not r.ok and any(v.startswith("read:") for v in r.violations)


def test_empty_party_is_legal_and_overfull_is_not():
    """The bedroom start state is organic with an empty party: count 0 passes party_structure."""
    emu = FakeEmulator({0xD35E: 0x26, 0xD163: 0, 0xD164: 0xFF})
    assert "party_structure" not in " ".join(check(emu).violations)
    emu.memory[0xD164] = 0x33                                  # species list not terminated
    assert any(v.startswith("party_structure") for v in check(emu).violations)
    emu.memory.update({0xD163: 7, 0xD164: 0xFF})
    assert any(v.startswith("party_structure") for v in check(emu).violations)


def test_empty_kb_dict_warns_like_none():
    assert any("no kb" in w for w in legality.check(world(), {}).warnings)
