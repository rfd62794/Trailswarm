import pytest

from pokeagent import cli
from pokeagent.emulator import Button, FakeEmulator


class WalkingFake(FakeEmulator):
    """Fake where RIGHT bumps wXCoord and every tick/press bumps a timer."""

    def __init__(self, memory=None):
        super().__init__(memory)
        self._timer = 0

    def _bump_timer(self):
        self._timer += 1
        self.memory[0xC010] = self._timer

    def tick(self, frames):
        super().tick(frames)
        self._bump_timer()

    def press(self, button, hold_frames=8, settle_frames=16):
        super().press(button, hold_frames, settle_frames)
        if button is Button.RIGHT:
            self.memory[0xD362] = self.read(0xD362) + 1
        self._bump_timer()


def test_hex_help_lists_subcommands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["hex", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for word in ("dump", "diff", "find", "screen"):
        assert word in out


def test_hex_dump_shows_hex_ascii_and_names(monkeypatch, capsys):
    fake = FakeEmulator({0xD362: 4})
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(["hex", "dump", "--range", "D360-D370"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "D360" in out
    assert "04" in out
    assert "wXCoord" in out
    assert "wYCoord" in out
    assert fake.closed


def test_hex_diff_prints_annotated_changes(monkeypatch, capsys):
    fake = WalkingFake({0xD362: 3})
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(["hex", "diff", "--press", "RIGHT"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "D362 wXCoord 03 -> 04 (3 -> 4)" in out
    assert fake.presses == [Button.RIGHT]
    assert fake.closed


def test_hex_find_isolates_x_and_drops_idle_noise(monkeypatch, capsys):
    fake = WalkingFake({0xD362: 3})
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(
        ["hex", "find", "--press", "RIGHT", "--repeat", "3", "--delta", "1",
         "--idle", "3"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    # The timer byte at 0xC010 also moved on every press, but the idle
    # snapshots marked it noisy, so only wXCoord remains.
    assert out == "D362 wXCoord\n"
    assert fake.presses == [Button.RIGHT] * 3


def test_hex_screen_prints_decoded_tilemap(monkeypatch, capsys):
    fake = FakeEmulator()
    for i, t in enumerate([0x80, 0x81, 0x82]):  # "ABC"
        fake.set(0xC3A0 + i, t)
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(["hex", "screen"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ABC" in out


def test_hex_state_loads_snapshot(monkeypatch, capsys, tmp_path):
    src = WalkingFake({0xD362: 7})
    snap = tmp_path / "s.state"
    src.save_state(snap)
    fake = WalkingFake()
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    rc = cli.main(["hex", "diff", "--press", "RIGHT", "--state", str(snap)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "D362 wXCoord 07 -> 08 (7 -> 8)" in out
