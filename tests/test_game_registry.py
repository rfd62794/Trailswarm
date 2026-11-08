import pytest

from pokeagent.game import DEFAULT_GAME, GAMES, RED, get_game


def test_games_holds_exactly_red():
    assert GAMES == {"pokemon-red": RED}
    assert set(GAMES) == {"pokemon-red"}


def test_default_game_is_red():
    assert DEFAULT_GAME == "pokemon-red"
    assert get_game(DEFAULT_GAME) is RED


def test_unknown_key_raises_keyerror_naming_known_keys():
    with pytest.raises(KeyError) as exc:
        get_game("nope")
    assert "pokemon-red" in str(exc.value)
    assert "nope" in str(exc.value)
