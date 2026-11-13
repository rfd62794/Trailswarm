"""tools/make_intro_state.py boots Red from power-on to a controllable bedroom (controller/laptop only)."""
import subprocess
import sys
from pathlib import Path

import pytest

from rom_helpers import ROM, ROOT


def test_intro_reaches_a_controllable_bedroom(tmp_path):
    if not ROM.exists():
        pytest.skip("needs roms/Pokemon Red.gb (gitignored; the controller runs these)")
    out = tmp_path / "bedroom.state"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_intro_state.py"), "--rom", str(ROM), "--out", str(out)],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "controllable=True" in r.stdout and out.exists()
