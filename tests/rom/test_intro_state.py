"""tools/make_intro_state.py boots a Gen 1 game from power-on to a controllable bedroom (controller/laptop only)."""
import subprocess
import sys

import pytest

from rom_helpers import ROM, ROM_BLUE, ROOT, rom_or_skip


@pytest.mark.parametrize("rom, what", [(ROM, "Red"), (ROM_BLUE, "Blue")])
def test_intro_reaches_a_controllable_bedroom(tmp_path, rom, what):
    rom = rom_or_skip(rom, what)
    out = tmp_path / "bedroom.state"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_intro_state.py"), "--rom", str(rom), "--out", str(out)],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "controllable=True" in r.stdout and out.exists()
    expected = "pokemon-blue" if what == "Blue" else "pokemon-red"
    assert f"game: {expected}" in r.stdout
