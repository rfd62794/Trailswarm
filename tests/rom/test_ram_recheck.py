"""ROM-backed dry run of the invariants: every fixture state, zero fail expected.

Skips without the ROM (gitignored); the controller runs this on the laptop.
"""
import importlib.util
from pathlib import Path

from rom_helpers import STATES, load

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ram_recheck", ROOT / "tools" / "ram_recheck.py")
recheck_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recheck_tool)


def test_recheck_all_fixture_states_dry_run(rom_emu):
    from pokeagent.ramlab.labels import load_entries
    entries = load_entries()
    snaps = []
    for st in sorted(STATES.glob("*.state")):
        load(rom_emu, st.stem)
        snaps.append((st.stem, bytes(rom_emu.read_range(0xC000, 0x2000))))
    fails, _ = recheck_tool.report_and_promote(entries, snaps, today="2026-11-12", apply=False)
    assert fails == []
