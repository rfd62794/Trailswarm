import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeagent import cli
from pokeagent.emulator import FakeEmulator


def test_run_claude_without_steps_refuses(tmp_path, capsys):
    rc = cli.main(["run", "--backend", "claude", "--runs-dir", str(tmp_path / "runs")])
    assert rc == 2
    out = capsys.readouterr().out
    assert "refusing: --steps is required for a real backend" in out
    assert "each step is one claude call" in out
    assert not (tmp_path / "runs").exists()  # refused before touching anything


def test_run_stub_three_steps(tmp_path, monkeypatch):
    fake = FakeEmulator()
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    runs = tmp_path / "runs"
    rc = cli.main(
        ["run", "--backend", "stub", "--steps", "3", "--headless",
         "--runs-dir", str(runs)]
    )
    assert rc == 0
    logs = list(runs.glob("*/log.jsonl"))
    assert len(logs) == 1
    assert len(logs[0].read_text(encoding="utf-8").splitlines()) == 3
    assert len(fake.presses) == 3
    assert fake.closed


def test_run_interrupted_returns_130(tmp_path, monkeypatch):
    class InterruptBackend:
        name = "interrupt"

        def choose(self, prompt):
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_build_emulator", lambda args: FakeEmulator())
    monkeypatch.setattr(cli, "_build_backend", lambda args, log: InterruptBackend())
    rc = cli.main(
        ["run", "--backend", "stub", "--steps", "5", "--runs-dir", str(tmp_path / "runs")]
    )
    assert rc == 130


def test_help_lists_three_subcommands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "run" in out
    assert "check-rom" in out
    assert "state" in out


def test_check_rom_missing_file(tmp_path, capsys):
    rc = cli.main(["check-rom", "--rom", str(tmp_path / "nope.gb")])
    assert rc == 1
    assert "ROM not found" in capsys.readouterr().out


def test_check_rom_mismatch_still_boots(tmp_path, monkeypatch, capsys):
    rom = tmp_path / "fake.gb"
    rom.write_bytes(b"not a real rom")
    fake = FakeEmulator()
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(["check-rom", "--rom", str(rom)])
    out = capsys.readouterr().out
    assert f"size: {len(b'not a real rom')} bytes" in out
    assert "mismatch (expected" in out
    assert "boot ok" in out
    assert fake.frames == 60
    assert fake.closed
    assert rc == 1


def test_check_rom_match_returns_zero(tmp_path, monkeypatch, capsys):
    rom = tmp_path / "fake.gb"
    data = b"pretend this is the real rom"
    rom.write_bytes(data)
    monkeypatch.setattr(cli, "EXPECTED_SHA1", hashlib.sha1(data).hexdigest().upper())
    monkeypatch.setattr(cli, "_build_emulator", lambda args: FakeEmulator())
    rc = cli.main(["check-rom", "--rom", str(rom)])
    out = capsys.readouterr().out
    assert "match" in out.split()
    assert "mismatch" not in out
    assert rc == 0


def test_state_prints_summary(tmp_path, monkeypatch, capsys):
    fake = FakeEmulator()
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(["state", "--rom", str(tmp_path / "any.gb")])
    out = capsys.readouterr().out
    assert "map=" in out
    assert "money=" in out
    assert fake.frames == 60
    assert fake.closed
    assert rc == 0


def test_state_loads_snapshot(tmp_path, monkeypatch, capsys):
    src = FakeEmulator({0xD35E: 0x26})
    snap = tmp_path / "s.state"
    src.save_state(snap)
    fake = FakeEmulator()
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(["state", "--state", str(snap)])
    out = capsys.readouterr().out
    assert "map=0x26" in out
    assert rc == 0


def test_rom_path_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("POKEAGENT_ROM", raising=False)
    args = SimpleNamespace(rom=None)
    assert cli._rom_path(args) == Path("roms/Pokemon Red.gb")
    monkeypatch.setenv("POKEAGENT_ROM", "env.gb")
    assert cli._rom_path(args) == Path("env.gb")
    args.rom = "cli.gb"
    assert cli._rom_path(args) == Path("cli.gb")
