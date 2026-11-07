"""After a settled step the next decision must not read the screen as 'still moving' (Readiness would mash an A)."""
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.readiness import BUSY_STABLE_FRAMES
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.press import Presser


def test_stillness_counter_is_restored_after_a_settled_move(tmp_path):
    emu = FakeEmulator({0xD35E: 0x0D, 0xD367: 0})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path)
    ctx.trans = open(tmp_path / "t.jsonl", "a", encoding="utf-8")
    ctx.stable_frames = 0
    Presser(ctx).press("UP", "agent", "test")
    assert ctx.stable_frames >= BUSY_STABLE_FRAMES
    ctx.trans.close()
