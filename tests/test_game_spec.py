from pathlib import Path

import pytest

from pokeagent.game import GAMES, GameSpec, RED
from pokeagent.game.spec import LEGACY_FAMILY

_KW = dict(
    key="x-game",
    title="x",
    rom_sha1=("A" * 40,),
    default_rom=Path("roms/x.gb"),
    screen=(160, 144),
    buttons=("up", "a"),
    memory_family="x-game",
    owns_legacy_paths=False,
)


def _spec(**kw) -> GameSpec:
    return GameSpec(**{**_KW, **kw})


def test_red_is_valid():
    assert RED.key == "pokemon-red"
    assert RED.title == "Pokemon Red"
    assert len(RED.rom_sha1) == 1
    assert len(RED.rom_sha1[0]) == 40


def test_red_carries_the_current_values():
    assert RED.default_rom == Path("roms/Pokemon Red.gb")
    assert RED.screen == (160, 144)
    assert RED.buttons == ("up", "down", "left", "right", "a", "b", "start", "select")


def test_bad_key_rejected():
    for key in ("Pokemon Red", "pokemon_red", "-red", "red-", "red--x", ""):
        with pytest.raises(ValueError):
            _spec(key=key)


def test_empty_hash_tuple_rejected():
    with pytest.raises(ValueError):
        _spec(rom_sha1=())


def test_lowercase_hash_rejected():
    with pytest.raises(ValueError):
        _spec(rom_sha1=("a" * 40,))


def test_short_hash_rejected():
    with pytest.raises(ValueError):
        _spec(rom_sha1=("A" * 39,))


def test_non_hex_hash_rejected():
    with pytest.raises(ValueError):
        _spec(rom_sha1=("G" * 40,))


def test_absolute_default_rom_rejected():
    for bad in (Path("C:/roms/x.gb"), Path("/roms/x.gb")):
        with pytest.raises(ValueError):
            _spec(default_rom=bad)


def test_suffixless_default_rom_rejected():
    with pytest.raises(ValueError):
        _spec(default_rom=Path("roms/x"))


def test_bad_screen_rejected():
    for screen in ((160,), (160, 144, 3), (0, 144), (-1, 2), "160x144"):
        with pytest.raises(ValueError):
            _spec(screen=screen)


def test_empty_buttons_rejected():
    with pytest.raises(ValueError):
        _spec(buttons=())


def test_duplicate_buttons_rejected():
    with pytest.raises(ValueError):
        _spec(buttons=("a", "a"))


def test_uppercase_buttons_rejected():
    with pytest.raises(ValueError):
        _spec(buttons=("A",))


def test_unknown_buttons_rejected():
    with pytest.raises(ValueError):
        _spec(buttons=("up", "turbo"))


def test_red_joins_the_legacy_family_and_owns_its_paths():
    assert RED.memory_family == LEGACY_FAMILY == "gen1-pokemon"
    assert RED.owns_legacy_paths is True


def test_bad_memory_family_rejected():
    for fam in ("Gen 1", "gen_1", "-gen1", "gen1-", ""):
        with pytest.raises(ValueError):
            _spec(memory_family=fam)


def test_owns_legacy_paths_requires_the_legacy_family():
    with pytest.raises(ValueError):
        _spec(owns_legacy_paths=True, memory_family="x-game")
    _spec(owns_legacy_paths=True, memory_family=LEGACY_FAMILY)  # allowed


def test_registry_holds_at_most_one_legacy_owner():
    assert sum(1 for g in GAMES.values() if g.owns_legacy_paths) <= 1


def test_no_nonlegacy_family_names_a_different_games_key():
    for g in GAMES.values():
        if g.memory_family != LEGACY_FAMILY:
            assert g.memory_family not in {k for k in GAMES if k != g.key}
