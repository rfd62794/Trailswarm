"""Module-scoped emulator for the ROM-backed tests; skips cleanly without a ROM."""
import importlib.util
from pathlib import Path

import pytest

from rom_helpers import ROM


@pytest.fixture(scope="module")
def rom_emu():
    if not ROM.exists():
        pytest.skip("needs roms/Pokemon Red.gb (gitignored; the controller runs these)")
    from pokeagent.emulator import PyBoyEmulator
    emu = PyBoyEmulator(ROM, headless=True)
    try:
        yield emu
    finally:
        emu.close()


# With no __init__.py, every conftest.py lands in sys.modules under the bare name
# "conftest" and whichever loads last wins; tests/* do `from conftest import
# walkgrid, world, hdr`. Re-export the parent conftest's public names so those
# imports keep working when this module is the one occupying the slot.
_parent_conftest = Path(__file__).resolve().parents[1] / "conftest.py"
_spec = importlib.util.spec_from_file_location("_pokeagent_tests_conftest", _parent_conftest)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
for _name in dir(_mod):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_mod, _name)
