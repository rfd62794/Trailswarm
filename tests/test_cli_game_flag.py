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
    for cmd in ("world", "states", "view"):
        with pytest.raises(SystemExit) as exc:
            cli.main([cmd, "--game", "pokemon-red"])
        assert exc.value.code == 2
