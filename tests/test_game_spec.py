import pytest

from pokeagent.game import GameSpec, RED


def test_red_is_valid():
    assert RED.key == "pokemon-red"
    assert RED.title == "Pokemon Red"
    assert len(RED.rom_sha1) == 1
    assert len(RED.rom_sha1[0]) == 40


def test_bad_key_rejected():
    for key in ("Pokemon Red", "pokemon_red", "-red", "red-", "red--x", ""):
        with pytest.raises(ValueError):
            GameSpec(key=key, title="x", rom_sha1=("A" * 40,))


def test_empty_hash_tuple_rejected():
    with pytest.raises(ValueError):
        GameSpec(key="pokemon-red", title="x", rom_sha1=())


def test_lowercase_hash_rejected():
    with pytest.raises(ValueError):
        GameSpec(key="pokemon-red", title="x", rom_sha1=("a" * 40,))


def test_short_hash_rejected():
    with pytest.raises(ValueError):
        GameSpec(key="pokemon-red", title="x", rom_sha1=("A" * 39,))


def test_non_hex_hash_rejected():
    with pytest.raises(ValueError):
        GameSpec(key="pokemon-red", title="x", rom_sha1=("G" * 40,))
