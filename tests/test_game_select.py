import argparse

import pytest

from pokeagent.game import (
    DEFAULT_GAME,
    RED,
    UnknownGame,
    add_game_argument,
    resolve_game,
)


def test_arg_wins_over_env():
    spec = resolve_game("pokemon-red", env={"POKEAGENT_GAME": "nope"})
    assert spec is RED


def test_env_used_when_no_arg():
    assert resolve_game(None, env={"POKEAGENT_GAME": "pokemon-red"}) is RED


def test_default_when_nothing_set():
    spec = resolve_game(None, env={})
    assert spec is RED
    assert spec.key == DEFAULT_GAME


def test_empty_env_ignored():
    assert resolve_game(None, env={"POKEAGENT_GAME": ""}) is RED


def test_unknown_arg_raises_unknown_game_listing_keys():
    with pytest.raises(UnknownGame) as exc:
        resolve_game("nope", env={})
    assert isinstance(exc.value, ValueError)
    assert "pokemon-red" in str(exc.value)


def test_unknown_env_raises_unknown_game_listing_keys():
    with pytest.raises(UnknownGame) as exc:
        resolve_game(None, env={"POKEAGENT_GAME": "nope"})
    assert "pokemon-red" in str(exc.value)


def test_add_game_argument_defaults_to_none():
    parser = argparse.ArgumentParser()
    add_game_argument(parser)
    assert parser.parse_args([]).game is None
    assert parser.parse_args(["--game", "pokemon-red"]).game == "pokemon-red"
