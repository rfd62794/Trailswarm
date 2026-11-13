import dataclasses
import hashlib

import pytest

from pokeagent import cli
from pokeagent.emulator import FakeEmulator
from pokeagent.game import GAMES, RED


def test_run_accepts_game(tmp_path, monkeypatch):
    fake = FakeEmulator()
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(
        ["run", "--game", "pokemon-red", "--backend", "stub", "--steps", "1",
         "--headless", "--runs-dir", str(tmp_path / "runs")]
    )
    assert rc == 0
    assert fake.closed


def test_state_accepts_game(tmp_path, monkeypatch, capsys):
    fake = FakeEmulator()
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(["state", "--game", "pokemon-red",
                   "--rom", str(tmp_path / "any.gb")])
    assert rc == 0
    assert "map=" in capsys.readouterr().out


def test_mcp_accepts_game(monkeypatch):
    import pokeagent.mcp_server as mcp_server

    seen = {}
    monkeypatch.setattr(
        mcp_server, "serve",
        lambda rom, state, headless, idle_fps: seen.update(rom=rom) or 0,
    )
    assert cli.main(["mcp", "--game", "pokemon-red"]) == 0
    assert seen["rom"] == cli.DEFAULT_ROM


def test_check_rom_accepts_game(tmp_path, monkeypatch, capsys):
    rom = tmp_path / "fake.gb"
    data = b"a red rom shaped file"
    rom.write_bytes(data)
    sha1 = hashlib.sha1(data).hexdigest().upper()
    monkeypatch.setitem(
        GAMES, "pokemon-red",
        dataclasses.replace(RED, rom_sha1=(sha1,)),
    )
    monkeypatch.setattr(cli, "_build_emulator", lambda args: FakeEmulator())
    rc = cli.main(["check-rom", "--game", "pokemon-red", "--rom", str(rom)])
    out = capsys.readouterr().out
    assert out == (
        f"size: {len(data)} bytes\n"
        f"sha1: {sha1}\n"
        "match\n"
        "boot ok\n"
    )
    assert rc == 0


def test_unknown_game_exits_2_and_names_keys(tmp_path, capsys):
    assert cli.main(["run", "--game", "nope"]) == 2
    assert cli.main(["check-rom", "--game", "nope",
                     "--rom", str(tmp_path / "x.gb")]) == 2
    assert cli.main(["state", "--game", "nope"]) == 2
    assert cli.main(["mcp", "--game", "nope"]) == 2
    out = capsys.readouterr().out
    assert out.count("error:") == 4
    assert "pokemon-red" in out
    assert "nope" in out


def test_bad_game_env_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POKEAGENT_GAME", "nonsense")
    rc = cli.main(["check-rom", "--rom", str(tmp_path / "x.gb")])
    assert rc == 2
    out = capsys.readouterr().out
    assert "error:" in out
    assert "pokemon-red" in out


def test_other_subcommands_do_not_gain_the_flag():
    # `view` is deliberately absent: the Unified World view directive gives it its own --game, which
    # names a mapview preset row (super-mario-land, pokemon-red), not the shared GameSpec registry
    # that add_game_argument serves; it is validated by viewer.app.check_launch.
    for cmd in ("world", "states"):
        with pytest.raises(SystemExit) as exc:
            cli.main([cmd, "--game", "pokemon-red"])
        assert exc.value.code == 2


class _CapturingEmu:
    def __init__(self, rom, headless=True, game=None):
        self.game = game


def _rom_with_hash(tmp_path, monkeypatch, key):
    """A fake ROM file whose SHA-1 is registered as ``key``'s (no real ROM involved)."""
    data = b"fake " + key.encode()
    rom = tmp_path / "x.gb"
    rom.write_bytes(data)
    sha1 = hashlib.sha1(data).hexdigest().upper()
    monkeypatch.setitem(GAMES, key, dataclasses.replace(GAMES[key], rom_sha1=(sha1,)))
    return rom


def _args(rom, game=None):
    return cli._build_parser().parse_args(["run", "--rom", str(rom)] + (["--game", game] if game else []))


def test_no_game_flag_lets_rom_hash_decide(tmp_path, monkeypatch):
    monkeypatch.delenv("POKEAGENT_GAME", raising=False)
    monkeypatch.setattr(cli, "PyBoyEmulator", _CapturingEmu)
    rom = _rom_with_hash(tmp_path, monkeypatch, "pokemon-blue")
    assert cli._build_emulator(_args(rom)).game is None  # emulator's game_for_rom then selects BLUE
    from pokeagent.game.gate import game_for_rom
    assert game_for_rom(rom).key == "pokemon-blue"


def test_explicit_game_conflicting_with_rom_hash_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("POKEAGENT_GAME", raising=False)
    monkeypatch.setattr(cli, "PyBoyEmulator", _CapturingEmu)
    rom = _rom_with_hash(tmp_path, monkeypatch, "pokemon-blue")
    with pytest.raises(cli.BackendError, match="pokemon-blue"):
        cli._build_emulator(_args(rom, "pokemon-red"))
    assert cli.main(["run", "--rom", str(rom), "--game", "pokemon-red", "--steps", "1"]) == 1


def test_unknown_hash_without_game_falls_back_to_red(tmp_path, monkeypatch):
    monkeypatch.delenv("POKEAGENT_GAME", raising=False)
    rom = tmp_path / "unknown.gb"
    rom.write_bytes(b"nobody registered this")
    seen = {}

    def fake(rom_path, headless=True, game=None):
        seen["game"] = game
        raise FileNotFoundError("stop here")
    monkeypatch.setattr(cli, "PyBoyEmulator", fake)
    cli.main(["run", "--rom", str(rom), "--steps", "1"])
    assert seen["game"] is None
    # the real constructor's fallback: an unknown hash with no game boots as Red (PyBoy itself is stubbed out)
    import pokeagent.emulator as emu_mod
    monkeypatch.setattr(emu_mod, "PyBoy", lambda *a, **k: type("P", (), {"set_emulation_speed": lambda s, v: None})())
    assert emu_mod.PyBoyEmulator(rom, headless=True).game is RED


def test_check_rom_without_game_reports_the_detected_game(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("POKEAGENT_GAME", raising=False)
    data = b"blue stand-in"
    blue = dataclasses.replace(GAMES["pokemon-blue"], rom_sha1=(hashlib.sha1(data).hexdigest().upper(),))
    rom = tmp_path / "b.gb"
    rom.write_bytes(data)
    monkeypatch.setattr(cli, "game_for_rom", lambda p: blue)
    monkeypatch.setattr(cli, "_build_emulator", lambda args: FakeEmulator())
    cli.main(["check-rom", "--rom", str(rom)])
    out = capsys.readouterr().out
    assert "\nmatch\n" in out and "mismatch" not in out
