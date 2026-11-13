"""Blue (family sibling) and Yellow (own family, gated): specs, selection, check-rom, state guard, store paths, symbol seam."""
import dataclasses
import hashlib
import json

import pytest

from pokeagent import cli
from pokeagent.emulator import FakeEmulator, PyBoyEmulator
from pokeagent.game import BLUE, GAMES, RED, YELLOW, resolve_game
from pokeagent.game.gate import (NotPlayable, adopt_rom_game, find_rom, game_for_rom, game_for_sha1,
                                 require_playable)
from pokeagent.game.spec import LEGACY_FAMILY
from pokeagent.game.state_guard import StateGameMismatch, check_state_game
from pokeagent.game.stores import store_path
from pokeagent.game.symbols import SymbolTableMissing, ram_table_text, symbol_table
from pokeagent.ram_lookup import load_map


def test_blue_spec_facts():
    assert BLUE.key == "pokemon-blue" and GAMES["pokemon-blue"] is BLUE
    assert BLUE.rom_sha1 == ("D7037C83E1AE5B39BDE3C30787637BA1D4C48CE2",)
    assert str(BLUE.default_rom).replace("\\", "/") == "roms/Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb"
    assert BLUE.memory_family == LEGACY_FAMILY and BLUE.owns_legacy_paths is False and BLUE.playable


def test_yellow_spec_is_gated_with_its_own_family():
    assert YELLOW.key == "pokemon-yellow" and YELLOW.memory_family == "gen1-yellow"
    assert YELLOW.rom_sha1 == ("CC7D03262EBFAF2F06772C1A480C7D9D5F4A38E1",)
    assert not YELLOW.playable and "not playable yet" in YELLOW.gate
    assert "Yellow Version - Special Pikachu Edition" in str(YELLOW.default_rom)


def test_a_gated_spec_needs_a_gate_message():
    with pytest.raises(ValueError):
        dataclasses.replace(YELLOW, gate="")


def test_resolve_game_and_hash_detection(tmp_path):
    assert resolve_game("pokemon-blue") is BLUE
    assert game_for_sha1(RED.rom_sha1[0].lower()) is RED
    assert game_for_sha1(BLUE.rom_sha1[0]) is BLUE and game_for_sha1("0" * 40) is None
    rom = tmp_path / "x.gb"
    rom.write_bytes(b"unknown")
    assert game_for_rom(rom) is None and game_for_rom(tmp_path / "missing.gb") is None
    assert find_rom(BLUE, tmp_path) is None


def test_rom_argument_selects_the_game_and_conflicts_fail(tmp_path, monkeypatch):
    data = b"blue-ish"
    monkeypatch.setitem(GAMES, "pokemon-blue",
                        dataclasses.replace(BLUE, rom_sha1=(hashlib.sha1(data).hexdigest().upper(),)))
    rom = tmp_path / "b.gb"
    rom.write_bytes(data)
    env = {}
    assert adopt_rom_game(["--rom", str(rom)], env).key == "pokemon-blue" and env["POKEAGENT_GAME"] == "pokemon-blue"
    assert adopt_rom_game([f"--rom={rom}"], {}).key == "pokemon-blue"
    with pytest.raises(SystemExit):
        adopt_rom_game(["--rom", str(rom)], {"POKEAGENT_GAME": "pokemon-red"})
    assert adopt_rom_game(["--steps", "3"], {}) is None


def test_check_rom_game_blue_uses_blues_hash_and_path(tmp_path, monkeypatch, capsys):
    data = b"pretend blue"
    monkeypatch.setitem(GAMES, "pokemon-blue",
                        dataclasses.replace(BLUE, rom_sha1=(hashlib.sha1(data).hexdigest().upper(),)))
    rom = tmp_path / "b.gb"
    rom.write_bytes(data)
    monkeypatch.setattr(cli, "_build_emulator", lambda args: FakeEmulator())
    assert cli.main(["check-rom", "--game", "pokemon-blue", "--rom", str(rom)]) == 0
    assert "mismatch" not in capsys.readouterr().out
    assert cli.main(["check-rom", "--game", "pokemon-red", "--rom", str(rom)]) == 1  # Red's hash refuses it


def test_default_rom_follows_the_game_flag(monkeypatch):
    monkeypatch.delenv("POKEAGENT_ROM", raising=False)
    args = cli._build_parser().parse_args(["check-rom", "--game", "pokemon-blue"])
    assert "Blue Version" in str(cli._rom_path(args))


def test_check_rom_yellow_verifies_hash_then_says_not_playable(tmp_path, monkeypatch, capsys):
    data = b"pretend yellow"
    monkeypatch.setitem(GAMES, "pokemon-yellow",
                        dataclasses.replace(YELLOW, rom_sha1=(hashlib.sha1(data).hexdigest().upper(),)))
    rom = tmp_path / "y.gb"
    rom.write_bytes(data)
    boot = []
    monkeypatch.setattr(cli, "_build_emulator", lambda args: boot.append(1) or FakeEmulator())
    assert cli.main(["check-rom", "--game", "pokemon-yellow", "--rom", str(rom)]) == 0
    out = capsys.readouterr().out
    assert "match" in out.split() and "NOT PLAYABLE YET" in out and not boot  # never booted
    rom.write_bytes(b"other")
    assert cli.main(["check-rom", "--game", "pokemon-yellow", "--rom", str(rom)]) == 1


def test_run_state_mcp_refuse_a_gated_game(monkeypatch, capsys, tmp_path):
    assert cli.main(["run", "--game", "pokemon-yellow", "--rom", str(tmp_path / "x.gb")]) == 2
    assert "not playable yet" in capsys.readouterr().out
    assert cli.main(["state", "--game", "pokemon-yellow", "--rom", str(tmp_path / "x.gb")]) == 2


def test_emulator_and_gate_refuse_yellow(tmp_path):
    with pytest.raises(NotPlayable):
        require_playable(YELLOW)
    rom = tmp_path / "y.gb"
    rom.write_bytes(b"x")
    with pytest.raises(NotPlayable):
        PyBoyEmulator(rom, game=YELLOW)


def _state(tmp_path, key, name):
    st = tmp_path / name
    st.write_bytes(b"opaque")
    st.with_name(name + ".meta.json").write_text(json.dumps({"game_key": key}), encoding="utf-8")
    return st


def test_blue_and_red_states_are_never_exchanged(tmp_path):
    blue, red = _state(tmp_path, "pokemon-blue", "b.state"), _state(tmp_path, "pokemon-red", "r.state")
    check_state_game(blue, BLUE)
    check_state_game(red, RED)
    with pytest.raises(StateGameMismatch):
        check_state_game(blue, RED)
    with pytest.raises(StateGameMismatch):
        check_state_game(red, BLUE)
    legacy = tmp_path / "legacy.state"
    legacy.write_bytes(b"x")
    check_state_game(legacy, RED)  # an unlabeled state is Red's
    with pytest.raises(StateGameMismatch):
        check_state_game(legacy, BLUE)


def test_blue_resolves_to_reds_family_store_paths_but_its_own_states():
    for rel in ("runs/maps.json", "runs/bandit.json", "runs/novelty.json", "runs/loops.json", "kb/rom_tables.json"):
        assert store_path(rel, BLUE) == store_path(rel, RED)
    assert store_path("runs/checkpoints", RED).as_posix() == "runs/checkpoints"
    assert store_path("runs/checkpoints", BLUE, scope="game").as_posix() == "runs/pokemon-blue/checkpoints"
    assert store_path("runs/maps.json", YELLOW).as_posix() == "runs/gen1-yellow/maps.json"


def test_red_and_blue_share_a_symbol_table_and_yellow_has_none():
    assert symbol_table(BLUE) == symbol_table(RED) and symbol_table(RED)["IS_IN_BATTLE"] == 0xD057
    with pytest.raises(SymbolTableMissing):
        symbol_table(YELLOW)
    with pytest.raises(SymbolTableMissing):
        ram_table_text(YELLOW)
    with pytest.raises(SymbolTableMissing):
        load_map(YELLOW)
    assert len(load_map(RED)) == len(load_map()) == len(load_map(BLUE))
