from pathlib import Path

import pytest

from pokeagent.game import RED, UnknownGame
from pokeagent.game.paths import default_rom


def test_red_rom_is_the_old_relative_path():
    assert default_rom(RED) == Path("roms/Pokemon Red.gb")


def test_no_arg_resolves_the_selected_game(monkeypatch):
    monkeypatch.delenv("POKEAGENT_GAME", raising=False)
    assert default_rom() == Path("roms/Pokemon Red.gb")


def test_pokeagent_game_env_is_honoured(monkeypatch):
    monkeypatch.setenv("POKEAGENT_GAME", "pokemon-red")
    assert default_rom() == RED.default_rom


def test_unknown_env_fails_like_resolve_game(monkeypatch):
    monkeypatch.setenv("POKEAGENT_GAME", "nope")
    with pytest.raises(UnknownGame):
        default_rom()


def test_root_joins_the_relative_path(tmp_path):
    assert default_rom(RED, root=tmp_path) == tmp_path / "roms" / "Pokemon Red.gb"
    assert default_rom(root=tmp_path) == tmp_path / "roms" / "Pokemon Red.gb"


def test_pokeagent_rom_env_is_not_read(monkeypatch):
    monkeypatch.setenv("POKEAGENT_ROM", "env.gb")
    assert default_rom(RED) == Path("roms/Pokemon Red.gb")
